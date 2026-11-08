#!/usr/bin/env python3
"""Prebuilt CI images on GHCR by content hash (decision E-020).

``ghcr.io/bjoernschotte/leonaid-ci/<service>:<hash>``; the hash is
tools/testing/image_tags.py's content hash. Only main publishes.

pull TARGETS     pull each image of the bake targets/groups, check its hash
                 label, tag it leonaid-local/<service>:<hash> (the harness
                 reuses it); write the misses to $GITHUB_OUTPUT as bake=...
                 Every failure is a miss, and a miss is built as before.
plan TARGETS     main: the images whose tag is missing (all with --all), as
                 a bake override with tags and the hash label
publish PLAN     main: secret check (forbidden files, Trivy), then push
adopt PROJECT CONFIG [SERVICE...]
                 tag present shared images as PROJECT-<service>, print the
                 services still to build (build.sh, vulnerability gate)
check-clean IMAGE...  the secret check alone

Standard library only; runs on the runner's ``python3 -I``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
# -I keeps the script directory off sys.path; import from the repository.
sys.path.insert(0, str(ROOT))

from tools.testing import image_tags  # noqa: E402

REPOSITORY = "ghcr.io/bjoernschotte/leonaid-ci"
SOURCE = "https://github.com/BjoernSchotte/leonaid"
HASH_LABEL = "io.leonaid.ci.content-hash"
BAKE_FILE = ROOT / "tools/ci/docker-bake.hcl"
PULL_TIMEOUT = 120
# Files that must never be in a public image.
FORBIDDEN = re.compile(
    r"(?:^|/)(?:\.env(?:\.(?!example\Z)[^/]+)?|sessions?\.env|\.netrc|\.pgpass|"
    r"\.git-credentials|id_(?:rsa|ecdsa|ed25519)|\.docker/config\.json|\.git/.*)\Z"
)

Run = Callable[..., Any]


def docker(*arguments: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def expand(selection: Iterable[str], text: str | None = None) -> list[str]:
    """Bake targets of target or group names (comma or space separated)."""
    text = BAKE_FILE.read_text(encoding="utf-8") if text is None else text
    groups = {
        name: re.findall(r'"([a-z0-9-]+)"', body)
        for name, body in re.findall(
            r'(?m)^group "([a-z0-9-]+)" \{ targets = \[([^\]]*)\] \}$', text
        )
    }
    targets = set(re.findall(r'(?m)^target "([a-z0-9-]+)" \{$', text))
    result: list[str] = []

    def visit(name: str) -> None:
        if name in groups:
            for member in groups[name]:
                visit(member)
        elif name in targets:
            if name not in result:
                result.append(name)
        else:
            raise ValueError(f"unknown bake target or group {name!r}")

    for item in selection:
        for name in re.split(r"[\s,]+", item.strip()):
            if name:
                visit(name)
    return result


def content(service: str) -> str:
    return image_tags.content_hash(ROOT, service)


def fetch(service: str, hasher: Callable[[str], str], run: Run = docker) -> str:
    """Pull and tag one image; return a report line. Raise on a miss."""
    digest = hasher(service)
    remote = f"{REPOSITORY}/{service}:{digest}"
    if run("pull", "--quiet", remote, timeout=PULL_TIMEOUT).returncode != 0:
        raise LookupError(f"{remote} not available")
    found = run(
        "image", "inspect", "--format", f'{{{{index .Config.Labels "{HASH_LABEL}"}}}}', remote
    )  # fmt: skip
    if found.stdout.strip() != digest:
        run("image", "rm", remote)
        raise LookupError(f"{remote} carries another content hash")
    local = f"{image_tags.REPOSITORY}/{service}:{digest}"
    if run("tag", remote, local).returncode != 0:
        raise LookupError(f"could not tag {local}")
    return f"hit  {remote}"


def pull(
    selection: Sequence[str], hasher: Callable[[str], str] = content, run: Run = docker
) -> tuple[list[str], list[str]]:
    """(bake targets still to build, report lines); never raises on a miss."""
    targets = expand(selection)

    def attempt(service: str) -> tuple[str, str]:
        try:
            return service, fetch(service, hasher, run)
        except Exception as error:  # noqa: BLE001 - every failure is a miss
            return service, f"miss {service}: {error}"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, targets))
    misses = [service for service, line in results if not line.startswith("hit")]
    return misses, [line for _, line in results]


def plan(
    selection: Sequence[str],
    revision: str,
    everything: bool = False,
    hasher: Callable[[str], str] = content,
    run: Run = docker,
) -> dict[str, Any]:
    """Bake override for the images to publish (missing tags, or all)."""
    override: dict[str, Any] = {"target": {}}
    for service in expand(selection):
        digest = hasher(service)
        tag = f"{REPOSITORY}/{service}:{digest}"
        if not everything and run("manifest", "inspect", tag).returncode == 0:
            continue
        override["target"][service] = {
            "tags": [tag],
            "labels": {
                HASH_LABEL: digest,
                "org.opencontainers.image.revision": revision,
                "org.opencontainers.image.source": SOURCE,
            },
        }
    return override


def forbidden(names: Iterable[str]) -> list[str]:
    paths = {name.removeprefix("./") for name in names}
    return sorted(path for path in paths if FORBIDDEN.search(path))


def locked_image(name: str) -> str:
    text = (ROOT / "infra/locks/images.env").read_text(encoding="utf-8")
    match = re.search(rf"(?m)^{name}=(\S+@sha256:[0-9a-f]{{64}})$", text)
    if not match:
        raise LookupError(f"{name} is not pinned in infra/locks/images.env")
    return match.group(1)


def check_clean(reference: str, run: Run = docker) -> list[str]:
    """Problems that forbid publishing REFERENCE (empty: clean)."""
    created = run("create", reference, "/nonexistent")
    if created.returncode != 0:
        return [f"cannot create a container: {created.stderr.strip()}"]
    container = created.stdout.strip()
    try:
        command = ["docker", "export", container]
        with subprocess.Popen(command, stdout=subprocess.PIPE) as export:
            assert export.stdout is not None
            with tarfile.open(fileobj=export.stdout, mode="r|") as archive:
                names = [member.name for member in archive]
        problems = [f"forbidden file {name}" for name in forbidden(names)]
        if export.returncode != 0:
            problems.append("docker export failed")
    finally:
        run("rm", "--force", container)
    scan = run(
        "run", "--rm", "--network", "none",
        "--volume", "/var/run/docker.sock:/var/run/docker.sock:ro",
        locked_image("TRIVY_IMAGE"), "image", "--scanners", "secret",
        "--image-src", "docker", "--quiet", "--format", "json", reference,
        timeout=900,
    )  # fmt: skip
    if scan.returncode != 0:
        return [*problems, f"secret scan failed: {scan.stderr.strip()[-300:]}"]
    for entry in json.loads(scan.stdout).get("Results") or []:
        for secret in entry.get("Secrets") or []:
            problems.append(f"secret {secret.get('RuleID')} in {entry.get('Target')}")
    return problems


def publish(
    tags: Sequence[str],
    run: Run = docker,
    cleaner: Callable[[str], list[str]] | None = None,
) -> list[str]:
    """Push every clean image; return the failures."""
    cleaner = cleaner or (lambda reference: check_clean(reference, run))
    failures = []
    for tag in tags:
        problems = cleaner(tag)
        if not problems and run("push", "--quiet", tag, timeout=900).returncode != 0:
            problems = ["push failed"]
        if problems:
            failures.append(f"{tag}: {'; '.join(problems)}")
        else:
            print(f"prebuilt-images: pushed {tag}")
    return failures


def output(environ: Mapping[str, str], **values: str) -> None:
    path = environ.get("GITHUB_OUTPUT") or os.devnull
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            if "\n" in value:
                raise ValueError(f"output {key} must be one line")
            handle.write(f"{key}={value}\n")


def main(
    argv: Sequence[str] | None = None, environ: Mapping[str, str] = os.environ
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pull").add_argument("targets", nargs="+")
    planning = commands.add_parser("plan")
    planning.add_argument("--all", action="store_true")
    planning.add_argument("targets", nargs="+")
    commands.add_parser("publish").add_argument("plan", type=Path)
    commands.add_parser("check-clean").add_argument("images", nargs="+")
    adopting = commands.add_parser("adopt")
    adopting.add_argument("project")
    adopting.add_argument("config", type=Path)
    adopting.add_argument("services", nargs="*")
    args = parser.parse_args(argv)

    if args.command == "pull":
        misses, report = pull(args.targets)
        for line in report:
            print(f"prebuilt-images: {line}")
        output(environ, bake=",".join(misses))
        return 0
    if args.command == "plan":
        revision = environ.get("GITHUB_SHA", "")
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            parser.error("GITHUB_SHA must be the commit being published")
        override = plan(args.targets, revision, args.all)
        path = Path(environ.get("RUNNER_TEMP") or "/tmp") / "prebuilt-images.bake.json"
        path.write_text(json.dumps(override), encoding="utf-8")
        print(f"prebuilt-images: to publish: {sorted(override['target'])}")
        output(environ, targets=",".join(override["target"]), override=str(path))
        return 0
    if args.command == "publish":
        targets = json.loads(args.plan.read_text(encoding="utf-8"))["target"]
        failures = publish([target["tags"][0] for target in targets.values()])
        for failure in failures:
            print(f"prebuilt-images: NOT published: {failure}", file=sys.stderr)
        return 1 if failures else 0
    if args.command == "adopt":
        if not re.fullmatch(r"leonaid(?:-[a-z0-9-]+)?", args.project):
            parser.error("project must be a leonaid Compose project")
        config = json.loads(args.config.read_text(encoding="utf-8"))
        services = args.services or [
            name
            for name, service in sorted(config.get("services", {}).items())
            if "build" in service
        ]
        builds = image_tags.effective_builds(config)
        print(" ".join(image_tags.adopt(ROOT, args.project, builds, services)))
        return 0
    failed = False
    for reference in args.images:
        problems = check_clean(reference)
        for problem in problems:
            print(f"prebuilt-images: {reference}: {problem}", file=sys.stderr)
        print(f"prebuilt-images: {reference}: {'NOT clean' if problems else 'clean'}")
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
