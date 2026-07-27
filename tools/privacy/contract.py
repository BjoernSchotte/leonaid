#!/usr/bin/env python3
"""Real privacy, suppression, export and retention contract."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import httpx

from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

SIMONE_ID = UUID("10000000-0000-4000-8000-000000000001")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
COMPANY_ID = UUID("40000000-0000-4000-8000-000000000001")
CONSENT_ID = UUID("d0000000-0000-4000-8000-000000000001")
INVOICE_ID = UUID("90000000-0000-4000-8000-000000000002")
EMAIL = "mara.muster@musterwerk.leonaid.invalid"
SESSION_NAMESPACE = UUID("d7b23eb1-c615-4665-99e1-c35029b9c460")
FOREIGN_CANARIES = (
    "40000000-0000-4000-8000-000000000002",
    "50000000-0000-4000-8000-000000000003",
    "80000000-0000-4000-8000-000000000006",
    "90000000-0000-4000-8000-000000000003",
)


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(label: str, user_id: UUID) -> str:
    return f"poc111-{label}-{user_id}-real-session-token-value"


def headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def error_code(response: httpx.Response) -> str:
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Vertrag")
    return str(payload["error"].get("code"))


async def seed_sessions(
    connection: asyncpg.Connection[Any],
    output: Path,
) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    sessions = (
        ("SIMONE_SESSION", "simone", SIMONE_ID, now),
        ("STALE_SIMONE_SESSION", "simone-stale", SIMONE_ID, now - timedelta(hours=1)),
        ("KLARA_SESSION", "klara", KLARA_ID, now),
        ("ANNA_SESSION", "anna", ANNA_ID, now),
    )
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        [SIMONE_ID, KLARA_ID, ANNA_ID],
    )
    tokens: dict[str, str] = {}
    lines: list[str] = []
    for env_name, label, user_id, fresh_at in sessions:
        token = token_for(label, user_id)
        tokens[label] = token
        lines.append(f"{env_name}={token}\n")
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at,
                last_seen_at, fresh_login_at, device_hint,
                created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, 'POC-111 Privacy', $6, $5)
            """,
            uuid5(SESSION_NAMESPACE, label),
            user_id,
            session_token_digest(token),
            fresh_at + SESSION_LIFETIME,
            now,
            fresh_at,
        )
    output.write_text("".join(lines), encoding="utf-8")
    output.chmod(0o600)
    return tokens


async def immutable_hashes(connection: asyncpg.Connection[Any]) -> dict[str, str]:
    row = await connection.fetchrow(
        """
        SELECT
            md5(to_jsonb(invoice)::text) AS invoice_hash,
            md5(to_jsonb(document)::text) AS document_hash
        FROM invoice
        JOIN generated_document AS document
          ON document.invoice_id = invoice.id
        WHERE invoice.id = $1
        """,
        INVOICE_ID,
    )
    if row is None:
        raise ContractFailure("Golden-Rechnung besitzt kein erzeugtes Dokument")
    return {
        "invoiceHash": str(row["invoice_hash"]),
        "documentHash": str(row["document_hash"]),
    }


async def prepare(
    connection: asyncpg.Connection[Any],
    sessions_path: Path,
    baseline_path: Path,
) -> None:
    tokens = await seed_sessions(connection, sessions_path)
    baseline_path.write_text(
        json.dumps(await immutable_hashes(connection), indent=2) + "\n",
        encoding="utf-8",
    )
    baseline_path.chmod(0o600)
    evidence = await connection.fetchrow(
        "SELECT * FROM consent_record WHERE id = $1",
        CONSENT_ID,
    )
    if (
        evidence is None
        or evidence["commitment_id"] != UUID("80000000-0000-4000-8000-000000000005")
        or str(evidence["normalized_recipient"]) != EMAIL
        or str(evidence["evidence_kind"]) != "notice_acknowledgement"
        or str(evidence["legal_basis_status"]) != "legal_review_pending"
        or evidence["revoked_at"] is not None
    ):
        raise ContractFailure("Golden-Nachweis ist nicht deterministisch")

    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        lookup = await api.post(
            "/api/v1/admin/privacy/lookup",
            headers=headers(tokens["simone"]),
            json={"email": EMAIL},
        )
        lookup.raise_for_status()
        payload = lookup.json()
        if (
            payload.get("found") is not True
            or payload.get("subjectEmail") != EMAIL
            or payload.get("crmDeletionStatus") != "pending_manual_review"
            or not payload.get("openLegalDecisions")
        ):
            raise ContractFailure("Privacy-Lookup verschweigt PoC-Grenzen")

        export = await api.post(
            "/api/v1/admin/privacy/exports",
            headers=headers(tokens["simone"]),
            json={"email": EMAIL},
        )
        export.raise_for_status()
        serialized = export.text
        if (
            "attachment" not in export.headers.get("content-disposition", "")
            or any(canary in serialized for canary in FOREIGN_CANARIES)
            or str(INVOICE_ID) not in serialized
        ):
            raise ContractFailure(
                "Datenauskunft enthält fremde oder unvollständige Daten"
            )

        forbidden = await api.post(
            "/api/v1/admin/privacy/lookup",
            headers=headers(tokens["klara"]),
            json={"email": EMAIL},
        )
        if (
            forbidden.status_code != 403
            or error_code(forbidden) != "system_admin_required"
        ):
            raise ContractFailure("Charity-Admin konnte globale Privacy-Daten lesen")

        stale = await api.post(
            "/api/v1/admin/privacy/exports",
            headers=headers(tokens["simone-stale"]),
            json={"email": EMAIL},
        )
        if stale.status_code != 401 or error_code(stale) != "fresh_login_required":
            raise ContractFailure("Datenauskunft verlangte keinen frischen Login")


