#!/usr/bin/env python3
"""Content-hash tags for the images Compose builds, shared by all checkouts.

`python3 tools/testing/image_tags.py SERVICE` prints the 24-hex content hash
of SERVICE's image: sha256 over the platform, the Compose build definition,
the Dockerfile, the context's .dockerignore and every file the Dockerfile
copies from the context (after .dockerignore), with its mode. Identical inputs
produce identical tags in every worktree, so one build serves all of them
(`leonaid-local/<service>:<hash>`; CI may push the same hash to a registry).

It exits non-zero instead of printing a hash when the inputs cannot be
determined completely (a FROM without digest, ADD of a URL, a bind mount,
unsupported .dockerignore syntax): callers then build without sharing.

Stdlib only; CI runs it on the runner's Python before any bootstrap.

Shell helpers (`adopt`, `record`) used by the test harness:
  image_tags.py adopt PROJECT SERVICE...   tag shared images as PROJECT-SERVICE,
                                           print the services still to build
  image_tags.py record PROJECT SERVICE...  tag freshly built PROJECT-SERVICE
                                           images under their content hash
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
# Tests use their own repository so they never touch the shared tags.
REPOSITORY = os.environ.get("LEONAID_IMAGE_REPOSITORY", "leonaid-local")
VERSION = "image-tags-v1"
# Mirrors the `build:` sections of infra/compose/compose.yml (context relative
# to the repository, Dockerfile relative to the context). A test compares it
# with `docker compose config`.
BUILDS: dict[str, tuple[str, str]] = {
    "api": (".", "infra/compose/Dockerfile.core"),
    "worker": (".", "infra/compose/Dockerfile.core"),
    "web": (".", "infra/compose/Dockerfile.web"),
    "pwa": (".", "infra/compose/Dockerfile.pwa"),
    "public": (".", "infra/compose/Dockerfile.public"),
    "survey-validator": (".", "infra/compose/Dockerfile.survey-validator"),
    "campaign-site": (".", "infra/compose/Dockerfile.campaign-site"),
    "proxy": ("infra/proxy/image", "Dockerfile"),
}
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\Z")
DEFAULT_KEEP = 3


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
            if image[0] not in stages and not DIGEST.search(image[0]):
                raise Unsupported(f"FROM {image[0]} is not pinned by digest")
            if "$" in image[0]:
                raise Unsupported("FROM with a variable")
            if len(image) == 3 and image[1].upper() == "AS":
                stages.add(image[2])
        elif keyword in {"COPY", "ADD"}:
            options = [a for a in arguments if a.startswith("--")]
            if any(o.startswith("--from=") for o in options):
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
                    if not kind or kind.group(1) != "cache":
                        raise Unsupported(f"RUN {argument}")
        elif keyword == "ONBUILD":
            raise Unsupported("ONBUILD")
    return paths


def ignore_patterns(context: Path) -> list[tuple[bool, re.Pattern[str]]]:
    """.dockerignore as (exclude?, regex) in file order (Docker semantics)."""
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
                end = pattern.find("]", index)
                if end < 0:
                    raise Unsupported(".dockerignore character class")
                expression += pattern[index : end + 1]
                index = end + 1
            else:
                expression += re.escape(pattern[index])
                index += 1
        result.append((exclude, re.compile(expression + r"\Z")))
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


def context_files(context: Path, source: str) -> list[Path]:
    pattern = os.path.normpath(source).lstrip("/")
    if pattern in {".", ""}:
        matches = [context]
    elif any(ch in pattern for ch in "*?["):
        matches = sorted(context / name for name in _glob(context, pattern.split("/")))
    else:
        matches = [context / pattern]
    files = []
    for match in matches:
        if match.is_symlink() or match.is_file():
            files.append(match)
        elif match.is_dir():
            for folder, subfolders, names in os.walk(match):
                subfolders.sort()
                for name in sorted(names):
                    files.append(Path(folder) / name)
                for name in subfolders:
                    if (Path(folder) / name).is_symlink():
                        files.append(Path(folder) / name)
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


def content_hash(root: Path, service: str) -> str:
    if service not in BUILDS:
        raise Unsupported(f"unknown service {service}")
    return build_hash(root, *BUILDS[service])


def build_hash(root: Path, context_name: str, dockerfile_name: str) -> str:
    context = (root / context_name).resolve()
    dockerfile = context / dockerfile_name
    text = dockerfile.read_text(encoding="utf-8")
    patterns = ignore_patterns(context)
    digest = hashlib.sha256()
    for part in (
        VERSION,
        platform.machine(),
        json.dumps([context_name, dockerfile_name], sort_keys=True),
        text,
        (context / ".dockerignore").read_text(encoding="utf-8")
        if (context / ".dockerignore").exists()
        else "",
    ):
        digest.update(part.encode() + b"\0")
    entries: dict[str, bytes] = {}
    for source in sources(text):
        for path in context_files(context, source):
            relative = path.relative_to(context).as_posix()
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


def tag(root: Path, service: str) -> str:
    return f"{REPOSITORY}/{service}:{content_hash(root, service)}"


def docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, check=check
    )


def exists(reference: str) -> bool:
    return docker("image", "inspect", reference, check=False).returncode == 0


def adopt(root: Path, project: str, services: list[str]) -> list[str]:
    """Tag existing shared images for PROJECT; return the services to build."""
    missing = []
    for service in services:
        try:
            shared = tag(root, service)
        except Unsupported as error:
            print(f"image-tags: {service}: not shared ({error})", file=sys.stderr)
            missing.append(service)
            continue
        if exists(shared):
            docker("tag", shared, f"{project}-{service}")
            print(f"image-tags: {service}: reusing {shared}", file=sys.stderr)
        else:
            missing.append(service)
    return missing


def record(root: Path, project: str, services: list[str]) -> None:
    """Tag freshly built PROJECT-SERVICE images; prune old hashes."""
    for service in services:
        try:
            shared = tag(root, service)
        except Unsupported as error:
            print(f"image-tags: {service}: not shared ({error})", file=sys.stderr)
            continue
        built = f"{project}-{service}"
        if not exists(built):
            # The Compose files name this image differently (e.g. a pilot
            # overlay with image:); nothing to share.
            print(
                f"image-tags: {service}: no {built} image; not shared", file=sys.stderr
            )
            continue
        docker("tag", built, shared)
        prune(service)


def prune(service: str, keep: int | None = None) -> list[str]:
    """Keep the newest `keep` content tags of SERVICE; never force removal."""
    keep = keep or int(os.environ.get("LEONAID_IMAGE_KEEP", DEFAULT_KEEP))
    listing = docker(
        "image",
        "ls",
        f"{REPOSITORY}/{service}",
        "--format",
        "{{.CreatedAt}}\t{{.Repository}}:{{.Tag}}",
    ).stdout.splitlines()
    references = [line.split("\t")[1] for line in sorted(listing, reverse=True)]
    removed = []
    for reference in references[keep:]:
        # Only the tag goes; an image used by a container is kept.
        if docker("image", "rm", reference, check=False).returncode == 0:
            removed.append(reference)
    return removed


def main() -> int:
    if (
        len(sys.argv) == 2
        and not sys.argv[1].startswith("-")
        and sys.argv[1]
        not in {
            "adopt",
            "record",
        }
    ):
        try:
            print(content_hash(ROOT, sys.argv[1]))
        except Unsupported as error:
            print(f"image-tags: not shareable: {error}", file=sys.stderr)
            return 1
        return 0
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["adopt", "record"])
    parser.add_argument("project")
    parser.add_argument("services", nargs="+")
    args = parser.parse_args()
    if not re.fullmatch(r"leonaid-[a-z0-9-]+", args.project):
        parser.error("project must be a leonaid-* test project")
    if args.command == "adopt":
        print(" ".join(adopt(ROOT, args.project, args.services)))
    else:
        record(ROOT, args.project, args.services)
    return 0


if __name__ == "__main__":
    sys.exit(main())
