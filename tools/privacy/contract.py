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
LEGAL_CONFIGURATION_ID = UUID("94000000-0000-4000-8000-000000000044")
EMAIL = "mara.muster@musterwerk.leonaid.invalid"
INBOX_CASE_ID = UUID("e0000000-0000-4000-8000-000000000001")
FOREIGN_INBOX_CASE_ID = UUID("e0000000-0000-4000-8000-000000000002")
INBOX_MESSAGE = "Bitte ruft mich wegen der Abholung zurück."
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
        raise ContractFailure(f"Missing environment variable: {name}")
    return value


def token_for(label: str, user_id: UUID) -> str:
    return f"poc111-{label}-{user_id}-real-session-token-value"


def headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def error_code(response: httpx.Response) -> str:
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        raise ContractFailure("Error response has no stable contract")
    return str(payload["error"].get("code"))


async def seed_sessions(connection: asyncpg.Connection[Any]) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    sessions = (
        ("simone", SIMONE_ID, now),
        ("simone-stale", SIMONE_ID, now - timedelta(hours=1)),
        ("klara", KLARA_ID, now),
        ("anna", ANNA_ID, now),
    )
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        [SIMONE_ID, KLARA_ID, ANNA_ID],
    )
    tokens: dict[str, str] = {}
    for label, user_id, fresh_at in sessions:
        token = token_for(label, user_id)
        tokens[label] = token
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
        raise ContractFailure("Golden invoice has no generated document")
    return {
        "invoiceHash": str(row["invoice_hash"]),
        "documentHash": str(row["document_hash"]),
    }


async def seed_inbox_cases(connection: asyncpg.Connection[Any]) -> None:
    """One public inquiry of the subject (mixed-case address) and a foreign one."""
    for case_id, email in (
        (INBOX_CASE_ID, EMAIL.replace("mara", "Mara", 1)),
        (FOREIGN_INBOX_CASE_ID, "jona.fremd@leonaid.invalid"),
    ):
        await connection.execute(
            """
            INSERT INTO inbox_case (
                id, public_reference, action_id, subject, message, given_name,
                family_name, email, phone, contact_create_id, consent_text_version
            )
            VALUES ($1, gen_random_uuid(), $2, 'Rückruf', $3, 'Mara', 'Muster',
                    $4, '+49 170 1234567', gen_random_uuid(),
                    'inbox-privacy-2026-11')
            """,
            case_id,
            ACTION_ID,
            INBOX_MESSAGE,
            email,
        )


