#!/usr/bin/env python3
"""Prepare and verify the real PILOT-030/031 import protocol fixture."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import shutil
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from tools.twenty.import_contacts import ImportFailure, load_mapping, load_rows

JsonObject = dict[str, Any]
SOURCE_RELATIVE = Path(
    "tests/fixtures/golden/v1/outputs/"
    "019f9a37-b6da-7521-b590-ec1e8215a6bf/leonaid-crm-import.xlsx"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def private_json(path: Path, value: JsonObject) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def load_json(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"JSON-Objekt erwartet: {path}")
    return value


def prepare(root: Path, workspace: Path) -> None:
    private_root = workspace / ".local" / "pilot"
    for name in ("intake", "manifests", "evidence", "backups"):
        private_directory(private_root / name)
    mapping_target = workspace / "infra" / "twenty" / "import-mapping.json"
    mapping_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "infra/twenty/import-mapping.json", mapping_target)

    source = private_root / "intake" / "historic-contacts.xlsx"
    shutil.copy2(root / SOURCE_RELATIVE, source)
    source.chmod(0o600)
    private_json(
        private_root / "manifests" / "intake.json",
        {
            "schemaVersion": 1,
            "sourceSha256": sha256_file(source),
            "authorizationReference": "AUTH-PILOT-001",
            "purpose": "historic-sponsor-contact-import",
            "receivedAt": "2026-07-29T20:00:00Z",
            "responsibleActorId": "ACTOR-DATA-01",
            "externalEvidenceId": "EVID-IMPORT-001",
        },
    )

    damaged = private_root / "intake" / "damaged"
    private_directory(damaged)
    for name in ("formula", "missing-header", "duplicate-id", "invalid-email"):
        target = damaged / f"{name}.xlsx"
        shutil.copy2(source, target)
        workbook = load_workbook(target)
        sheet = workbook["Kontakte"]
        if name == "formula":
            sheet["G2"] = "=1+1"
        elif name == "missing-header":
            sheet["A1"] = None
        elif name == "duplicate-id":
            sheet["A3"] = sheet["A2"].value
        else:
            sheet["F4"] = "keine-adresse"
        workbook.save(target)
        workbook.close()
        target.chmod(0o600)


def check_damaged(workspace: Path) -> None:
    mapping = load_mapping(workspace / "infra/twenty/import-mapping.json")
    damaged = workspace / ".local" / "pilot" / "intake" / "damaged"
    for name, marker in (
        ("formula", "Formeln"),
        ("missing-header", "Header"),
    ):
        try:
            load_rows(damaged / f"{name}.xlsx", "Kontakte", mapping)
        except ImportFailure as error:
            if marker not in str(error):
                raise AssertionError(
                    f"{name} lieferte keine stabile Fehlerklasse: {error}"
                ) from error
        else:
            raise AssertionError(f"{name} wurde nicht abgewiesen")

    duplicate = load_rows(damaged / "duplicate-id.xlsx", "Kontakte", mapping)
    if (
        sum(
            "source_id ist innerhalb der Datei doppelt" in row.validation_errors
            for row in duplicate
        )
        != 2
    ):
        raise AssertionError("doppelte IDs wurden nicht zeilenbezogen erkannt")
    invalid_email = load_rows(damaged / "invalid-email.xlsx", "Kontakte", mapping)
    if "email ist ungültig" not in invalid_email[2].validation_errors:
        raise AssertionError("ungültige E-Mail wurde nicht erkannt")
    source = workspace / ".local" / "pilot" / "intake" / "historic-contacts.xlsx"
    if len(load_rows(source, "Kontakte", mapping)) != 4:
        raise AssertionError("erstes Blatt besitzt nicht vier Strukturzeilen")
    if len(load_rows(source, "Kontakte Update", mapping)) != 4:
        raise AssertionError("zweites Blatt besitzt nicht vier Strukturzeilen")


def write_backup_manifest(workspace: Path, source_project: str) -> None:
    backup = workspace / ".local" / "pilot" / "backups"
    files: JsonObject = {}
    for name in (
        "core.dump",
        "twenty.dump",
        "twenty-storage.tar",
        "rustfs-data.tar",
    ):
        path = backup / name
        if not path.is_file() or path.stat().st_size == 0:
            raise AssertionError(f"reales Backup-Artefakt fehlt: {name}")
        files[name] = {"size": path.stat().st_size, "sha256": sha256_file(path)}
        path.chmod(0o600)
    private_json(
        backup / "manifest.json",
        {
            "schemaVersion": 1,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "sourceProject": source_project,
            "files": files,
        },
    )


def resolve(workspace: Path) -> None:
    evidence = workspace / ".local" / "pilot" / "evidence"
    report = load_json(evidence / "unresolved.json")
    conflicts = [
        row
        for row in report["rows"]
        if isinstance(row, dict) and row.get("status") == "conflict"
    ]
    if len(conflicts) != 1:
        raise AssertionError("Golden-Dry-Run muss genau einen Konflikt besitzen")
    candidates = conflicts[0].get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise AssertionError("Golden-Konflikt muss zwei echte Kandidaten besitzen")
    candidate = sorted(candidates, key=lambda item: str(item["twentyId"]))[0]
    private_json(
        workspace / ".local" / "pilot" / "manifests" / "resolutions.json",
        {
            "schemaVersion": 1,
            "batchId": "IMPORT-GOLDEN-001",
            "decisions": [
                {
                    "sourceId": conflicts[0]["source_id"],
                    "decision": "use-existing",
                    "targetTwentyId": candidate["twentyId"],
                    "decidedBy": "ACTOR-REVIEWER-01",
                    "decidedAt": "2026-07-29T20:10:00Z",
                }
            ],
        },
    )


def approve(workspace: Path) -> None:
    pilot = workspace / ".local" / "pilot"
    dry = load_json(pilot / "evidence" / "dry-a.json")
    backup = pilot / "backups" / "manifest.json"
    private_json(
        pilot / "manifests" / "approval.json",
        {
            "schemaVersion": 1,
            "batchId": dry["batchId"],
            "targetEnvironment": dry["targetEnvironment"],
            "planFingerprint": dry["planFingerprint"],
            "sourceSha256": dry["sourceSha256"],
            "mappingSha256": dry["mappingSha256"],
            "resolutionSha256": dry["resolutionSha256"],
            "backupManifestSha256": sha256_file(backup),
            "recoveryPointId": "RECOVERY-GOLDEN-001",
            "approvedBy": ["ACTOR-OWNER-01", "ACTOR-OPERATOR-01"],
            "approvedAt": "2026-07-29T20:20:00Z",
        },
    )


def write_negative_manifests(workspace: Path) -> None:
    pilot = workspace / ".local" / "pilot"
    resolutions = load_json(pilot / "manifests" / "resolutions.json")
    decisions = resolutions.get("decisions")
    if not isinstance(decisions, list):
        raise AssertionError("Resolution-Fixture enthält keine decisions")
    stale = {**resolutions, "decisions": [*decisions]}
    stale["decisions"].append(
        {
            "sourceId": "00000000-0000-4000-8000-000000000099",
            "decision": "create-new",
            "decidedBy": "ACTOR-REVIEWER-01",
            "decidedAt": "2026-07-29T20:11:00Z",
        }
    )
    private_json(pilot / "manifests" / "stale-resolutions.json", stale)

    backup = load_json(pilot / "backups" / "manifest.json")
    private_json(
        pilot / "backups" / "wrong-target-manifest.json",
        {**backup, "sourceProject": "leonaid-staging-other"},
    )


def check_reports(workspace: Path) -> None:
    evidence = workspace / ".local" / "pilot" / "evidence"
    dry_a_bytes = (evidence / "dry-a.json").read_bytes()
    dry_b_bytes = (evidence / "dry-b.json").read_bytes()
    if dry_a_bytes != dry_b_bytes:
        raise AssertionError("identische Dry Runs sind nicht bytegleich")
    dry = load_json(evidence / "dry-a.json")
    applied = load_json(evidence / "apply.json")
    verified = load_json(evidence / "verify.json")
    restored = load_json(evidence / "restored.json")
    if dry["summary"] != {
        "new": 1,
        "update": 2,
        "unchanged": 0,
        "conflict": 0,
        "rejected": 1,
    }:
        raise AssertionError(f"unerwarteter freigegebener Dry Run: {dry['summary']}")
    if applied["appliedCount"] != 3 or applied["summary"] != dry["summary"]:
        raise AssertionError("Apply setzte nicht exakt drei freigegebene Writes um")
    if verified["summary"] != {
        "new": 0,
        "update": 0,
        "unchanged": 3,
        "conflict": 0,
        "rejected": 1,
    }:
        raise AssertionError(f"Verify ist nicht idempotent: {verified['summary']}")
    if restored["summary"] != {
        "new": 1,
        "update": 1,
        "unchanged": 0,
        "conflict": 1,
        "rejected": 1,
    }:
        raise AssertionError(
            f"Recovery Point stellte den Vorzustand nicht her: {restored['summary']}"
        )
    for row in dry["rows"]:
        if not str(row.get("error_code", "")).startswith("ROW_"):
            raise AssertionError("Reportzeile besitzt keinen stabilen Fehlercode")
    summary_text = (evidence / "summary.json").read_text(encoding="utf-8")
    for forbidden in ("rows", "candidates", "Nordstern", "Mustermann", "@"):
        if forbidden in summary_text:
            raise AssertionError(
                f"sanitizte Summe enthält privaten Marker: {forbidden}"
            )
    for path in evidence.iterdir():
        if path.is_file() and stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise AssertionError(f"Evidence ist nicht Modus 0600: {path}")


def hold_lock(workspace: Path, ready: Path, release: Path) -> None:
    lock_path = (
        workspace / ".local" / "pilot" / "manifests" / ".IMPORT-GOLDEN-001.apply.lock"
    )
    with lock_path.open("a+", encoding="utf-8") as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        ready.write_text("ready\n", encoding="utf-8")
        deadline = time.monotonic() + 20
        while not release.exists():
            if time.monotonic() >= deadline:
                raise AssertionError("Concurrency-Test erhielt kein Release-Signal")
            time.sleep(0.05)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    subparsers = result.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("root", type=Path)
    prepare_parser.add_argument("workspace", type=Path)
    damaged_parser = subparsers.add_parser("check-damaged")
    damaged_parser.add_argument("workspace", type=Path)
    backup_parser = subparsers.add_parser("write-backup-manifest")
    backup_parser.add_argument("workspace", type=Path)
    backup_parser.add_argument("source_project")
    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("workspace", type=Path)
    approve_parser = subparsers.add_parser("approve")
    approve_parser.add_argument("workspace", type=Path)
    negative_parser = subparsers.add_parser("write-negative-manifests")
    negative_parser.add_argument("workspace", type=Path)
    check_parser = subparsers.add_parser("check-reports")
    check_parser.add_argument("workspace", type=Path)
    lock_parser = subparsers.add_parser("hold-lock")
    lock_parser.add_argument("workspace", type=Path)
    lock_parser.add_argument("ready", type=Path)
    lock_parser.add_argument("release", type=Path)
    return result


def main() -> None:
    arguments = parser().parse_args()
    if arguments.command == "prepare":
        prepare(arguments.root.resolve(), arguments.workspace.resolve())
    elif arguments.command == "check-damaged":
        check_damaged(arguments.workspace.resolve())
    elif arguments.command == "write-backup-manifest":
        write_backup_manifest(
            arguments.workspace.resolve(),
            arguments.source_project,
        )
    elif arguments.command == "resolve":
        resolve(arguments.workspace.resolve())
    elif arguments.command == "approve":
        approve(arguments.workspace.resolve())
    elif arguments.command == "write-negative-manifests":
        write_negative_manifests(arguments.workspace.resolve())
    elif arguments.command == "check-reports":
        check_reports(arguments.workspace.resolve())
    else:
        hold_lock(
            arguments.workspace.resolve(),
            arguments.ready.resolve(),
            arguments.release.resolve(),
        )


if __name__ == "__main__":
    main()
