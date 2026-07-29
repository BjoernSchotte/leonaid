#!/usr/bin/env python3
"""Maintain a PII-free append-only release promotion ledger."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.pilot_release.manifest import (
    InvalidManifest,
    _load_object,
    manifest_sha256,
    validate_manifest,
)

ALLOWED_EVENTS = {
    "staging_started",
    "staging_verified",
    "production_started",
    "production_failed",
    "production_verified",
    "rollback_started",
    "rollback_verified",
}
EVIDENCE_ID = re.compile(r"^[A-Z0-9][A-Z0-9._:-]{2,119}$")


class InvalidPromotion(RuntimeError):
    """Raised when an unsafe release promotion is requested."""


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise InvalidPromotion("Ledger-Zeile ist kein Objekt")
            records.append(value)
    except (OSError, json.JSONDecodeError) as error:
        raise InvalidPromotion(f"Ledger ist ungültig: {error}") from error
    return records


def _staging_verified(records: list[dict[str, Any]], digest: str) -> bool:
    return any(
        record.get("event") == "staging_verified"
        and record.get("manifestSha256") == digest
        and record.get("result") == "passed"
        for record in records
    )


def record_event(
    *,
    manifest: dict[str, Any],
    ledger: Path,
    event: str,
    result: str,
    evidence_id: str,
    occurred_at: str,
) -> dict[str, Any]:
    validate_manifest(manifest)
    if event not in ALLOWED_EVENTS:
        raise InvalidPromotion("unbekanntes Release-Ereignis")
    if result not in {"passed", "failed"}:
        raise InvalidPromotion("result muss passed oder failed sein")
    if EVIDENCE_ID.fullmatch(evidence_id) is None:
        raise InvalidPromotion("Evidence-ID ist ungültig")
    try:
        parsed_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidPromotion("occurredAt ist ungültig") from error
    if parsed_at.tzinfo is None:
        raise InvalidPromotion("occurredAt benötigt eine Zeitzone")

    digest = manifest_sha256(manifest)
    records = _load_ledger(ledger)
    if event.startswith("production_") and not _staging_verified(records, digest):
        raise InvalidPromotion(
            "Produktion erfordert dasselbe in Staging verifizierte Manifest"
        )
    if event.startswith("rollback_") and not any(
        record.get("event") in {"production_started", "production_failed"}
        and record.get("manifestSha256") == digest
        for record in records
    ):
        raise InvalidPromotion("Rollback erfordert einen Produktionsversuch")

    sequence = len(records) + 1
    record = {
        "schemaVersion": 1,
        "sequence": sequence,
        "occurredAt": parsed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "releaseId": manifest["releaseId"],
        "manifestSha256": digest,
        "event": event,
        "result": result,
        "evidenceId": evidence_id,
    }
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--event", choices=sorted(ALLOWED_EVENTS), required=True)
    parser.add_argument("--result", choices=("passed", "failed"), required=True)
    parser.add_argument("--evidence-id", required=True)
    parser.add_argument("--occurred-at", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    try:
        manifest = _load_object(arguments.manifest)
        record = record_event(
            manifest=manifest,
            ledger=arguments.ledger,
            event=arguments.event,
            result=arguments.result,
            evidence_id=arguments.evidence_id,
            occurred_at=arguments.occurred_at,
        )
    except (InvalidManifest, InvalidPromotion, OSError) as error:
        print(f"pilot-release-promotion: ERROR: {error}", file=sys.stderr)
        return 1
    print(f"pilot-release-promotion: OK: {record['event']} #{record['sequence']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
