#!/usr/bin/env python3
"""Prove pilot evidence permissions, manifests and real Git boundaries."""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from tools.pilot.evidence import build_manifest, initialize, write_private_json

EXPECTED_MANIFEST_KEYS = {
    "sha256",
    "counts",
    "error_classes",
    "timestamps",
    "actor_id",
    "external_evidence_id",
}


def run(
    *arguments: str, cwd: Path, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(arguments),
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def prove_permissions_and_manifest(workspace: Path) -> None:
    pilot_root = initialize(workspace)
    for directory in (pilot_root, *pilot_root.iterdir()):
        if not directory.is_dir() or mode(directory) != 0o700:
            raise AssertionError(
                f"privates Verzeichnis ist nicht Modus 0700: {directory}"
            )

    source = pilot_root / "intake" / "club-export.xlsx"
    source.write_bytes(b"synthetic private workbook bytes")
    source.chmod(0o600)
    manifest_path = pilot_root / "manifests" / "EVID-IMPORT-001.json"
    manifest = build_manifest(
        source,
        actor_id="ACTOR-ADMIN-01",
        external_evidence_id="EVID-IMPORT-001",
        error_classes=["ROW_CONFLICT"],
        recorded_at="2026-07-28T10:00:00+02:00",
    )
    write_private_json(manifest_path, manifest)
    parsed: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    if set(parsed) != EXPECTED_MANIFEST_KEYS:
        raise AssertionError("Evidence-Manifest enthält nicht freigegebene Metadaten")
    serialized = manifest_path.read_text(encoding="utf-8")
    forbidden = ("club-export", "synthetic private workbook bytes", "@", "street")
    if any(value in serialized for value in forbidden):
        raise AssertionError("Evidence-Manifest enthält private Quelldaten")
    if mode(source) != 0o600 or mode(manifest_path) != 0o600:
        raise AssertionError("private Dateien sind nicht Modus 0600")


def initialize_git_repository(repository: Path, root: Path) -> None:
    repository.mkdir()
    shutil.copy2(root / ".gitignore", repository / ".gitignore")
    tools = repository / "tools" / "pilot"
    tools.mkdir(parents=True)
    shutil.copy2(root / "tools/pilot/boundary.py", tools / "boundary.py")
    run("git", "init", "--initial-branch=main", cwd=repository)
    run("git", "config", "user.name", "LeonAid Boundary Proof", cwd=repository)
    run(
        "git",
        "config",
        "user.email",
        "boundary-proof@leonaid.invalid",
        cwd=repository,
    )
    run("git", "add", ".gitignore", "tools/pilot/boundary.py", cwd=repository)
    run("git", "commit", "-m", "baseline", cwd=repository)


def expect_boundary_failure(repository: Path, marker: str) -> None:
    result = run(
        sys.executable,
        "tools/pilot/boundary.py",
        str(repository),
        cwd=repository,
        check=False,
    )
    if result.returncode == 0 or marker not in result.stderr:
        raise AssertionError(
            f"Git-Grenze hat privaten Pfad nicht abgewiesen: {result.stderr}"
        )


def prove_real_git_index_and_history(root: Path, workspace: Path) -> None:
    indexed_repo = workspace / "indexed-repo"
    initialize_git_repository(indexed_repo, root)
    private = indexed_repo / ".local" / "pilot" / "intake" / "members.xlsx"
    private.parent.mkdir(parents=True)
    private.write_bytes(b"private")
    run(
        "git",
        "add",
        "--force",
        str(private.relative_to(indexed_repo)),
        cwd=indexed_repo,
    )
    expect_boundary_failure(indexed_repo, "Git-Index")

    history_repo = workspace / "history-repo"
    initialize_git_repository(history_repo, root)
    historical = history_repo / ".local" / "pilot" / "evidence" / "invoice.pdf"
    historical.parent.mkdir(parents=True)
    historical.write_bytes(b"private")
    run(
        "git",
        "add",
        "--force",
        str(historical.relative_to(history_repo)),
        cwd=history_repo,
    )
    run("git", "commit", "-m", "intentional private canary", cwd=history_repo)
    historical.unlink()
    run("git", "add", "--update", cwd=history_repo)
    run("git", "commit", "-m", "remove canary", cwd=history_repo)
    expect_boundary_failure(history_repo, "Git-Historie")


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        prove_permissions_and_manifest(workspace)
        prove_real_git_index_and_history(root, workspace)
    result = run(
        sys.executable,
        "tools/pilot/boundary.py",
        str(root),
        cwd=root,
    )
    if "pilot-data-boundary: OK" not in result.stdout:
        raise AssertionError("Repository-Grenznachweis fehlt")
    print(
        "pilot-data-boundary-test: OK: 0700/0600, minimales Manifest, "
        "echter Git-Index und Git-Historie bewiesen"
    )


if __name__ == "__main__":
    main()
