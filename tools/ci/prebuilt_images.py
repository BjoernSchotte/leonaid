#!/usr/bin/env python3
"""Prebuilt CI images on GHCR, tagged by content hash (decision E-020).

Images live at ``ghcr.io/bjoernschotte/leonaid-ci/<image>:<hash>``; the hash
is tools/testing/image_tags.py's content hash, so a tag names exactly one
set of build inputs. Services built from the same inputs (api and worker)
share one image.

``pull TARGETS``: every CI job that needs LeonAid images (build-cache action).
For each image of the bake targets or groups TARGETS: resolve the hash tag
anonymously, check the registry config (our hash label, age), pull by digest,
check the pulled image again and tag it ``leonaid-local/<service>:<hash>``,
where the test harness reuses it (image_tags.adopt). Writes the bake targets
that still have to be built to ``$GITHUB_OUTPUT`` (``bake=``) and the CI age
limit of the harness to ``$GITHUB_ENV``. Any failure
is a miss, and a miss is built locally as before: a registry problem costs
time, never a test. ``CI_PREBUILT_IMAGES=off`` (repository variable) makes
everything a miss.

``plan TARGETS``, ``publish``: the main-only publish job. ``plan`` lists the
images whose tag is missing or carries another hash and writes a bake
override (tags, labels) for them; ``publish`` checks each loaded image
for secrets (file names and image config here, Trivy's secret scanner in the
workflow), pushes it and verifies the pushed digest and label.

``adopt PROJECT CONFIG SERVICE...``: for scripts that run ``docker compose
build`` themselves (tools/ci/build.sh, the vulnerability gate, the API
contract): tag every shared image ``PROJECT-<service>`` like the harness
does (image_tags.adopt) and print the services still to build.

``check-clean IMAGE...``: the secret check alone (also for local images).

``cleanup [--dry-run]``: delete package versions older than 30 days whose
tags no current main commit references (the hashes of the checkout).

Standard library only; runs on the runner's ``python3 -I``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Any

ROOT = Path(__file__).resolve().parents[2]
# -I keeps the script directory off sys.path; import from the repository.
sys.path.insert(0, str(ROOT))

from tools.testing import image_tags  # noqa: E402

REGISTRY = "ghcr.io"
OWNER = "bjoernschotte"
NAMESPACE = f"{OWNER}/leonaid-ci"
SOURCE = "https://github.com/BjoernSchotte/leonaid"
HASH_LABEL = "io.leonaid.ci.content-hash"
REVISION_LABEL = "org.opencontainers.image.revision"
SOURCE_LABEL = "org.opencontainers.image.source"
HASH = re.compile(r"[0-9a-f]{24}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
NAME = re.compile(r"[a-z][a-z0-9-]*\Z")
# Age is the image's creation time, which BuildKit takes from the last step it
# really ran: a rebuild from cached layers (CI imports main's layer cache) and
# a republish keep it. Locally the harness reuses a shared tag for 7 days
# (image_tags.DEFAULT_MAX_AGE_DAYS: the Dockerfiles upgrade OS packages); CI
# builds from the same cached layers however old they are, so a pulled image
# is as current as a CI build. `pull` sets the harness limit to CI_MAX_AGE_DAYS
# and takes images one day younger, so an image stays usable for the run.
CI_MAX_AGE_DAYS = 30
PULL_MAX_AGE = timedelta(days=CI_MAX_AGE_DAYS - 1)
CLEANUP_AGE = timedelta(days=30)
KILL_SWITCH = "CI_PREBUILT_IMAGES"
HTTP_TIMEOUT = 20
PULL_TIMEOUT = 300
MANIFEST_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)
INDEX_TYPES = MANIFEST_TYPES[:2]
BAKE_FILE = ROOT / "tools/ci/docker-bake.hcl"
# Files that must never be in a public image (decision E-020).
FORBIDDEN_FILE = re.compile(
    r"(?:^|/)(?:\.env(?:\.(?!example\Z|sample\Z)[^/]+)?|sessions?\.env|"
    r"\.netrc|\.pgpass|\.git-credentials|id_(?:rsa|dsa|ecdsa|ed25519)|"
    r"\.docker/config\.json)\Z"
)
FORBIDDEN_DIRECTORY = re.compile(r"(?:^|/)\.git/")
# Environment variables of the image config that look like credentials.
SECRET_NAME = re.compile(r"(?i)(?:secret|password|passwd|token|api_?key|private_?key)")


class Unavailable(Exception):
    """A prebuilt image cannot be used; the job builds it itself."""


@dataclass(frozen=True)
class Image:
    """One published image: the services built from the same inputs."""

    name: str
    services: tuple[str, ...]
    content: str

    @property
    def repository(self) -> str:
        return f"{REGISTRY}/{NAMESPACE}/{self.name}"

    @property
    def tag(self) -> str:
        return f"{self.repository}:{self.content}"


@dataclass(frozen=True)
class Remote:
    digest: str
    labels: Mapping[str, str]
    created: datetime


# --- bake targets ---------------------------------------------------------


def bake_groups(text: str) -> dict[str, list[str]]:
    groups = {}
    for name, body in re.findall(
        r'(?m)^group "([a-z0-9-]+)" \{ targets = \[([^\]]*)\] \}$', text
    ):
        groups[name] = re.findall(r'"([a-z0-9-]+)"', body)
    return groups


def bake_targets(text: str) -> list[str]:
    return re.findall(r'(?m)^target "([a-z0-9-]+)" \{$', text)


def expand(selection: Iterable[str], text: str | None = None) -> list[str]:
    """Bake targets of target or group names (comma or space separated)."""
    text = BAKE_FILE.read_text(encoding="utf-8") if text is None else text
    groups, targets = bake_groups(text), set(bake_targets(text))
    result: list[str] = []

    def visit(name: str, depth: int) -> None:
        if depth > 8:
            raise ValueError(f"bake group cycle at {name}")
        if name in groups:
            for member in groups[name]:
                visit(member, depth + 1)
        elif name in targets:
            if name not in result:
                result.append(name)
        else:
            raise ValueError(f"unknown bake target or group {name!r}")

    for item in selection:
        for name in re.split(r"[\s,]+", item.strip()):
            if name:
                visit(name, 0)
    return result


def images_for(
    services: Sequence[str], hasher: Callable[[str], str]
) -> tuple[list[Image], dict[str, str]]:
    """Group services by image; return images and {service: reason} misses.

    Services with the same build section share one image, named after the
    first of them in image_tags.BUILDS (worker uses api's)."""
    canonical: dict[str, str] = {}
    for service, build in image_tags.BUILDS.items():
        first = next(
            name for name, other in image_tags.BUILDS.items() if other == build
        )
        canonical[service] = first
    grouped: dict[tuple[str, str], list[str]] = {}
    misses: dict[str, str] = {}
    for service in services:
        if service not in canonical:
            misses[service] = "no shared build"
            continue
        try:
            content = hasher(service)
        except (image_tags.Unsupported, OSError) as error:
            misses[service] = f"not hashable ({error})"
            continue
        if not HASH.match(content):
            misses[service] = "unexpected hash format"
            continue
        grouped.setdefault((canonical[service], content), []).append(service)
    images = [
        Image(name, tuple(members), content)
        for (name, content), members in grouped.items()
    ]
    return images, misses


# --- registry -------------------------------------------------------------


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """Follow blob redirects without sending the registry token elsewhere."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and (
            urllib.parse.urlsplit(newurl).netloc
            != urllib.parse.urlsplit(req.full_url).netloc
        ):
            new.remove_header("Authorization")
        return new


_OPENER = urllib.request.build_opener(_SameHostRedirect)


def http_get(url: str, headers: Mapping[str, str]) -> tuple[bytes, Mapping[str, str]]:
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with _OPENER.open(request, timeout=HTTP_TIMEOUT) as response:
            return response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as error:
        raise Unavailable(f"HTTP {error.code} for {url}") from None
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise Unavailable(f"{url}: {error}") from None


class Registry:
    """Read-only Docker Registry v2 client for one repository."""

    def __init__(
        self,
        repository: str,
        token: str | None = None,
        get: Callable[[str, Mapping[str, str]], tuple[bytes, Mapping[str, str]]] = (
            http_get
        ),
    ) -> None:
        self.repository = repository
        self.secret = token
        self.get = get
        self.bearer: str | None = None

    def _auth(self) -> dict[str, str]:
        if self.bearer is None:
            scope = urllib.parse.quote(f"repository:{self.repository}:pull", safe=":/")
            headers = {}
            if self.secret:
                basic = base64.b64encode(f"x:{self.secret}".encode()).decode()
                headers["Authorization"] = f"Basic {basic}"
            body, _ = self.get(
                f"https://{REGISTRY}/token?service={REGISTRY}&scope={scope}", headers
            )
            try:
                self.bearer = str(json.loads(body)["token"])
            except (ValueError, KeyError, TypeError):
                raise Unavailable("registry token response unreadable") from None
        return {"Authorization": f"Bearer {self.bearer}"}

    def _verified(self, reference: str, accept: str) -> tuple[bytes, dict[str, Any]]:
        body, headers = self.get(
            f"https://{REGISTRY}/v2/{self.repository}/manifests/{reference}",
            {**self._auth(), "Accept": accept},
        )
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        if DIGEST.match(reference) and digest != reference:
            raise Unavailable(f"manifest {reference} does not match its digest")
        announced = {k.lower(): v for k, v in headers.items()}.get(
            "docker-content-digest"
        )
        if announced and announced != digest:
            raise Unavailable("registry digest header does not match the manifest")
        try:
            manifest = json.loads(body)
        except ValueError:
            raise Unavailable("manifest is not JSON") from None
        if not isinstance(manifest, dict):
            raise Unavailable("manifest is not an object")
        return body, manifest

    def resolve(self, tag: str) -> Remote:
        body, manifest = self._verified(tag, ", ".join(MANIFEST_TYPES))
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        image = manifest
        if manifest.get("mediaType") in INDEX_TYPES or "manifests" in manifest:
            choices = [
                entry
                for entry in manifest.get("manifests", [])
                if isinstance(entry, dict)
                and entry.get("platform", {}).get("os") == "linux"
                and entry.get("platform", {}).get("architecture") == "amd64"
            ]
            if len(choices) != 1 or not DIGEST.match(str(choices[0].get("digest"))):
                raise Unavailable("index has no single linux/amd64 image")
            _, image = self._verified(
                str(choices[0]["digest"]), ", ".join(MANIFEST_TYPES[2:])
            )
        config_digest = str(image.get("config", {}).get("digest", ""))
        if not DIGEST.match(config_digest):
            raise Unavailable("manifest has no config digest")
        blob, _ = self.get(
            f"https://{REGISTRY}/v2/{self.repository}/blobs/{config_digest}",
            self._auth(),
        )
        if "sha256:" + hashlib.sha256(blob).hexdigest() != config_digest:
            raise Unavailable("config blob does not match its digest")
        try:
            config = json.loads(blob)
        except ValueError:
            raise Unavailable("config is not JSON") from None
        labels = (config.get("config") or {}).get("Labels") or {}
        return Remote(digest, dict(labels), parse_time(str(config.get("created"))))


def parse_time(stamp: str) -> datetime:
    """RFC 3339 with up to nanoseconds, as Docker and BuildKit write it."""
    text = re.sub(r"(\.\d{6})\d*", r"\1", stamp.strip()).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise Unavailable(f"unreadable creation time {stamp!r}") from None
    if parsed.tzinfo is None:
        raise Unavailable(f"creation time without zone {stamp!r}")
    return parsed


def check_remote(
    image: Image, remote: Remote, now: datetime, max_age: timedelta | None
) -> None:
    found = remote.labels.get(HASH_LABEL)
    if found != image.content:
        raise Unavailable(f"label {HASH_LABEL}={found!r}, expected {image.content}")
    if max_age is not None and now - remote.created > max_age:
        raise Unavailable(
            f"built {remote.created:%Y-%m-%d}, older than {max_age.days} days"
        )


# --- docker ---------------------------------------------------------------


def docker(*arguments: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def inspect(reference: str, run: Callable[..., Any] = docker) -> dict[str, Any]:
    result = run("image", "inspect", "--format", "{{json .}}", reference)
    if result.returncode != 0:
        raise Unavailable(f"image {reference} not present")
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise Unavailable(f"image {reference}: unreadable inspect output")
    return data


def fetch(
    image: Image,
    now: datetime,
    registry: Registry | None = None,
    run: Callable[..., Any] = docker,
) -> str:
    """Pull IMAGE by digest, verify it and tag it for every service; return
    the digest. Raises Unavailable; a verified image is never left half-tagged."""
    registry = registry or Registry(f"{NAMESPACE}/{image.name}")
    remote = registry.resolve(image.content)
    check_remote(image, remote, now, PULL_MAX_AGE)
    pinned = f"{image.repository}@{remote.digest}"
    try:
        result = run("pull", "--quiet", pinned, timeout=PULL_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise Unavailable(f"pull of {pinned} timed out") from None
    if result.returncode != 0:
        raise Unavailable(f"pull failed: {result.stderr.strip()[-300:]}")
    data = inspect(pinned, run)
    labels = (data.get("Config") or {}).get("Labels") or {}
    if labels.get(HASH_LABEL) != image.content:
        run("image", "rm", pinned)
        raise Unavailable("pulled image carries another content hash")
    if pinned not in (data.get("RepoDigests") or []):
        run("image", "rm", pinned)
        raise Unavailable("pulled image does not carry the resolved digest")
    tagged: list[str] = []
    for service in image.services:
        local = f"{image_tags.REPOSITORY}/{service}:{image.content}"
        if run("tag", pinned, local).returncode != 0:
            for reference in tagged:
                run("image", "rm", reference)
            raise Unavailable(f"could not tag {local}")
        tagged.append(local)
    return remote.digest


def kill_switch(environ: Mapping[str, str]) -> bool:
    return environ.get(KILL_SWITCH, "").strip().lower() in {"off", "false", "0"}


def pull(
    selection: Sequence[str],
    environ: Mapping[str, str],
    hasher: Callable[[str], str] | None = None,
    fetcher: Callable[[Image, datetime], str] | None = None,
    now: datetime | None = None,
) -> tuple[list[str], list[str]]:
    """Return (bake targets still to build, report lines). Never raises for
    registry or Docker problems: those are misses."""
    targets = expand(selection)
    if environ.get("PREBUILT_ENABLED", "true") != "true":
        return targets, [
            "prebuilt images: not used by this step (cache write or benchmark)"
        ]
    if kill_switch(environ):
        return targets, [f"prebuilt images: off ({KILL_SWITCH}); building locally"]
    hasher = hasher or (lambda service: image_tags.content_hash(ROOT, service))
    fetcher = fetcher or fetch
    now = now or datetime.now(timezone.utc)
    images, misses = images_for(targets, hasher)
    report = [f"miss {service}: {reason}" for service, reason in misses.items()]

    def attempt(image: Image) -> tuple[Image, str | None, str]:
        try:
            return image, fetcher(image, now), ""
        except Unavailable as error:
            return image, None, str(error)
        except Exception as error:  # noqa: BLE001 - any failure is a miss
            return image, None, f"unexpected {type(error).__name__}: {error}"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, images))
    built = set(misses)
    for image, digest, reason in results:
        names = "+".join(image.services)
        if digest:
            report.append(f"hit  {names}: {image.repository}@{digest}")
        else:
            built.update(image.services)
            report.append(f"miss {names}: {image.tag}: {reason}")
    return [target for target in targets if target in built], report


# --- secrets --------------------------------------------------------------


def forbidden_paths(names: Iterable[str]) -> list[str]:
    found = []
    for raw in names:
        name = raw.removeprefix("./")
        if FORBIDDEN_FILE.search(name) or FORBIDDEN_DIRECTORY.search(name + "/"):
            found.append(name)
    return sorted(set(found))


def secret_environment(config: Mapping[str, Any]) -> list[str]:
    found = []
    for entry in (config.get("Config") or {}).get("Env") or []:
        name, _, value = str(entry).partition("=")
        if SECRET_NAME.search(name) and value:
            found.append(name)
    for name, value in ((config.get("Config") or {}).get("Labels") or {}).items():
        if SECRET_NAME.search(str(name)) and value:
            found.append(f"label {name}")
    return found


def archive_names(stream: IO[bytes]) -> list[str]:
    with tarfile.open(fileobj=stream, mode="r|") as archive:
        return [member.name for member in archive]


def check_clean(reference: str, run: Callable[..., Any] = docker) -> list[str]:
    """Problems that forbid publishing REFERENCE (empty list: clean)."""
    problems = [
        f"credential-like {name}"
        for name in secret_environment(inspect(reference, run))
    ]
    created = run("create", reference, "/nonexistent")
    if created.returncode != 0:
        return [*problems, f"cannot create a container: {created.stderr.strip()}"]
    container = created.stdout.strip()
    names: list[str] = []
    try:
        with subprocess.Popen(
            ["docker", "export", container], stdout=subprocess.PIPE
        ) as export:
            if export.stdout is None:
                raise Unavailable("docker export produced no stream")
            try:
                names = archive_names(export.stdout)
            except tarfile.TarError as error:
                problems.append(f"unreadable export ({error})")
        if export.returncode != 0:
            problems.append("docker export failed")
    finally:
        run("rm", "--force", container)
    problems += [f"forbidden file {name}" for name in forbidden_paths(names)]
    return problems + trivy_secrets(reference, run)


def trivy_secrets(reference: str, run: Callable[..., Any] = docker) -> list[str]:
    """Trivy's secret scanner over the image (TRIVY_IMAGE, infra/locks/images.env)."""
    result = run(
        "run",
        "--rm",
        "--network",
        "none",
        "--volume",
        "/var/run/docker.sock:/var/run/docker.sock:ro",
        locked_image("TRIVY_IMAGE"),
        "image",
        "--scanners",
        "secret",
        "--image-src",
        "docker",
        "--exit-code",
        "0",
        "--quiet",
        "--format",
        "json",
        reference,
        timeout=900,
    )
    if result.returncode != 0:
        return [f"secret scan failed: {result.stderr.strip()[-300:]}"]
    try:
        report = json.loads(result.stdout)
    except ValueError:
        return ["secret scan output unreadable"]
    found = []
    for entry in report.get("Results") or []:
        for secret in entry.get("Secrets") or []:
            found.append(
                f"secret {secret.get('RuleID')} in {entry.get('Target')}"
                f":{secret.get('StartLine')}"
            )
    return found


def locked_image(name: str) -> str:
    text = (ROOT / "infra/locks/images.env").read_text(encoding="utf-8")
    match = re.search(rf"(?m)^{name}=(\S+@sha256:[0-9a-f]{{64}})$", text)
    if not match:
        raise Unavailable(f"{name} is not pinned in infra/locks/images.env")
    return match.group(1)


# --- publish (main only) ---------------------------------------------------


def plan(
    selection: Sequence[str],
    environ: Mapping[str, str],
    hasher: Callable[[str], str] | None = None,
    resolver: Callable[[Image], Remote] | None = None,
    now: datetime | None = None,
) -> tuple[list[Image], dict[str, Any], list[str]]:
    """Images to (re)publish, the bake override for them, report lines."""
    hasher = hasher or (lambda service: image_tags.content_hash(ROOT, service))
    token = environ.get("GITHUB_TOKEN")
    resolver = resolver or (
        lambda image: Registry(f"{NAMESPACE}/{image.name}", token).resolve(
            image.content
        )
    )
    now = now or datetime.now(timezone.utc)
    revision = environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("GITHUB_SHA must be the commit being published")
    images, misses = images_for(expand(selection), hasher)
    report = [f"skip {service}: {reason}" for service, reason in misses.items()]
    todo = []
    for image in images:
        try:
            check_remote(image, resolver(image), now, None)
            report.append(f"current {image.tag}")
            continue
        except Unavailable as error:
            report.append(f"publish {image.tag}: {error}")
        todo.append(image)
    override: dict[str, Any] = {"target": {}}
    for image in todo:
        override["target"][image.name] = {
            "tags": [image.tag],
            "labels": {
                HASH_LABEL: image.content,
                REVISION_LABEL: revision,
                SOURCE_LABEL: SOURCE,
            },
        }
    return todo, override, report


def publish(
    images: Sequence[Image],
    environ: Mapping[str, str],
    run: Callable[..., Any] = docker,
    cleaner: Callable[[str], list[str]] | None = None,
    resolver: Callable[[Image, str | None], Remote] | None = None,
) -> tuple[bool, list[str]]:
    """Check, push and verify each image; return (all pushed, report)."""
    cleaner = cleaner or (lambda reference: check_clean(reference, run))
    resolver = resolver or (
        lambda image, token: Registry(f"{NAMESPACE}/{image.name}", token).resolve(
            image.content
        )
    )
    token = environ.get("GITHUB_TOKEN")
    report: list[str] = []
    ok = True
    for image in images:
        labels = ((inspect(image.tag, run).get("Config") or {}).get("Labels")) or {}
        if labels.get(HASH_LABEL) != image.content:
            report.append(f"FAILED {image.tag}: built image lacks the hash label")
            ok = False
            continue
        problems = cleaner(image.tag)
        if problems:
            report.append(f"FAILED {image.tag}: not published: {'; '.join(problems)}")
            ok = False
            continue
        pushed = run("push", "--quiet", image.tag, timeout=900)
        if pushed.returncode != 0:
            report.append(f"FAILED {image.tag}: push: {pushed.stderr.strip()[-300:]}")
            ok = False
            continue
        try:
            remote = resolver(image, token)
            check_remote(image, remote, datetime.now(timezone.utc), None)
        except Unavailable as error:
            report.append(f"FAILED {image.tag}: pushed but not verifiable: {error}")
            ok = False
            continue
        report.append(f"pushed {image.tag} {remote.digest}")
        try:
            resolver(image, None)
        except Unavailable as error:
            report.append(
                f"::warning title=GHCR package not public::{image.repository} cannot "
                f"be pulled anonymously ({error}); pull requests build it themselves "
                "until its visibility is public"
            )
    return ok, report


# --- cleanup --------------------------------------------------------------


def stale_versions(
    versions: Sequence[Mapping[str, Any]], keep: set[str], now: datetime
) -> list[tuple[int, list[str], str]]:
    """(id, tags, reason) of versions to delete: created more than 30 days
    ago and without a tag in KEEP. Versions with a tag that is no content
    hash were not made by CI and are never touched."""
    result = []
    for version in versions:
        tags = list(
            ((version.get("metadata") or {}).get("container") or {}).get("tags") or []
        )
        if any(not HASH.match(str(tag)) for tag in tags):
            continue
        if keep & set(tags):
            continue
        try:
            created = parse_time(str(version.get("created_at")))
        except Unavailable:
            continue
        if now - created <= CLEANUP_AGE:
            continue
        reason = "untagged" if not tags else "unreferenced"
        result.append(
            (int(version["id"]), tags, f"{reason}, created {created:%Y-%m-%d}")
        )
    return result


def api(method: str, path: str, token: str) -> Any:
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        body = response.read()
    return json.loads(body) if body else None


def cleanup(
    dry_run: bool,
    token: str,
    hasher: Callable[[str], str] | None = None,
    call: Callable[[str, str, str], Any] = api,
    now: datetime | None = None,
) -> tuple[bool, list[str]]:
    hasher = hasher or (lambda service: image_tags.content_hash(ROOT, service))
    now = now or datetime.now(timezone.utc)
    images, misses = images_for(list(image_tags.BUILDS), hasher)
    if misses:
        # Without every current hash a referenced tag could be deleted.
        return False, [
            f"cannot hash {service}: {why}" for service, why in misses.items()
        ]
    report: list[str] = []
    ok = True
    for image in sorted(images, key=lambda item: item.name):
        package = urllib.parse.quote(f"leonaid-ci/{image.name}", safe="")
        base = f"/users/{OWNER}/packages/container/{package}/versions"
        versions: list[Mapping[str, Any]] = []
        try:
            for page in range(1, 51):
                batch = call("GET", f"{base}?per_page=100&page={page}", token)
                versions += batch
                if len(batch) < 100:
                    break
        except urllib.error.HTTPError as error:
            if error.code == 404:
                report.append(f"{image.name}: no package yet")
                continue
            report.append(f"{image.name}: listing failed: HTTP {error.code}")
            ok = False
            continue
        stale = stale_versions(versions, {image.content}, now)
        report.append(
            f"{image.name}: {len(versions)} versions, keeps {image.content}, "
            f"{len(stale)} to delete"
        )
        for version_id, tags, reason in stale:
            label = ",".join(tags) or "-"
            if dry_run:
                report.append(f"  would delete {version_id} ({label}; {reason})")
                continue
            try:
                call("DELETE", f"{base}/{version_id}", token)
                report.append(f"  deleted {version_id} ({label}; {reason})")
            except urllib.error.HTTPError as error:
                report.append(f"  delete {version_id} failed: HTTP {error.code}")
                ok = False
    return ok, report


# --- command line ---------------------------------------------------------


def write_output(environ: Mapping[str, str], **values: str) -> None:
    path = environ.get("GITHUB_OUTPUT")
    lines = []
    for key, value in values.items():
        if "\n" in value or "\r" in value:
            raise ValueError(f"output {key} must be one line")
        lines.append(f"{key}={value}\n")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.writelines(lines)
    else:
        sys.stdout.writelines(lines)


def summary(environ: Mapping[str, str], title: str, lines: Sequence[str]) -> None:
    for line in lines:
        print(line if line.startswith("::") else f"prebuilt-images: {line}")
    path = environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"### {title}\n\n")
            handle.writelines(
                f"- `{line}`\n" for line in lines if not line.startswith("::")
            )
            handle.write("\n")