async def assert_result(
    connection: asyncpg.Connection[Any],
    baseline_path: Path,
) -> None:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if await immutable_hashes(connection) != baseline:
        raise ContractFailure(
            "Rechnung oder Rechnungs-PDF wurde bei Löschung verändert"
        )

    evidence = await connection.fetchrow(
        "SELECT revoked_at FROM consent_record WHERE id = $1",
        CONSENT_ID,
    )
    suppressions = await connection.fetch(
        """
        SELECT purpose
        FROM suppression_entry
        WHERE normalized_recipient = $1
          AND channel = 'email'
        ORDER BY purpose
        """,
        EMAIL,
    )
    if evidence is None or evidence["revoked_at"] is None:
        raise ContractFailure("Nachweis wurde nicht widerrufen")
    if {str(row["purpose"]) for row in suppressions} != {
        "acquisition",
        "marketing",
    }:
        raise ContractFailure("Akquise- und Marketing-Sperren fehlen")

    commitment = await connection.fetchrow(
        """
        SELECT customer_snapshot, invoice_recipient_snapshot,
               delivery_recipient_snapshot, message_snapshot
        FROM commitment
        WHERE id = '80000000-0000-4000-8000-000000000005'
        """
    )
    if commitment is None:
        raise ContractFailure("Operative Golden-Bestellung fehlt")
    serialized = json.dumps(dict(commitment), default=str, ensure_ascii=False)
    if (
        EMAIL in serialized
        or "Musterwerk GmbH" in serialized
        or "Werkstraße" in serialized
        or commitment["message_snapshot"] is not None
    ):
        raise ContractFailure("Operative Bestelldaten wurden nicht anonymisiert")

    erasure = await connection.fetchrow(
        """
        SELECT *
        FROM privacy_erasure_case
        ORDER BY completed_at DESC
        LIMIT 1
        """
    )
    if (
        erasure is None
        or str(erasure["status"]) != "completed_with_retention"
        or erasure["subject_hash"] == EMAIL
        or EMAIL in json.dumps(dict(erasure), default=str)
    ):
        raise ContractFailure("Löschprotokoll ist unvollständig oder enthält Roh-PII")
    audit_leak = await connection.fetchval(
        "SELECT count(*) FROM audit_event WHERE payload::text ILIKE '%' || $1 || '%'",
        EMAIL,
    )
    if audit_leak:
        raise ContractFailure("Privacy-Audit enthält die rohe E-Mail-Adresse")

    anna = token_for("anna", ANNA_ID)
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        board = await api.get(
            f"/api/v1/actions/{ACTION_ID}/acquisition/activity-board",
            headers=headers(anna),
        )
        board.raise_for_status()
        work_item = next(
            (
                item
                for item in board.json().get("workItems", [])
                if item.get("partyId") == str(COMPANY_ID)
            ),
            None,
        )
        if work_item is None or "email" not in work_item.get("suppressedChannels", []):
            raise ContractFailure("Akquisiteur-UI erhält die Kontaktsperre nicht")
        blocked = await api.post(
            f"/api/v1/actions/{ACTION_ID}/acquisition/activities",
            headers=headers(anna),
            json={
                "partyKind": "company",
                "partyId": str(COMPANY_ID),
                "revision": work_item["revision"],
                "channel": "email",
                "outcome": "reached",
                "note": "Dieser Text darf nie gespeichert werden.",
                "nextAction": None,
                "dueOn": None,
            },
        )
        if blocked.status_code != 409 or error_code(blocked) != "contact_suppressed":
            raise ContractFailure("Direkter API-Aufruf umging die Kontaktsperre")


async def run(
    command: str,
    sessions_path: Path | None,
    baseline_path: Path,
) -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        if command == "prepare":
            if sessions_path is None:
                raise ContractFailure("prepare benötigt eine Sessions-Datei")
            await prepare(connection, sessions_path, baseline_path)
        else:
            await assert_result(connection, baseline_path)
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "assert"))
    parser.add_argument("sessions_path", nargs="?", type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    arguments = parser.parse_args()
    asyncio.run(run(arguments.command, arguments.sessions_path, arguments.baseline))
    print(f"privacy-contract: OK: {arguments.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
