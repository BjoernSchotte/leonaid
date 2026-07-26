#!/usr/bin/env python3
"""Real PostgreSQL/API concurrency and history contract for POC-060."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import httpx

from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
FREE_COMPANY_ID = UUID("40000000-0000-4000-8000-000000000004")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
BERND_ID = UUID("10000000-0000-4000-8000-000000000005")
CARLA_ID = UUID("10000000-0000-4000-8000-000000000006")
SESSION_NAMESPACE = UUID("98ee8092-cae7-47c0-be10-f01ce4117b19")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(user_id: UUID) -> str:
    return f"poc060-{user_id}-server-session-token-value"


async def seed_sessions(connection: asyncpg.Connection[Any]) -> dict[UUID, str]:
    now = datetime.now(timezone.utc)
    users = (KLARA_ID, ANNA_ID, BERND_ID, CARLA_ID)
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        list(users),
    )
    tokens: dict[UUID, str] = {}
    for user_id in users:
        token = token_for(user_id)
        tokens[user_id] = token
        await connection.execute(
            """
            INSERT INTO user_session (
                id,
                user_id,
                token_digest,
                expires_at,
                last_seen_at,
                fresh_login_at,
                created_at,
                updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $5, $5, $5)
            """,
            uuid5(SESSION_NAMESPACE, str(user_id)),
            user_id,
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )
    return tokens


async def request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    token: str,
    request_id: str,
    body: Mapping[str, object] | None = None,
) -> httpx.Response:
    return await client.request(
        method,
        path,
        cookies={SESSION_COOKIE_NAME: token},
        headers={"X-Request-ID": request_id},
        json=body,
    )


def error_code(response: httpx.Response) -> str:
    payload = response.json()
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Vertrag")
    return str(error.get("code"))


async def exercise(connection: asyncpg.Connection[Any]) -> None:
    tokens = await seed_sessions(connection)
    base_path = f"/api/v1/actions/{ACTION_ID}/acquisition/assignments"
    carla_body: dict[str, object] = {
        "partyKind": "company",
        "partyId": str(FREE_COMPANY_ID),
        "acquirerUserId": str(CARLA_ID),
    }
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        concurrent = await asyncio.gather(
            request(
                api,
                "POST",
                base_path,
                tokens[KLARA_ID],
                "poc060:concurrent-carla-a",
                carla_body,
            ),
            request(
                api,
                "POST",
                base_path,
                tokens[KLARA_ID],
                "poc060:concurrent-carla-b",
                carla_body,
            ),
        )
        if sorted(item.status_code for item in concurrent) != [200, 201]:
            raise ContractFailure(
                "Konkurrierende Zuweisung war nicht idempotent: "
                f"{[item.status_code for item in concurrent]}"
            )
        payloads = [item.json() for item in concurrent]
        assignment_ids = {
            item["assignment"]["id"] for item in payloads if isinstance(item, dict)
        }
        if len(assignment_ids) != 1 or sorted(
            bool(item["created"]) for item in payloads
        ) != [False, True]:
            raise ContractFailure(
                "Konkurrierende Antworten zeigen nicht dieselbe Zuweisung"
            )
        carla_assignment_id = UUID(assignment_ids.pop())
        carla_count = await connection.fetchval(
            """
            SELECT count(*)
            FROM acquisition_assignment
            WHERE action_id = $1
              AND twenty_company_id = $2
              AND acquirer_user_id = $3
            """,
            ACTION_ID,
            FREE_COMPANY_ID,
            CARLA_ID,
        )
        carla_history_count = await connection.fetchval(
            """
            SELECT count(*)
            FROM acquisition_assignment_history
            WHERE assignment_id = $1
            """,
            carla_assignment_id,
        )
        if carla_count != 1 or carla_history_count != 1:
            raise ContractFailure("Konkurrenz erzeugte Duplikat oder doppelte Historie")

        bernd = await request(
            api,
            "POST",
            base_path,
            tokens[KLARA_ID],
            "poc060:proactive-bernd",
            {
                "partyKind": "company",
                "partyId": str(FREE_COMPANY_ID),
                "acquirerUserId": str(BERND_ID),
            },
        )
        if bernd.status_code != 201 or bernd.json()["created"] is not True:
            raise ContractFailure("Proaktive Admin-Zuweisung an Bernd fehlgeschlagen")
        bernd_assignment_id = UUID(bernd.json()["assignment"]["id"])
        if bernd_assignment_id == carla_assignment_id:
            raise ContractFailure(
                "Mehrere Akquisiteure teilen fälschlich eine Assignment-ID"
            )

        due_at = datetime(2026, 8, 3, 8, 30, tzinfo=timezone.utc)
        updated = await request(
            api,
            "PATCH",
            f"{base_path}/{carla_assignment_id}",
            tokens[CARLA_ID],
            "poc060:carla-follow-up",
            {
                "revision": 1,
                "status": "contacted",
                "priority": 2,
                "nextAction": "Angebot persönlich nachfassen",
                "dueAt": due_at.isoformat(),
            },
        )
        updated.raise_for_status()
        updated_body = updated.json()
        if (
            updated_body["revision"] != 2
            or updated_body["status"] != "contacted"
            or updated_body["priority"] != 2
            or updated_body["nextAction"] != "Angebot persönlich nachfassen"
            or datetime.fromisoformat(str(updated_body["dueAt"]).replace("Z", "+00:00"))
            != due_at
        ):
            raise ContractFailure("Arbeitsstatus wurde nicht vollständig aktualisiert")

        stale = await request(
            api,
            "PATCH",
            f"{base_path}/{carla_assignment_id}",
            tokens[CARLA_ID],
            "poc060:stale-update",
            {
                "revision": 1,
                "status": "declined",
                "priority": 0,
                "nextAction": None,
                "dueAt": None,
            },
        )
        if (
            stale.status_code != 409
            or error_code(stale) != "assignment_revision_conflict"
        ):
            raise ContractFailure("Veraltete Zuordnungsrevision wurde akzeptiert")

        details = await request(
            api,
            "GET",
            f"{base_path}/{carla_assignment_id}",
            tokens[CARLA_ID],
            "poc060:carla-details",
        )
        details.raise_for_status()
        history = details.json()["history"]
        if (
            len(history) != 2
            or history[0]["changedByDisplayName"] != "Klara Kern"
            or history[1]["changedByDisplayName"] != "Carla Club"
            or history[1]["previousState"]["status"] != "open"
            or history[1]["newState"]["status"] != "contacted"
        ):
            raise ContractFailure("Zuweisungs- und Statushistorie ist unvollständig")

        handed_over = await request(
            api,
            "POST",
            f"{base_path}/{carla_assignment_id}/handover",
            tokens[CARLA_ID],
            "poc060:carla-to-anna",
            {
                "revision": 2,
                "targetAcquirerUserId": str(ANNA_ID),
            },
        )
        handed_over.raise_for_status()
        handover_body = handed_over.json()
        if (
            handover_body["source"]["status"] != "handed_over"
            or handover_body["source"]["revision"] != 3
            or handover_body["target"]["acquirerDisplayName"] != "Anna Akquise"
            or handover_body["target"]["status"] != "open"
            or handover_body["target"]["priority"] != 2
            or handover_body["target"]["nextAction"] != "Angebot persönlich nachfassen"
            or handover_body["targetCreated"] is not True
        ):
            raise ContractFailure(
                "Übergabe bewahrt Verantwortung und Wiedervorlage nicht"
            )
        anna_assignment_id = UUID(handover_body["target"]["id"])

        concealed = await request(
            api,
            "GET",
            f"{base_path}/{carla_assignment_id}",
            tokens[CARLA_ID],
            "poc060:old-owner-concealed",
        )
        if concealed.status_code != 404:
            raise ContractFailure(
                "Übergebene Zuordnung blieb für alte Persona sichtbar"
            )

        admin_details = await request(
            api,
            "GET",
            f"{base_path}/{carla_assignment_id}",
            tokens[KLARA_ID],
            "poc060:admin-history",
        )
        admin_details.raise_for_status()
        if len(admin_details.json()["history"]) != 3:
            raise ContractFailure("Übergabe fehlt in der Ausgangshistorie")

        preview = await request(
            api,
            "POST",
            f"/api/v1/actions/{ACTION_ID}/acquisition/sponsor-match",
            tokens[ANNA_ID],
            "poc060:shared-preview",
            {"companyName": "Freie Firma e.K."},
        )
        preview.raise_for_status()
        names = {
            item["displayName"]
            for item in preview.json()["candidates"][0]["assignedAcquirers"]
        }
        if names != {"Anna Akquise", "Bernd Binder"}:
            raise ContractFailure(
                f"Aktive Mitzuordnung zeigt falsche Namen: {sorted(names)}"
            )

        rows = await connection.fetch(
            """
            SELECT id, acquirer_user_id, status
            FROM acquisition_assignment
            WHERE action_id = $1
              AND twenty_company_id = $2
            ORDER BY acquirer_user_id
            """,
            ACTION_ID,
            FREE_COMPANY_ID,
        )
        if (
            len(rows) != 3
            or {row["acquirer_user_id"] for row in rows}
            != {ANNA_ID, BERND_ID, CARLA_ID}
            or sum(str(row["status"]) != "handed_over" for row in rows) != 2
        ):
            raise ContractFailure(
                "Mehrfachzuordnung oder Übergabestatus ist inkonsistent"
            )
        target_history = await connection.fetchval(
            """
            SELECT count(*)
            FROM acquisition_assignment_history
            WHERE assignment_id = $1
            """,
            anna_assignment_id,
        )
        if target_history != 1:
            raise ContractFailure("Übergabe-Ziel besitzt keine initiale Historie")

        audit_count = await connection.fetchval(
            """
            SELECT count(*)
            FROM audit_event
            WHERE request_id = ANY($1::text[])
            """,
            [
                "poc060:concurrent-carla-a",
                "poc060:concurrent-carla-b",
                "poc060:proactive-bernd",
                "poc060:carla-follow-up",
                "poc060:carla-to-anna",
            ],
        )
        if audit_count != 4:
            raise ContractFailure(
                "Idempotente Zuweisungen/Aktualisierungen sind falsch auditiert"
            )

        print(
            "assignment-contract: OK:",
            "Konkurrenz, Mehrfachzuordnung, Admin-Zuweisung, Arbeitsstatus,",
            "Revision, Übergabe, Sichtentzug, Historie und Audit bewiesen",
        )


async def main() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"))
    try:
        await exercise(connection)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
