#!/usr/bin/env python3
"""Turn pushed release images into the pinned production image references.

images:     bake metadata (docker buildx bake --metadata-file) -> images.env
render-env: production.env.example + images.env -> env file that resolves the
            pilot Compose topology, so the release manifest is created from
            exactly the configuration that pilot-deploy later verifies.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CALVER = re.compile(r"^[0-9]{4}\.(1[0-2]|[1-9])\.[1-9][0-9]*(\.[1-9][0-9]*)?$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
REGISTRY = re.compile(r"^[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9._-]+)+$")
IMAGE_VARIABLES = {
    "core": "LEONAID_CORE_IMAGE",
    "web": "LEONAID_WEB_IMAGE",
    "pwa": "LEONAID_PWA_IMAGE",
    "public": "LEONAID_PUBLIC_IMAGE",
    "proxy": "LEONAID_PROXY_IMAGE",
    "survey-validator": "LEONAID_SURVEY_VALIDATOR_IMAGE",
}


class ReleaseAssetError(ValueError):
    """Raised when release inputs are incomplete or malformed."""


def image_environment(
    metadata: dict[str, object], *, registry: str, version: str, commit: str
) -> dict[str, str]:
    if not REGISTRY.fullmatch(registry):
        raise ReleaseAssetError(f"invalid registry {registry!r}")
    if not CALVER.fullmatch(version):
        raise ReleaseAssetError(f"version {version!r} is not CalVer YYYY.M.N[.P]")
    if not COMMIT.fullmatch(commit):
        raise ReleaseAssetError("commit must be a full 40-character SHA")
    missing = sorted(set(IMAGE_VARIABLES) - set(metadata))
    if missing:
        raise ReleaseAssetError(f"bake metadata lacks targets: {', '.join(missing)}")
    environment = {
        "LEONAID_SERVICE_VERSION": version,
        "LEONAID_RELEASE_COMMIT": commit,
    }
    for target, variable in IMAGE_VARIABLES.items():
        entry = metadata[target]
        digest = entry.get("containerimage.digest") if isinstance(entry, dict) else None
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ReleaseAssetError(f"{target}: missing or invalid image digest")
        environment[variable] = f"{registry}/{target}:{version}@{digest}"
    return environment


def render_environment(template: str, values: dict[str, str]) -> str:
    """Replace the given keys in a dotenv template; every key must exist once."""

    lines = template.splitlines()
    seen: set[str] = set()
    for index, line in enumerate(lines):
        key, separator, _ = line.partition("=")
        if separator and key in values:
            if key in seen:
                raise ReleaseAssetError(f"{key} appears twice in the template")
            lines[index] = f"{key}={values[key]}"
            seen.add(key)
    missing = sorted(set(values) - seen)
    if missing:
        raise ReleaseAssetError(f"template lacks keys: {', '.join(missing)}")
    return "\n".join(lines) + "\n"


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and not key.startswith("#"):
            values[key.strip()] = value
    return values


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(description=__doc__)
    commands = command_parser.add_subparsers(dest="command", required=True)
    images = commands.add_parser("images")
    images.add_argument("--metadata", type=Path, required=True)
    images.add_argument("--registry", required=True)
    images.add_argument("--version", required=True)
    images.add_argument("--commit", required=True)
    images.add_argument("--output", type=Path, required=True)
    render = commands.add_parser("render-env")
    render.add_argument("--template", type=Path, required=True)
    render.add_argument("--images", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    return command_parser


def main() -> int:
    arguments = parser().parse_args()
    try:
        if arguments.command == "images":
            metadata = json.loads(arguments.metadata.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                raise ReleaseAssetError("bake metadata must be a JSON object")
            environment = image_environment(
                metadata,
                registry=arguments.registry,
                version=arguments.version,
                commit=arguments.commit,
            )
            arguments.output.write_text(
                "".join(f"{key}={value}\n" for key, value in environment.items()),
                encoding="utf-8",
            )
        else:
            arguments.output.write_text(
                render_environment(
                    arguments.template.read_text(encoding="utf-8"),
                    read_dotenv(arguments.images),
                ),
                encoding="utf-8",
            )
    except (OSError, json.JSONDecodeError, ReleaseAssetError) as error:
        print(f"release-assets: ERROR: {error}", file=sys.stderr)
        return 1
    print(f"release-assets: OK: wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
