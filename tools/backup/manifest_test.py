#!/usr/bin/env python3
"""Real-file negative tests for the complete backup manifest contract."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tarfile
from typing import Callable

from tools.backup.manifest import (
    ManifestError,
    REQUIRED_FILES,
    CMS_REQUIRED_FILES,
    create,
    verify,
    key_fingerprint,
)

SYNTHETIC_KEY = "emdash_enc_v1_" + "A" * 43


def rejected(label: str, operation: Callable[[], object]) -> None:
    try:
        operation()
    except ManifestError:
        return
    raise AssertionError(f"unsichere Backup-Mutation akzeptiert: {label}")


def write_backup(
    directory: Path, project: str, *, version: int = 1
) -> dict[str, object]:
    files: dict[str, dict[str, object]] = {}
    required = CMS_REQUIRED_FILES if version == 2 else REQUIRED_FILES
    for index, name in enumerate(sorted(required), start=1):
        data = f"synthetic-backup-part-{index}\n".encode()
        if name == "cms-bootstrap-state.tar":
            with tarfile.open(directory / name, "w") as archive:
                state = json.dumps(
                    {
                        "version": 1,
                        "status": "complete",
                        "actor": "10000000-0000-4000-8000-000000000001",
                        "expiresAt": 1,
                    }
                ).encode()
                member = tarfile.TarInfo("./state.json")
                member.mode = 0o600
                member.size = len(state)
                archive.addfile(member, io.BytesIO(state))
            data = (directory / name).read_bytes()
        else:
            (directory / name).write_bytes(data)
        files[name] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
    manifest: dict[str, object] = {
        "schemaVersion": version,
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sourceProject": project,
        "files": files,
    }
    if version == 2:
        manifest["cmsEncryptionKeySha256"] = key_fingerprint(SYNTHETIC_KEY)
    (directory / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    project = "leonaid-production-test"
    # EmDash requires canonical base64url, not merely 43 allowed characters.
    for last in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_":
        candidate = "emdash_enc_v1_" + "A" * 42 + last
        if last in "AEIMQUYcgkosw048":
            assert len(key_fingerprint(candidate)) == 64
        else:
            rejected(
                "non-canonical key padding bits", lambda: key_fingerprint(candidate)
            )
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        for fault in ("symlink", "oversize", "duplicate", "invalid-encoding"):
            write_backup(directory, project, version=2)
            path = directory / "manifest.json"
            if fault == "symlink":
                path.rename(directory / "outside.json")
                path.symlink_to(directory / "outside.json")
            elif fault == "oversize":
                path.write_bytes(b" " * 65537)
            elif fault == "invalid-encoding":
                path.write_bytes(b"\xff")
            else:
                path.write_text(
                    path.read_text().replace(
                        '"schemaVersion": 2', '"schemaVersion": 1, "schemaVersion": 2'
                    )
                )
            rejected(
                f"unsafe manifest {fault}",
                lambda: verify(directory, source_project=project, topology="emdash"),
            )
            path.unlink()

    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        manifest = write_backup(directory, project, version=2)
        manifest.pop("cmsEncryptionKeySha256")
        (directory / "manifest.json").write_text(json.dumps(manifest))
        rejected(
            "missing key fingerprint",
            lambda: verify(directory, source_project=project, topology="emdash"),
        )
        (directory / "manifest.json").unlink()
        rejected(
            "creation without key",
            lambda: create(directory, source_project=project, topology="emdash"),
        )
        assert not (directory / "manifest.json").exists()
        command = [
            sys.executable,
            "-m",
            "tools.backup.manifest",
            str(directory),
            "--source-project",
            project,
            "--topology",
            "emdash",
        ]
        environment = {**os.environ, "CMS_ENCRYPTION_KEY": SYNTHETIC_KEY}
        created = subprocess.run(
            command + ["--create"],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert created.returncode == 0
        assert SYNTHETIC_KEY not in (directory / "manifest.json").read_text()
        for cli_key, expected in (
            (SYNTHETIC_KEY, 0),
            ("", 1),
            ("emdash_enc_v1_" + "B" * 42 + "A", 1),
        ):
            checked = subprocess.run(
                command + ["--require-cms-key"],
                env={**environment, "CMS_ENCRYPTION_KEY": cli_key},
                capture_output=True,
                text=True,
                check=False,
            )
            assert checked.returncode == expected
            assert SYNTHETIC_KEY not in checked.stdout + checked.stderr
            assert cli_key == "" or cli_key not in checked.stdout + checked.stderr
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
        rejected(
            "legacy without CMS in new topology",
            lambda: verify(directory, source_project=project, topology="emdash"),
        )
        manifest = write_backup(directory, project, version=2)
        verify(directory, source_project=project, topology="emdash")
        verify(
            directory,
            source_project=project,
            topology="emdash",
            encryption_key=SYNTHETIC_KEY,
            require_key=True,
        )
        for key in (None, "", "invalid", "emdash_enc_v1_" + "B" * 43):
            rejected(
                "missing or different restore key",
                lambda: verify(
                    directory,
                    source_project=project,
                    topology="emdash",
                    encryption_key=key,
                    require_key=True,
                ),
            )
        rejected(
            "CMS backup on legacy restore",
            lambda: verify(directory, source_project=project),
        )
        for missing in sorted(CMS_REQUIRED_FILES):
            incomplete = copy.deepcopy(manifest)
            assert isinstance(incomplete["files"], dict)
            incomplete["files"].pop(missing)
            (directory / "manifest.json").write_text(
                json.dumps(incomplete), encoding="utf-8"
            )
            rejected(
                "missing v2 part",
                lambda: verify(directory, source_project=project, topology="emdash"),
            )
        for version in (0, 3, True, "2"):
            invalid = {**manifest, "schemaVersion": version}
            (directory / "manifest.json").write_text(
                json.dumps(invalid), encoding="utf-8"
            )
            rejected(
                "unknown or malformed version",
                lambda: verify(directory, source_project=project, topology="emdash"),
            )
        write_backup(directory, project, version=2)
        (directory / "emdash.dump").unlink()
        rejected(
            "missing CMS bytes",
            lambda: verify(directory, source_project=project, topology="emdash"),
        )
        write_backup(directory, project, version=2)
        (directory / "emdash.dump").rename(directory / "outside.dump")
        (directory / "emdash.dump").symlink_to(directory / "outside.dump")
        rejected(
            "symlink CMS dump",
            lambda: verify(directory, source_project=project, topology="emdash"),
        )
        (directory / "emdash.dump").unlink()
        write_backup(directory, project, version=2)
        (directory / "cms-bootstrap-state.tar").write_bytes(b"corrupt")
        rejected(
            "corrupt bootstrap state",
            lambda: verify(directory, source_project=project, topology="emdash"),
        )

    for topology, version in (("legacy", 1), ("emdash", 2)):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_backup(directory, project, version=version)
            (directory / "manifest.json").unlink()
            written = create(
                directory,
                source_project=project,
                topology=topology,
                encryption_key=SYNTHETIC_KEY,
            )
            assert written["schemaVersion"] == version
            assert written == verify(
                directory, source_project=project, topology=topology
            )
            rejected(
                "overwrite existing manifest",
                lambda: create(
                    directory,
                    source_project=project,
                    topology=topology,
                    encryption_key=SYNTHETIC_KEY,
                ),
            )
            (directory / "manifest.json").unlink()
            (directory / "core.dump").unlink()
            rejected(
                "create from incomplete source",
                lambda: create(
                    directory,
                    source_project=project,
                    topology=topology,
                    encryption_key=SYNTHETIC_KEY,
                ),
            )
            assert not (directory / "manifest.json").exists()

    for fault in (
        "armed",
        "consumed",
        "missing",
        "link",
        "traversal",
        "extra",
        "duplicate",
        "permissions",
        "duplicate-json",
    ):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest = write_backup(directory, project, version=2)
            archive_path = directory / "cms-bootstrap-state.tar"
            payload = json.dumps(
                {
                    "version": 1,
                    "status": fault if fault in {"armed", "consumed"} else "complete",
                    "actor": "10000000-0000-4000-8000-000000000001",
                    "expiresAt": 1,
                }
            ).encode()
            if fault == "duplicate-json":
                payload = payload.replace(b'"status":', b'"status":"armed","status":')
            with tarfile.open(archive_path, "w") as archive:
                if fault != "missing":
                    member = tarfile.TarInfo(
                        "../state.json" if fault == "traversal" else "./state.json"
                    )
                    member.mode = 0o644 if fault == "permissions" else 0o600
                    member.size = len(payload)
                    if fault == "link":
                        member.type = tarfile.SYMTYPE
                        member.linkname = "/outside/state.json"
                        member.size = 0
                    archive.addfile(member, io.BytesIO(payload))
                    if fault in {"extra", "duplicate"}:
                        member.name = "state.next" if fault == "extra" else "state.json"
                        archive.addfile(member, io.BytesIO(payload))
            data = archive_path.read_bytes()
            assert isinstance(manifest["files"], dict)
            manifest["files"]["cms-bootstrap-state.tar"] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
            (directory / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            rejected(
                f"valid hash but unsafe bootstrap {fault}",
                lambda: verify(directory, source_project=project, topology="emdash"),
            )
            (directory / "manifest.json").unlink()
            rejected(
                f"unsafe bootstrap creation {fault}",
                lambda: create(
                    directory,
                    source_project=project,
                    topology="emdash",
                    encryption_key=SYNTHETIC_KEY,
                ),
            )
            assert not (directory / "manifest.json").exists()

    for fault in (None, "link", "file", "permissions", "child", "duplicate"):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_backup(directory, project, version=2)
            archive_path = directory / "cms-bootstrap-state.tar"
            with tarfile.open(archive_path, "a") as archive:
                member = tarfile.TarInfo("./cms-maintenance")
                member.type = tarfile.DIRTYPE
                member.mode = 0o700
                if fault == "link":
                    member.type = tarfile.SYMTYPE
                    member.linkname = "/outside"
                elif fault == "file":
                    member.type = tarfile.REGTYPE
                elif fault == "permissions":
                    member.mode = 0o777
                archive.addfile(member)
                if fault in {"child", "duplicate"}:
                    member.name = (
                        "./cms-maintenance/extra"
                        if fault == "child"
                        else "cms-maintenance/"
                    )
                    archive.addfile(member)
            (directory / "manifest.json").unlink()
            if fault is None:
                create(
                    directory,
                    source_project=project,
                    topology="emdash",
                    encryption_key=SYNTHETIC_KEY,
                )
                verify(directory, source_project=project, topology="emdash")
                restored = directory / "restored"
                restored.mkdir()
                # The restore operator uses tar, whose directory mode handling
                # differs from Python's data extraction filter.
                subprocess.run(
                    ["tar", "-C", str(restored), "-xf", str(archive_path)],
                    check=True,
                )
                assert (restored / "cms-maintenance").is_dir()
                assert not list((restored / "cms-maintenance").iterdir())
                assert (restored / "cms-maintenance").stat().st_mode & 0o777 == 0o700
            else:
                rejected(
                    f"unsafe maintenance marker {fault}",
                    lambda: create(
                        directory,
                        source_project=project,
                        topology="emdash",
                        encryption_key=SYNTHETIC_KEY,
                    ),
                )

    print(
        "backup-manifest-test: OK: explicit legacy/CMS topology, exact v1/v2 inventories, missing/corrupt parts, unsupported versions and symlink denial proved with real files"
    )


if __name__ == "__main__":
    main()
