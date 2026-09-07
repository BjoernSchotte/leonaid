#!/usr/bin/env python3
"""Validate a complete LeonAid cross-system backup inventory."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

from tools.backup.cms_state import CmsStateError, verify_bootstrap_archive

REQUIRED_FILES = {
    "core.dump",
    "rustfs-data.tar",
    "twenty-storage.tar",
    "twenty.dump",
}
CMS_REQUIRED_FILES = REQUIRED_FILES | {"emdash.dump", "cms-bootstrap-state.tar"}
TOPOLOGY_VERSIONS = {"legacy": 1, "emdash": 2}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CMS_KEY = re.compile(r"^emdash_enc_v1_[A-Za-z0-9_-]{43}$")


class ManifestError(RuntimeError):
    """A backup is incomplete, corrupt or belongs to another environment."""


def key_fingerprint(key: str | None) -> str:
    if key is None or CMS_KEY.fullmatch(key) is None:
        raise ManifestError("cms_encryption_key_missing_or_invalid")
    return hashlib.sha256(key.encode("ascii")).hexdigest()


def object_value(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label}_invalid")
    return value


def unique_manifest_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError("manifest_duplicate_key")
        result[key] = value
    return result


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ManifestError("manifest_not_regular")
            data = stream.read(65537)
        if len(data) > 65536:
            raise ManifestError("manifest_too_large")
        return object_value(
            json.loads(data, object_pairs_hook=unique_manifest_object), "manifest"
        )
    except (ValueError, OSError, RecursionError) as error:
        raise ManifestError("manifest_unreadable") from error


def file_digest(path: Path) -> tuple[int, str]:
    """Hash archives in bounded memory and refuse symlinks/non-regular files."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ManifestError("backup_file_not_regular")
            digest = hashlib.sha256()
            size = 0
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ManifestError("backup_file_changed")
            return size, digest.hexdigest()
    except OSError as error:
        raise ManifestError("backup_file_unreadable") from error


def verify(
    directory: Path,
    *,
    source_project: str,
    topology: str = "legacy",
    encryption_key: str | None = None,
    require_key: bool = False,
) -> dict[str, Any]:
    manifest = read_manifest(directory / "manifest.json")
    version = manifest.get("schemaVersion")
    if type(version) is not int or version not in TOPOLOGY_VERSIONS.values():
        raise ManifestError("manifest_schema_unsupported")
    if topology not in TOPOLOGY_VERSIONS or version != TOPOLOGY_VERSIONS[topology]:
        raise ManifestError("manifest_topology_mismatch")
    if version == 2:
        fingerprint = manifest.get("cmsEncryptionKeySha256")
        if not isinstance(fingerprint, str) or SHA256.fullmatch(fingerprint) is None:
            raise ManifestError("cms_encryption_key_fingerprint_missing")
        if require_key and key_fingerprint(encryption_key) != fingerprint:
            raise ManifestError("cms_encryption_key_mismatch")
    if manifest.get("sourceProject") != source_project:
        raise ManifestError("manifest_source_mismatch")
    created_at = manifest.get("createdAt")
    if not isinstance(created_at, str) or not created_at:
        raise ManifestError("manifest_timestamp_missing")

    files = object_value(manifest.get("files"), "manifest_files")
    required = CMS_REQUIRED_FILES if version == 2 else REQUIRED_FILES
    if set(files) != required:
        raise ManifestError("manifest_inventory_incomplete")
    for name in sorted(required):
        metadata = object_value(files[name], f"manifest_file_{name}")
        expected_size = metadata.get("size")
        expected_hash = metadata.get("sha256")
        if (
            type(expected_size) is not int
            or expected_size < 0
            or not isinstance(expected_hash, str)
            or SHA256.fullmatch(expected_hash) is None
        ):
            raise ManifestError(f"manifest_metadata_invalid:{name}")
        size, digest = file_digest(directory / name)
        if size != expected_size:
            raise ManifestError(f"backup_size_mismatch:{name}")
        if digest != expected_hash:
            raise ManifestError(f"backup_hash_mismatch:{name}")
    if version == 2:
        try:
            verify_bootstrap_archive(directory / "cms-bootstrap-state.tar")
        except CmsStateError as error:
            raise ManifestError("cms_bootstrap_recovery_refused") from error
    return manifest


def create(
    directory: Path,
    *,
    source_project: str,
    topology: str,
    encryption_key: str | None = None,
    require_key: bool = False,
) -> dict[str, Any]:
    if topology not in TOPOLOGY_VERSIONS:
        raise ManifestError("manifest_topology_mismatch")
    required = CMS_REQUIRED_FILES if topology == "emdash" else REQUIRED_FILES
    fingerprint = key_fingerprint(encryption_key) if topology == "emdash" else None
    if topology == "emdash":
        try:
            verify_bootstrap_archive(directory / "cms-bootstrap-state.tar")
        except CmsStateError as error:
            raise ManifestError("cms_bootstrap_recovery_refused") from error
    files = {}
    for name in sorted(required):
        size, digest = file_digest(directory / name)
        files[name] = {"size": size, "sha256": digest}
    manifest = {
        "schemaVersion": TOPOLOGY_VERSIONS[topology],
        "sourceProject": source_project,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    if fingerprint is not None:
        manifest["cmsEncryptionKeySha256"] = fingerprint
    # Backup staging is private and freshly allocated. Never overwrite an
    # existing manifest or follow a symlink at the output path.
    try:
        descriptor = os.open(
            directory / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    except OSError as error:
        raise ManifestError("manifest_create_failed") from error
    return verify(directory, source_project=source_project, topology=topology)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("directory", type=Path)
    result.add_argument("--source-project", required=True)
    result.add_argument("--create", action="store_true")
    result.add_argument("--require-cms-key", action="store_true")
    result.add_argument(
        "--topology", choices=sorted(TOPOLOGY_VERSIONS), default="legacy"
    )
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        operation = create if arguments.create else verify
        manifest = operation(
            arguments.directory,
            source_project=arguments.source_project,
            topology=arguments.topology,
            encryption_key=os.environ.get("CMS_ENCRYPTION_KEY"),
            require_key=arguments.require_cms_key,
        )
    except ManifestError as error:
        print(f"backup-manifest: BLOCKED: {error}", file=sys.stderr)
        return 1
    print(
        f"backup-manifest: OK: version {manifest['schemaVersion']}, exact inventory verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