async def prepare(
    connection: asyncpg.Connection[Any],
    baseline_path: Path,
) -> None:
    tokens = await seed_sessions(connection)
    await seed_inbox_cases(connection)
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
        raise ContractFailure("Golden consent evidence is not deterministic")
    if await connection.fetchval(
        "SELECT count(*) FROM suppression_entry WHERE normalized_recipient = $1",
        EMAIL,
    ):
        raise ContractFailure("The subject is suppressed before the revocation")

    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        await connection.execute(
            """
            UPDATE legal_configuration_state
            SET active_version_id = NULL
            """
        )
        missing_configuration = await api.post(
            "/api/v1/admin/privacy/lookup",
            headers=headers(tokens["simone"]),
            json={"email": EMAIL},
        )
        if (
            missing_configuration.status_code != 409
            or error_code(missing_configuration)
            != "privacy_legal_configuration_missing"
        ):
            raise ContractFailure("Privacy request ran without active retention rules")
        await connection.execute(
            """
            UPDATE legal_configuration_state
            SET active_version_id = $1
            """,
            LEGAL_CONFIGURATION_ID,
        )

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
            or payload.get("retention")
            != {
                "legalConfigurationVersionId": str(LEGAL_CONFIGURATION_ID),
                "legalConfigurationVersion": 1,
                "invoiceDays": 3650,
                "commitmentDays": 3650,
                "contactDays": 730,
                "consentEvidenceDays": 3650,
                "auditDays": 3650,
            }
        ):
            raise ContractFailure(
                "Privacy lookup hides retention periods or PoC limits"
            )
        inbox_references = [
            item
            for item in payload.get("references", [])
            if item.get("referenceType") == "inbox_case"
        ]
        if [item.get("id") for item in inbox_references] != [str(INBOX_CASE_ID)]:
            raise ContractFailure("Privacy lookup misses or mixes inbox cases")

        export = await api.post(
            "/api/v1/admin/privacy/exports",
            headers=headers(tokens["simone"]),
            json={"email": EMAIL},
        )
        export.raise_for_status()
        serialized = export.text
        if export.json().get("subjectEmail") != EMAIL:
            raise ContractFailure("Data export is not the subject's JSON report")
        if (
            "attachment" not in export.headers.get("content-disposition", "")
            or any(canary in serialized for canary in FOREIGN_CANARIES)
            or str(INVOICE_ID) not in serialized
            or str(LEGAL_CONFIGURATION_ID) not in serialized
            or str(INBOX_CASE_ID) not in serialized
            or str(FOREIGN_INBOX_CASE_ID) in serialized
        ):
            raise ContractFailure("Data export contains foreign or incomplete data")

        forbidden = await api.post(
            "/api/v1/admin/privacy/lookup",
            headers=headers(tokens["klara"]),
            json={"email": EMAIL},
        )
        if (
            forbidden.status_code != 403
            or error_code(forbidden) != "system_admin_required"
        ):
            raise ContractFailure("Charity admin could read global privacy data")

        stale = await api.post(
            "/api/v1/admin/privacy/exports",
            headers=headers(tokens["simone-stale"]),
            json={"email": EMAIL},
        )
        if stale.status_code != 401 or error_code(stale) != "fresh_login_required":
            raise ContractFailure("Data export did not require a fresh login")


async def act(connection: asyncpg.Connection[Any]) -> None:
    """The admin's UI steps through the API: revoke the consent, then erase.

    The erasure needs the address typed again exactly; the server enforces
    it. The client-side disabled button is proven in system-admin.test.tsx.
    """
    simone = headers(token_for("simone", SIMONE_ID))
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        revoked = await api.post(
            f"/api/v1/admin/privacy/consents/{CONSENT_ID}/revoke",
            headers=simone,
            json={"reason": "Kontaktwunsch der betroffenen Person"},
        )
        revoked.raise_for_status()
        if revoked.json().get("revokedAt") is None:
            raise ContractFailure("Consent revocation returned no revocation time")
        lookup = await api.post(
            "/api/v1/admin/privacy/lookup",
            headers=simone,
            json={"email": EMAIL},
        )
        lookup.raise_for_status()
        if {
            (item.get("channel"), item.get("purpose"))
            for item in lookup.json().get("suppressions", [])
        } != {("email", "acquisition"), ("email", "marketing")}:
            raise ContractFailure(
                "Revocation did not suppress acquisition and marketing"
            )

        # A fixture may ship erasure cases; the refusal must add none.
        cases_before = await connection.fetchval(
            "SELECT count(*) FROM privacy_erasure_case"
        )
        mismatch = await api.post(
            "/api/v1/admin/privacy/erasures",
            headers=simone,
            json={"email": EMAIL, "confirmation": EMAIL[:-1]},
        )
        if (
            mismatch.status_code != 409
            or error_code(mismatch) != "privacy_erasure_confirmation_mismatch"
        ):
            raise ContractFailure("Erasure ran without the exact confirmation")
        untouched = await connection.fetchrow(
            """
            SELECT
                (SELECT count(*) FROM privacy_erasure_case) AS cases,
                (SELECT customer_snapshot::text FROM commitment
                  WHERE id = '80000000-0000-4000-8000-000000000005') AS snapshot,
                (SELECT erased_at FROM inbox_case WHERE id = $1) AS erased_at
            """,
            INBOX_CASE_ID,
        )
        if (
            untouched is None
            or untouched["cases"] != cases_before
            or EMAIL not in str(untouched["snapshot"])
            or untouched["erased_at"] is not None
        ):
            raise ContractFailure("The refused erasure changed data")
        erased = await api.post(
            "/api/v1/admin/privacy/erasures",
            headers=simone,
            json={"email": EMAIL, "confirmation": EMAIL},
        )
        erased.raise_for_status()
        result = erased.json()
        if (
            result.get("status") != "completed_with_retention"
            or str(INVOICE_ID) not in result.get("retainedInvoiceIds", [])
            or result.get("anonymizedCommitments", 0) < 1
        ):
            raise ContractFailure("Erasure did not retain the invoice or anonymize")


