#!/usr/bin/env python3
"""Create private pilot paths and privacy-minimal evidence manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

PRIVATE_DIRECTORIES = ("intake", "evidence", "backups", "manifests")
OPAQUE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
ERROR_CLASS_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


class Counts(TypedDict):
    bytes: int


class Timestamps(TypedDict):
    recorded_at: str


class EvidenceManifest(TypedDict):
    sha256: str
    counts: Counts
    error_classes: list[str]
    timestamps: Timestamps
    actor_id: str
    external_evidence_id: str


class EvidenceError(RuntimeError):
    """Raised when private evidence metadata is unsafe or incomplete."""


def ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def initialize(root: Path) -> Path:
    pilot_root = root / ".local" / "pilot"
    ensure_private_directory(root / ".local")
    ensure_private_directory(pilot_root)
    for name in PRIVATE_DIRECTORIES:
        ensure_private_directory(pilot_root / name)
    return pilot_root


def validate_opaque_id(value: str, label: str) -> str:
    if not OPAQUE_ID_PATTERN.fullmatch(value):
        raise EvidenceError(
            f"{label} muss eine opake ID wie ACTOR-ADMIN-01 oder EVID-TAX-001 sein"
        )
    return value


def validate_timestamp(value: str) -> str:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise EvidenceError("recorded-at ist kein ISO-8601-Zeitpunkt") from error
    if parsed.tzinfo is None:
        raise EvidenceError("recorded-at benötigt eine Zeitzone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(
    source: Path,
    *,
    actor_id: str,
    external_evidence_id: str,
    error_classes: list[str],
    recorded_at: str,
) -> EvidenceManifest:
    if not source.is_file():
        raise EvidenceError("private Evidence-Datei fehlt")
    actor = validate_opaque_id(actor_id, "actor-id")
    evidence = validate_opaque_id(external_evidence_id, "external-evidence-id")
    normalized_errors: list[str] = []
    for error_class in error_classes:
        if not ERROR_CLASS_PATTERN.fullmatch(error_class):
            raise EvidenceError(f"ungültige Fehlerklasse: {error_class!r}")
        normalized_errors.append(error_class)
    return {
        "sha256": sha256_file(source),
        "counts": {"bytes": source.stat().st_size},
        "error_classes": sorted(set(normalized_errors)),
        "timestamps": {"recorded_at": validate_timestamp(recorded_at)},
        "actor_id": actor,
        "external_evidence_id": evidence,
    }


def write_private_json(path: Path, payload: EvidenceManifest) -> None:
    ensure_private_directory(path.parent)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        temporary.replace(path)
        path.chmod(0o600)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--root", type=Path, default=Path.cwd())

    manifest_parser = subparsers.add_parser("manifest")
    manifest_parser.add_argument("source", type=Path)
    manifest_parser.add_argument("output", type=Path)
    manifest_parser.add_argument("--actor-id", required=True)
    manifest_parser.add_argument("--external-evidence-id", required=True)
    manifest_parser.add_argument("--error-class", action="append", default=[])
    manifest_parser.add_argument(
        "--recorded-at",
        default=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )

    arguments = parser.parse_args()
    try:
        if arguments.command == "init":
            pilot_root = initialize(arguments.root.resolve())
            print(f"pilot-evidence: OK: private Pfade bereit: {pilot_root}")
            return
        manifest = build_manifest(
            arguments.source.resolve(),
            actor_id=arguments.actor_id,
            external_evidence_id=arguments.external_evidence_id,
            error_classes=arguments.error_class,
            recorded_at=arguments.recorded_at,
        )
        write_private_json(arguments.output.resolve(), manifest)
        print(
            "pilot-evidence: OK: minimales Manifest mit SHA-256 und "
            "nicht-personenbezogenen Metadaten geschrieben"
        )
    except EvidenceError as error:
        parser.exit(64, f"pilot-evidence: ERROR: {error}\n")


if __name__ == "__main__":
    main()
