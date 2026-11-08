#!/usr/bin/env python3
"""Content-hash tags for the images Compose builds, shared by all checkouts.

`python3 tools/testing/image_tags.py SERVICE` prints the 24-hex content hash
of SERVICE's image as built from infra/compose/compose.yml: sha256 over the
Docker platform, the build definition, the Dockerfile, the context's
.dockerignore and every file the Dockerfile copies from the context (after
.dockerignore), with its mode. Identical inputs produce identical tags in every
worktree, so one build serves all of them (`leonaid-local/<service>:<hash>`;
CI may push the same hash to a registry).

It exits non-zero, with nothing on stdout, when the inputs cannot be
determined completely (a FROM or COPY --from without digest, ADD of a URL, a
bind/secret/ssh mount, build secrets, unsupported .dockerignore syntax):
callers then build without sharing.

Stdlib only; CI runs it on the runner's Python before any bootstrap.

Test-harness helpers, given the project's `docker compose config --format
json` so overlays that change a build are hashed as Compose runs them:
  image_tags.py adopt PROJECT CONFIG SERVICE...
      tag shared images as PROJECT-SERVICE; print "SERVICE HASH" (or
      "SERVICE -" when not shareable) for each service still to build
  image_tags.py record PROJECT CONFIG SERVICE=HASH...
      after the build, tag PROJECT-SERVICE as its shared tag only if the
      inputs still hash to HASH (nothing changed while it was building)
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
# Tests use their own repository so they never touch the shared tags.
REPOSITORY = os.environ.get("LEONAID_IMAGE_REPOSITORY", "leonaid-local")
VERSION = "image-tags-v2"
# The `build:` sections of infra/compose/compose.yml, for the CLI without a
# rendered config (CI before bootstrap). A test compares them with Compose.
BUILDS: dict[str, dict[str, str]] = {
    "api": {"context": ".", "dockerfile": "infra/compose/Dockerfile.core"},
    "worker": {"context": ".", "dockerfile": "infra/compose/Dockerfile.core"},
    "web": {"context": ".", "dockerfile": "infra/compose/Dockerfile.web"},
    "pwa": {"context": ".", "dockerfile": "infra/compose/Dockerfile.pwa"},
    "public": {"context": ".", "dockerfile": "infra/compose/Dockerfile.public"},
    "survey-validator": {
        "context": ".",
        "dockerfile": "infra/compose/Dockerfile.survey-validator",
    },
    "campaign-site": {
        "context": ".",
        "dockerfile": "infra/compose/Dockerfile.campaign-site",
    },
    "proxy": {"context": "infra/proxy/image", "dockerfile": "Dockerfile"},
}
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\Z")
# Build keys whose inputs this module cannot hash.
UNSUPPORTED_BUILD_KEYS = {"secrets", "ssh", "additional_contexts", "dockerfile_inline"}
DEFAULT_KEEP = 4
# Dockerfiles upgrade OS packages at build time (security fixes); an older
# image is rebuilt instead of reused.
DEFAULT_MAX_AGE_DAYS = 7
STATE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / (
    "leonaid/image-tags"
)


class Unsupported(Exception):
    """The image inputs cannot be determined completely; do not share."""


def instructions(text: str) -> list[tuple[str, list[str]]]:
    """Dockerfile instructions as (keyword, shell-split arguments)."""
    if re.search(r"<<-?\s*['\"]?[A-Za-z]", text):
        raise Unsupported("heredocs are not supported")
    result = []
    logical = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not logical and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            logical += line[:-1] + " "
            continue
        logical += line
        if logical.strip():
            keyword, _, rest = logical.strip().partition(" ")
            rest = rest.strip()
            if rest.startswith("["):
                arguments = json.loads(rest)
            else:
                arguments = shlex.split(rest, comments=False, posix=True)
            result.append((keyword.upper(), arguments))
        logical = ""
    return result


def sources(dockerfile: str) -> list[str]:
    """Context paths the Dockerfile copies; raise Unsupported when unsure."""
    stages: set[str] = set()
    count = 0
    paths: list[str] = []
    for keyword, arguments in instructions(dockerfile):
        if keyword == "FROM":
            options = [a for a in arguments if a.startswith("--")]
            for option in options:
                if option != "--platform=$BUILDPLATFORM":
                    raise Unsupported(f"FROM option {option}")
            image = [a for a in arguments if not a.startswith("--")]
            if not image:
                raise Unsupported("FROM without image")
            if "$" in image[0]:
                raise Unsupported("FROM with a variable")
            if image[0] not in stages and not DIGEST.search(image[0]):
                raise Unsupported(f"FROM {image[0]} is not pinned by digest")
            if len(image) == 3 and image[1].upper() == "AS":
                stages.add(image[2])
            count += 1
        elif keyword in {"COPY", "ADD"}:
            options = [a for a in arguments if a.startswith("--")]
            origin = next(
                (o.split("=", 1)[1] for o in options if o.startswith("--from=")), None
            )
            if origin is not None:
                # A previous stage, or an image whose digest is in the text.
                if not (
                    origin in stages
                    or (origin.isdigit() and int(origin) < count)
                    or DIGEST.search(origin)
                ):
                    raise Unsupported(f"{keyword} --from={origin} is not pinned")
                continue
            for option in options:
                if not re.fullmatch(r"--(chown|chmod)=[^\s]+|--link", option):
                    raise Unsupported(f"{keyword} option {option}")
            operands = [a for a in arguments if not a.startswith("--")]
            if len(operands) < 2:
                raise Unsupported(f"{keyword} without source")
            for source in operands[:-1]:
                if keyword == "ADD" and re.match(r"[a-z]+://|git@", source):
                    raise Unsupported("ADD from a URL")
                if "$" in source:
                    raise Unsupported("COPY source with a variable")
                paths.append(source)
        elif keyword == "RUN":
            for argument in arguments:
                if argument.startswith("--mount="):
                    kind = re.search(r"type=([a-z]+)", argument)
                    if not kind or kind.group(1) != "cache" or "from=" in argument:
                        raise Unsupported(f"RUN {argument}")
        elif keyword == "ONBUILD":
            raise Unsupported("ONBUILD")
    return paths


def _translate(pattern: str) -> str:
    """A .dockerignore pattern (Go filepath.Match plus **) as a regex."""
    expression = ""
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            expression += "(?:.*/)?"
            index += 3
        elif pattern.startswith("**", index):
            expression += ".*"
            index += 2
        elif pattern[index] == "*":
            expression += "[^/]*"
            index += 1
        elif pattern[index] == "?":
            expression += "[^/]"
            index += 1
        elif pattern[index] == "[":
            end = pattern.find("]", index + 2)
            if end < 0:
                raise Unsupported(".dockerignore character class")
            body = pattern[index + 1 : end]
            if body.startswith(("!", "^")):
                body = "^" + body[1:]
            expression += f"[{body}]"
            index = end + 1
        else:
            expression += re.escape(pattern[index])
            index += 1
    return expression + r"\Z"


def ignore_patterns(
    context: Path, dockerfile: Path
) -> list[tuple[bool, re.Pattern[str]]]:
    """.dockerignore as (exclude?, regex) in file order (Docker semantics)."""
    if Path(str(dockerfile) + ".dockerignore").exists():
        # BuildKit prefers it over the context's file.
        raise Unsupported("per-Dockerfile .dockerignore")
    path = context / ".dockerignore"
    if not path.exists():
        return []
    result = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        exclude = not line.startswith("!")
        pattern = os.path.normpath(line.lstrip("!").strip()).lstrip("/")
        if "\\" in pattern:
            raise Unsupported(".dockerignore escapes")
        result.append((exclude, re.compile(_translate(pattern))))
    return result


def ignored(relative: str, patterns: list[tuple[bool, re.Pattern[str]]]) -> bool:
    parts = relative.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    excluded = False
    for exclude, pattern in patterns:
        # A pattern matching a parent directory excludes everything below it.
        if any(pattern.match(prefix) for prefix in prefixes):
            excluded = exclude
    return excluded


def _inside(context: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(context)
    except ValueError:
        return False
    return True


def context_files(context: Path, source: str) -> list[tuple[str, Path]]:
    """(path relative to the context, file to read) for one COPY source."""
    pattern = os.path.normpath(source).lstrip("/")
    if pattern in {".", ""}:
        matches = [context]
    elif any(ch in pattern for ch in "*?["):
        matches = sorted(context / name for name in _glob(context, pattern.split("/")))
    else:
        matches = [context / pattern]
    files = []
    for match in matches:
        if not _inside(context, match):
            raise Unsupported(f"COPY source {source} leaves the context")
        relative = match.relative_to(context).as_posix()
        # A top-level symlink source is followed: hash what it points to.
        target = match.resolve() if match.is_symlink() else match
        if target.is_file():
            files.append((relative, target))
        elif target.is_dir():
            for folder, subfolders, names in os.walk(target):
                subfolders.sort()
                for name in sorted([*names, *subfolders]):
                    path = Path(folder) / name
                    if path.is_symlink() and not _inside(context, path):
                        raise Unsupported(f"symlink {path} leaves the context")
                    if path.is_symlink() or path.is_file():
                        inner = path.relative_to(target).as_posix()
                        joined = inner if relative == "." else f"{relative}/{inner}"
                        files.append((joined, path))
        else:
            raise Unsupported(f"COPY source {source} does not exist")
    return files


def _glob(base: Path, segments: list[str]) -> list[str]:
    """Docker COPY wildcards: filepath.Match per path segment."""
    results = [""]
    for segment in segments:
        expanded = []
        for prefix in results:
            folder = base / prefix if prefix else base
            if not folder.is_dir():
                continue
            for name in sorted(os.listdir(folder)):
                # Go's filepath.Match: wildcards also match leading dots.
                if fnmatch.fnmatchcase(name, segment):
                    expanded.append(f"{prefix}/{name}" if prefix else name)
        results = expanded
    return results


def docker_platform() -> str:
    """The platform builds target: DOCKER_DEFAULT_PLATFORM or the daemon's."""
    configured = os.environ.get("DOCKER_DEFAULT_PLATFORM")
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.OSType}}/{{.Architecture}}"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise Unsupported(f"Docker platform unknown: {error}") from None
    return result.stdout.strip()