async def assert_result(
    connection: asyncpg.Connection[Any],
    baseline_path: Path,
) -> None:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if await immutable_hashes(connection) != baseline:
        raise ContractFailure("Invoice or invoice PDF changed during erasure")

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
        raise ContractFailure("Consent evidence was not revoked")
    if {str(row["purpose"]) for row in suppressions} != {
        "acquisition",
        "marketing",
    }:
        raise ContractFailure("Acquisition and marketing suppressions are missing")

    commitment = await connection.fetchrow(
        """
        SELECT customer_snapshot, invoice_recipient_snapshot,
               delivery_recipient_snapshot, message_snapshot
        FROM commitment
        WHERE id = '80000000-0000-4000-8000-000000000005'
        """
    )
    if commitment is None:
        raise ContractFailure("Operational golden order is missing")
    serialized = json.dumps(dict(commitment), default=str, ensure_ascii=False)
    if (
        EMAIL in serialized
        or "Musterwerk GmbH" in serialized
        or "Werkstraße" in serialized
        or commitment["message_snapshot"] is not None
    ):
        raise ContractFailure("Operational order data was not anonymized")

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
        or erasure["legal_configuration_version_id"] != LEGAL_CONFIGURATION_ID
        or json.loads(erasure["retention_schedule"])
        != {
            "legalConfigurationVersion": 1,
            "invoiceDays": 3650,
            "commitmentDays": 3650,
            "contactDays": 730,
            "consentEvidenceDays": 3650,
            "auditDays": 3650,
        }
        or "3650 Tage" not in erasure["retention_reasons"]
    ):
        raise ContractFailure("Erasure record is incomplete or contains raw PII")
    inbox_cases = {
        row["id"]: row
        for row in await connection.fetch(
            "SELECT * FROM inbox_case WHERE id = ANY($1::uuid[])",
            [INBOX_CASE_ID, FOREIGN_INBOX_CASE_ID],
        )
    }
    erased_case = inbox_cases.get(INBOX_CASE_ID)
    if (
        erased_case is None
        or erased_case["erased_at"] is None
        or erased_case["email"] is not None
        or erased_case["phone"] is not None
        or erased_case["given_name"] != "Anonymisiert"
        or erased_case["message"] == INBOX_MESSAGE
    ):
        raise ContractFailure("Inbox case of the subject was not anonymized")
    foreign_case = inbox_cases.get(FOREIGN_INBOX_CASE_ID)
    if (
        foreign_case is None
        or foreign_case["erased_at"] is not None
        or foreign_case["message"] != INBOX_MESSAGE
    ):
        raise ContractFailure("Erasure changed a foreign inbox case")
    audit_leak = await connection.fetchval(
        "SELECT count(*) FROM audit_event WHERE payload::text ILIKE '%' || $1 || '%'",
        EMAIL,
    )
    if audit_leak:
        raise ContractFailure("Privacy audit contains the raw email address")

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
            raise ContractFailure(
                "Acquirer UI does not receive the contact suppression"
            )
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
            raise ContractFailure("Direct API call bypassed the contact suppression")


async def run(command: str, baseline_path: Path) -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        if command == "prepare":
            await prepare(connection, baseline_path)
        elif command == "act":
            await act(connection)
        else:
            await assert_result(connection, baseline_path)
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "act", "assert"))
    parser.add_argument("--baseline", required=True, type=Path)
    arguments = parser.parse_args()
    asyncio.run(run(arguments.command, arguments.baseline))
    print(f"privacy-contract: OK: {arguments.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
