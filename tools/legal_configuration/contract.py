#!/usr/bin/env python3
"""Real PostgreSQL/FastAPI contract for legal configuration."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
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
SESSION_NAMESPACE = UUID("35cd44c4-6106-4f7f-84c9-ced1d57cb044")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(label: str, user_id: UUID) -> str:
    return f"pilot044-{label}-{user_id}-real-session-token-value"


def session_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def error_code(response: httpx.Response) -> str:
    value = response.json()
    if not isinstance(value, dict) or not isinstance(value.get("error"), dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Vertrag")
    return str(value["error"].get("code"))


def draft_payload(*, revision: int) -> dict[str, object]:
    return {
        "expectedRevision": revision,
        "issuer": {
            "legalName": "Golden Förderverein e. V.",
            "streetLine1": "Testweg 44",
            "postalCode": "86150",
            "city": "Augsburg",
            "countryCode": "DE",
            "taxIdentifier": "103/123/45678",
            "email": "rechnung@leonaid.invalid",
        },
        "bankAccountHolder": "Golden Förderverein e. V.",
        "iban": "DE89370400440532013000",
        "bic": "COBADEFFXXX",
        "taxTreatment": "tax_exempt",
        "taxRateBasisPoints": 0,
        "taxNote": "Steuerbefreiung laut dokumentierter fachlicher Prüfung.",
        "numberPrefix": "KT",
        "numberWidth": 5,
        "paymentTermsDays": 14,
        "publicOrderLegalBasis": "Vertragserfüllung für die öffentliche Bestellung.",
        "publicOrderNoticeText": (
            "Wir verarbeiten die angegebenen Daten ausschließlich zur "
            "Durchführung und Abrechnung der Krapfentaxi-Bestellung."
        ),
        "consentTextVersion": "public-order-v1",
        "privacyContactEmail": "datenschutz@leonaid.invalid",
        "retention": {
            "invoiceDays": 3650,
            "commitmentDays": 3650,
            "contactDays": 730,
            "consentEvidenceDays": 3650,
            "auditDays": 3650,
        },
        "eInvoiceDecision": "pending",
        "taxEvidenceId": "STEUER-PILOT-044",
        "privacyEvidenceId": "DATENSCHUTZ-PILOT-044",
        "eInvoiceEvidenceId": None,
    }


async def seed_sessions(
    connection: asyncpg.Connection[Any],
    output: Path,
) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    await connection.execute(
        """
        INSERT INTO user_global_role (user_id, role)
        VALUES ($1, 'system_admin')
        ON CONFLICT DO NOTHING
        """,
        KLARA_ID,
    )
    sessions = (
        ("SIMONE_SESSION", "simone", SIMONE_ID),
        ("KLARA_SESSION", "klara", KLARA_ID),
        ("ANNA_SESSION", "anna", ANNA_ID),
    )
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        [SIMONE_ID, KLARA_ID, ANNA_ID],
    )
    tokens: dict[str, str] = {}
    lines: list[str] = []
    for env_name, label, user_id in sessions:
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
            VALUES ($1, $2, $3, $4, $5, $5, 'PILOT-044 legal', $5, $5)
            """,
            uuid5(SESSION_NAMESPACE, label),
            user_id,
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )
    output.write_text("".join(lines), encoding="utf-8")
    output.chmod(0o600)
    return tokens