def normalize(root: Path, build: dict[str, Any]) -> dict[str, Any]:
    """A Compose build section with the context relative to the repository."""
    unsupported = UNSUPPORTED_BUILD_KEYS & set(build)
    if unsupported:
        raise Unsupported(f"build {sorted(unsupported)}")
    spec = dict(build)
    context = (root / spec.get("context", ".")).resolve()
    try:
        spec["context"] = context.relative_to(root.resolve()).as_posix() or "."
    except ValueError:
        raise Unsupported("build context outside the repository") from None
    spec.setdefault("dockerfile", "Dockerfile")
    return spec


def spec_hash(root: Path, build: dict[str, Any], platform: str | None = None) -> str:
    spec = normalize(root, build)
    context = (root / spec["context"]).resolve()
    dockerfile = context / spec["dockerfile"]
    if not _inside(context, dockerfile):
        raise Unsupported("Dockerfile outside the context")
    text = dockerfile.read_text(encoding="utf-8")
    patterns = ignore_patterns(context, dockerfile)
    digest = hashlib.sha256()
    for part in (
        VERSION,
        platform or docker_platform(),
        json.dumps(spec, sort_keys=True),
        text,
        (context / ".dockerignore").read_text(encoding="utf-8")
        if (context / ".dockerignore").exists()
        else "",
    ):
        digest.update(part.encode() + b"\0")
    entries: dict[str, bytes] = {}
    for source in sources(text):
        for relative, path in context_files(context, source):
            if ignored(relative, patterns):
                continue
            if path.is_symlink():
                payload = b"link\0" + os.readlink(path).encode()
            else:
                mode = path.stat().st_mode & 0o777
                payload = (
                    f"{mode:o}\0".encode() + hashlib.sha256(path.read_bytes()).digest()
                )
            entries[relative] = payload
    for relative in sorted(entries):
        digest.update(relative.encode() + b"\0" + entries[relative] + b"\0")
    return digest.hexdigest()[:24]