def main(
    argv: Sequence[str] | None = None, environ: Mapping[str, str] = os.environ
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("pull", "plan"):
        command = commands.add_parser(name)
        command.add_argument("targets", nargs="+")
    commands.add_parser("publish").add_argument("plan", type=Path)
    commands.add_parser("check-clean").add_argument("images", nargs="+")
    adopting = commands.add_parser("adopt")
    adopting.add_argument("project")
    adopting.add_argument(
        "config", type=Path, help="docker compose config --format json"
    )
    adopting.add_argument("services", nargs="*")
    cleaning = commands.add_parser("cleanup")
    cleaning.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "pull":
        try:
            build, report = pull(args.targets, environ)
        except Exception as error:  # noqa: BLE001 - fall back to the local build
            build = expand(args.targets)
            report = [f"failed ({type(error).__name__}: {error}); building locally"]
        hits = len(expand(args.targets)) - len(build)
        write_output(environ, bake=",".join(build), hits=str(hits))
        if hits and environ.get("GITHUB_ENV"):
            # The harness, build.sh and the vulnerability gate accept the
            # pulled images (see CI_MAX_AGE_DAYS) in the following steps.
            with open(environ["GITHUB_ENV"], "a", encoding="utf-8") as handle:
                handle.write(f"LEONAID_IMAGE_MAX_AGE_DAYS={CI_MAX_AGE_DAYS}\n")
        summary(environ, "Prebuilt images", report)
        return 0
    if args.command == "plan":
        todo, override, report = plan(args.targets, environ)
        directory = Path(environ.get("RUNNER_TEMP") or "/tmp")
        override_path = directory / "prebuilt-images.bake.json"
        override_path.write_text(json.dumps(override, indent=2), encoding="utf-8")
        plan_path = directory / "prebuilt-images.plan.json"
        plan_path.write_text(
            json.dumps(
                [image.__dict__ | {"services": list(image.services)} for image in todo]
            ),
            encoding="utf-8",
        )
        write_output(
            environ,
            targets=",".join(image.name for image in todo),
            override=str(override_path),
            plan=str(plan_path),
        )
        summary(environ, "Prebuilt image plan", report)
        return 0
    if args.command == "publish":
        entries = json.loads(args.plan.read_text(encoding="utf-8"))
        images = []
        for entry in entries:
            image = Image(
                str(entry["name"]), tuple(entry["services"]), str(entry["content"])
            )
            if not NAME.match(image.name) or not HASH.match(image.content):
                raise ValueError(f"invalid plan entry {entry!r}")
            images.append(image)
        ok, report = publish(images, environ)
        summary(environ, "Published prebuilt images", report)
        return 0 if ok else 1
    if args.command == "adopt":
        if not re.fullmatch(r"leonaid(?:-[a-z0-9-]+)?", args.project):
            parser.error("project must be a leonaid Compose project")
        config = json.loads(args.config.read_text(encoding="utf-8"))
        services = args.services or [
            name
            for name, service in sorted(config.get("services", {}).items())
            if "build" in service
        ]
        missing = image_tags.adopt(
            ROOT, args.project, image_tags.effective_builds(config), services
        )
        print(" ".join(missing))
        return 0
    if args.command == "check-clean":
        failed = False
        for reference in args.images:
            problems = check_clean(reference)
            for problem in problems:
                print(f"prebuilt-images: {reference}: {problem}", file=sys.stderr)
            failed = failed or bool(problems)
            if not problems:
                print(f"prebuilt-images: {reference}: clean")
        return 1 if failed else 0
    token = environ.get("GITHUB_TOKEN", "")
    if not token:
        parser.error("cleanup needs GITHUB_TOKEN")
    ok, report = cleanup(args.dry_run, token)
    summary(
        environ,
        "Prebuilt image cleanup" + (" (dry run)" if args.dry_run else ""),
        report,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
