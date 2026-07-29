#!/usr/bin/env python3
"""Real-file negative tests for the complete backup manifest contract."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Callable

from tools.backup.manifest import ManifestError, REQUIRED_FILES, verify


def rejected(label: str, operation: Callable[[], object]) -> None:
    try:
        operation()
    except ManifestError:
        return
    raise AssertionError(f"unsichere Backup-Mutation akzeptiert: {label}")


def write_backup(directory: Path, project: str) -> dict[str, object]:
    files: dict[str, dict[str, object]] = {}
    for index, name in enumerate(sorted(REQUIRED_FILES), start=1):
        data = f"synthetic-backup-part-{index}\n".encode()
        (directory / name).write_bytes(data)
        files[name] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sourceProject": project,
        "files": files,
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    project = "leonaid-production-test"
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        manifest = write_backup(directory, project)
        verify(directory, source_project=project)

        incomplete = copy.deepcopy(manifest)
        files = incomplete["files"]
        assert isinstance(files, dict)
        files.pop("rustfs-data.tar")
        (directory / "manifest.json").write_text(
            json.dumps(incomplete), encoding="utf-8"
        )
        rejected(
            "fehlendes RustFS-Archiv",
            lambda: verify(directory, source_project=project),
        )

        write_backup(directory, project)
        (directory / "core.dump").write_bytes(b"corrupt")
        rejected("korrupter Dump", lambda: verify(directory, source_project=project))

        write_backup(directory, project)
        rejected(
            "falsches Quellprojekt",
            lambda: verify(directory, source_project="leonaid-production-other"),
        )

    print(
        "backup-manifest-test: OK: vollständiges Inventar sowie drei "
        "reale Negativmutationen bewiesen"
    )


if __name__ == "__main__":
    main()