def content_hash(root: Path, service: str) -> str:
    """Hash of SERVICE as built from the base compose.yml (CLI, CI)."""
    if service not in BUILDS:
        raise Unsupported(f"unknown service {service}")
    return spec_hash(root, BUILDS[service])


def build_hash(root: Path, context_name: str, dockerfile_name: str) -> str:
    return spec_hash(root, {"context": context_name, "dockerfile": dockerfile_name})


def effective_builds(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build sections of a rendered `docker compose config --format json`.

    A service with its own `image:` name is not tagged PROJECT-SERVICE by
    Compose, so it is never shared.
    """
    return {
        name: service["build"]
        for name, service in config.get("services", {}).items()
        if "build" in service and "image" not in service
    }


def docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, check=check
    )


def exists(reference: str) -> bool:
    return docker("image", "inspect", reference, check=False).returncode == 0


def fresh(reference: str) -> bool:
    """True if the image exists and was built within the maximum age."""
    result = docker(
        "image", "inspect", "--format", "{{.Created}}", reference, check=False
    )
    if result.returncode != 0:
        return False
    stamp = re.sub(r"(\.\d{6})\d*", r"\1", result.stdout.strip()).replace("Z", "+00:00")
    created = datetime.fromisoformat(stamp)
    days = float(os.environ.get("LEONAID_IMAGE_MAX_AGE_DAYS", DEFAULT_MAX_AGE_DAYS))
    return (datetime.now(timezone.utc) - created).total_seconds() < days * 86400


def touch(service: str, content: str) -> None:
    """Record the last use of a content tag; pruning keeps the most recent."""
    folder = STATE / service
    folder.mkdir(parents=True, exist_ok=True)
    (folder / content).touch()


def adopt(
    root: Path, project: str, builds: dict[str, dict[str, Any]], services: list[str]
) -> dict[str, str | None]:
    """Tag shared images for PROJECT; return {service: pre-build hash or None}
    for every service that still has to be built."""
    missing: dict[str, str | None] = {}
    for service in services:
        if service not in builds:
            print(f"image-tags: {service}: no shareable build", file=sys.stderr)
            missing[service] = None
            continue
        try:
            content = spec_hash(root, builds[service])
        except Unsupported as error:
            print(f"image-tags: {service}: not shared ({error})", file=sys.stderr)
            missing[service] = None
            continue
        shared = f"{REPOSITORY}/{service}:{content}"
        if (
            fresh(shared)
            and docker("tag", shared, f"{project}-{service}", check=False).returncode
            == 0
        ):
            touch(service, content)
            print(f"image-tags: {service}: reusing {shared}", file=sys.stderr)
        else:
            # Missing, too old, or pruned meanwhile by another checkout.
            missing[service] = content
    return missing


def record(
    root: Path,
    project: str,
    builds: dict[str, dict[str, Any]],
    before: dict[str, str | None],
) -> list[str]:
    """Tag freshly built images under the hash their inputs had before the
    build, only if the inputs still hash the same now."""
    recorded = []
    for service, content in before.items():
        if content is None or service not in builds:
            continue
        built = f"{project}-{service}"
        try:
            after: str | None = spec_hash(root, builds[service])
        except Unsupported:
            after = None
        if after != content:
            print(
                f"image-tags: {service}: inputs changed during the build; not shared",
                file=sys.stderr,
            )
            continue
        if not exists(built):
            print(
                f"image-tags: {service}: no {built} image; not shared", file=sys.stderr
            )
            continue
        docker("tag", built, f"{REPOSITORY}/{service}:{content}")
        touch(service, content)
        prune(service)
        recorded.append(service)
    return recorded


def prune(service: str, keep: int | None = None) -> list[str]:
    """Keep the `keep` most recently used content tags of SERVICE."""
    keep = keep or int(os.environ.get("LEONAID_IMAGE_KEEP", DEFAULT_KEEP))
    tags = docker(
        "image", "ls", f"{REPOSITORY}/{service}", "--format", "{{.Tag}}"
    ).stdout.split()

    def last_use(tag: str) -> float:
        marker = STATE / service / tag
        return marker.stat().st_mtime if marker.exists() else 0.0

    removed = []
    for tag in sorted(tags, key=last_use, reverse=True)[keep:]:
        # Only the tag goes; an image used by a container or project stays.
        reference = f"{REPOSITORY}/{service}:{tag}"
        if docker("image", "rm", reference, check=False).returncode == 0:
            (STATE / service / tag).unlink(missing_ok=True)
            removed.append(tag)
    return removed


def main() -> int:
    commands = {"adopt", "record"}
    if (
        len(sys.argv) == 2
        and sys.argv[1] not in commands
        and not sys.argv[1].startswith("-")
    ):
        try:
            print(content_hash(ROOT, sys.argv[1]))
        except (Unsupported, OSError) as error:
            print(f"image-tags: not shareable: {error}", file=sys.stderr)
            return 1
        return 0
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=sorted(commands))
    parser.add_argument("project")
    parser.add_argument("config", type=Path, help="docker compose config --format json")
    parser.add_argument("services", nargs="+")
    args = parser.parse_args()
    if not re.fullmatch(r"leonaid-[a-z0-9-]+", args.project):
        parser.error("project must be a leonaid-* test project")
    builds = effective_builds(json.loads(args.config.read_text()))
    if args.command == "adopt":
        for service, content in adopt(
            ROOT, args.project, builds, args.services
        ).items():
            print(f"{service} {content or '-'}")
    else:
        before: dict[str, str | None] = {}
        for item in args.services:
            service, _, content = item.partition("=")
            before[service] = None if content in {"", "-"} else content
        record(ROOT, args.project, builds, before)
    return 0


if __name__ == "__main__":
    sys.exit(main())