async def prepare(connection: asyncpg.Connection[Any], sessions_path: Path) -> None:
    tokens = await seed_sessions(connection, sessions_path)
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        initial = await api.get(
            "/api/v1/admin/legal/configuration",
            headers=session_headers(tokens["simone"]),
        )
        initial.raise_for_status()
        if initial.json() != {
            "revision": 1,
            "production": False,
            "draft": None,
            "active": None,
            "draftApproval": None,
        }:
            raise ContractFailure("Initialzustand ist nicht deterministisch")

        forbidden = await api.get(
            "/api/v1/admin/legal/configuration",
            headers=session_headers(tokens["anna"]),
        )
        if (
            forbidden.status_code != 403
            or error_code(forbidden) != "system_admin_required"
        ):
            raise ContractFailure("Akquisiteurin konnte Rechtsgrundlage lesen")

        created = await api.put(
            "/api/v1/admin/legal/configuration/draft",
            headers=session_headers(tokens["simone"]),
            json=draft_payload(revision=1),
        )
        created.raise_for_status()
        state = created.json()
        if (
            state.get("revision") != 2
            or not isinstance(state.get("draft"), dict)
            or state["draft"].get("version") != 1
        ):
            raise ContractFailure("Erste unveränderliche Version wurde nicht angelegt")

        version_id = str(state["draft"]["id"])
        own_approval = await api.post(
            f"/api/v1/admin/legal/configuration/draft/{version_id}/approval",
            headers=session_headers(tokens["simone"]),
            json={
                "evidenceId": "FREIGABE-PILOT-044",
                "expectedRevision": 2,
            },
        )
        if (
            own_approval.status_code != 409
            or error_code(own_approval) != "legal_configuration_four_eyes_required"
        ):
            raise ContractFailure("Vier-Augen-Grenze ließ Eigenfreigabe zu")

        approved = await api.post(
            f"/api/v1/admin/legal/configuration/draft/{version_id}/approval",
            headers=session_headers(tokens["klara"]),
            json={
                "evidenceId": "FREIGABE-PILOT-044",
                "expectedRevision": 2,
            },
        )
        approved.raise_for_status()
        if approved.json().get("revision") != 3:
            raise ContractFailure("Freigabe erhöhte Revision nicht")

        blocked = await api.post(
            f"/api/v1/admin/legal/configuration/draft/{version_id}/activation",
            headers=session_headers(tokens["simone"]),
            json={"expectedRevision": 3},
        )
        if (
            blocked.status_code != 409
            or error_code(blocked) != "legal_configuration_activation_blocked"
        ):
            raise ContractFailure("Offene E-Rechnungsentscheidung wurde aktiviert")

        stale = await api.put(
            "/api/v1/admin/legal/configuration/draft",
            headers=session_headers(tokens["simone"]),
            json=draft_payload(revision=1),
        )
        if (
            stale.status_code != 409
            or error_code(stale) != "legal_configuration_revision_conflict"
        ):
            raise ContractFailure(
                "Optimistische Revision verhinderte Lost Update nicht"
            )


async def assert_result(connection: asyncpg.Connection[Any]) -> None:
    state = await connection.fetchrow(
        """
        SELECT revision, draft_version_id, active_version_id
        FROM legal_configuration_state
        """
    )
    if (
        state is None
        or int(state["revision"]) != 6
        or state["draft_version_id"] is not None
        or state["active_version_id"] is None
    ):
        raise ContractFailure(f"Finaler Aktivzustand ist ungültig: {state}")

    versions = await connection.fetch(
        """
        SELECT version, e_invoice_decision, e_invoice_evidence_id
        FROM legal_configuration_version
        ORDER BY version
        """
    )
    if [
        (
            int(row["version"]),
            str(row["e_invoice_decision"]),
            row["e_invoice_evidence_id"],
        )
        for row in versions
    ] != [
        (1, "pending", None),
        (2, "not_required", "ERECHNUNG-PILOT-044"),
    ]:
        raise ContractFailure("Versionen sind nicht vollständig oder wurden verändert")

    rows = await connection.fetch(
        """
        SELECT event_type, payload::text
        FROM audit_event
        WHERE entity_type = 'legal_configuration'
        ORDER BY occurred_at, id
        """
    )
    if [str(row["event_type"]) for row in rows] != [
        "legal_configuration_draft_saved",
        "legal_configuration_approved",
        "legal_configuration_draft_saved",
        "legal_configuration_approved",
        "legal_configuration_activated",
    ]:
        raise ContractFailure("Audit-Sequenz ist unvollständig")
    forbidden_fragments = (
        "DE89370400440532013000",
        "@leonaid.invalid",
        "Testweg",
        "Datenschutz",
    )
    audit_payload = json.dumps([str(row["payload"]) for row in rows])
    if any(fragment in audit_payload for fragment in forbidden_fragments):
        raise ContractFailure("Audit enthält vertrauliche Konfigurationswerte")

    active_version_id = state["active_version_id"]
    approval = await connection.fetchrow(
        """
        SELECT approved_by_user_id, evidence_id
        FROM legal_configuration_approval
        WHERE version_id = $1
        """,
        active_version_id,
    )
    if (
        approval is None
        or approval["approved_by_user_id"] != SIMONE_ID
        or approval["evidence_id"] != "UI-FREIGABE-PILOT-044"
    ):
        raise ContractFailure("Aktive Version besitzt keine unabhängige UI-Freigabe")

    print(
        "legal-configuration-contract: OK: Versionierung, Vier-Augen-Grenze, "
        "Aktivierungsstopp und PII-freies Audit bewiesen"
    )


async def run(command: str, sessions_path: Path | None) -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"))
    try:
        if command == "prepare":
            if sessions_path is None:
                raise ContractFailure("prepare benötigt --sessions")
            await prepare(connection, sessions_path)
        else:
            await assert_result(connection)
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "assert"))
    parser.add_argument("--sessions", type=Path)
    arguments = parser.parse_args()
    asyncio.run(run(arguments.command, arguments.sessions))


if __name__ == "__main__":
    main()
