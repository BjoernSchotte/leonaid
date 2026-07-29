#!/usr/bin/env python3
"""Validate a complete LeonAid cross-system backup inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

REQUIRED_FILES = {
    "core.dump",
    "rustfs-data.tar",
    "twenty-storage.tar",
    "twenty.dump",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(RuntimeError):
    """A backup is incomplete, corrupt or belongs to another environment."""


def object_value(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label}_invalid")
    return value


def verify(directory: Path, *, source_project: str) -> dict[str, Any]:
    try:
        manifest = object_value(
            json.loads((directory / "manifest.json").read_text(encoding="utf-8")),
            "manifest",
        )
    except (json.JSONDecodeError, OSError) as error:
        raise ManifestError("manifest_unreadable") from error
    if manifest.get("schemaVersion") != 1:
        raise ManifestError("manifest_schema_unsupported")
    if manifest.get("sourceProject") != source_project:
        raise ManifestError("manifest_source_mismatch")
    created_at = manifest.get("createdAt")
    if not isinstance(created_at, str) or not created_at:
        raise ManifestError("manifest_timestamp_missing")

    files = object_value(manifest.get("files"), "manifest_files")
    if set(files) != REQUIRED_FILES:
        raise ManifestError("manifest_inventory_incomplete")
    for name in sorted(REQUIRED_FILES):
        metadata = object_value(files[name], f"manifest_file_{name}")
        expected_size = metadata.get("size")
        expected_hash = metadata.get("sha256")
        if (
            not isinstance(expected_size, int)
            or expected_size < 0
            or not isinstance(expected_hash, str)
            or SHA256.fullmatch(expected_hash) is None
        ):
            raise ManifestError(f"manifest_metadata_invalid:{name}")
        try:
            data = (directory / name).read_bytes()
        except OSError as error:
            raise ManifestError(f"backup_file_unreadable:{name}") from error
        if len(data) != expected_size:
            raise ManifestError(f"backup_size_mismatch:{name}")
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise ManifestError(f"backup_hash_mismatch:{name}")
    return manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("directory", type=Path)
    result.add_argument("--source-project", required=True)
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        verify(arguments.directory, source_project=arguments.source_project)
    except ManifestError as error:
        print(f"backup-manifest: BLOCKED: {error}", file=sys.stderr)
        return 1
    print("backup-manifest: OK: vier Cross-System-Bestandteile bytegenau")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
