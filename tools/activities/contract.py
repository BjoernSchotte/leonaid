#!/usr/bin/env python3
"""Real API/PostgreSQL activity and reminder contract for POC-061."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import asyncpg
import httpx

from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
MUSTERWERK_ID = UUID("40000000-0000-4000-8000-000000000001")
DOPPELKONTAKT_ID = UUID("40000000-0000-4000-8000-000000000003")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
BERND_ID = UUID("10000000-0000-4000-8000-000000000005")
CARLA_ID = UUID("10000000-0000-4000-8000-000000000006")
ANNA_MUSTERWERK_ASSIGNMENT = UUID("60000000-0000-4000-8000-000000000001")
ANNA_DOPPELKONTAKT_ASSIGNMENT = UUID("60000000-0000-4000-8000-000000000003")
SESSION_NAMESPACE = UUID("e1b83888-86bb-485a-9d05-5803851e5961")
BERLIN = ZoneInfo("Europe/Berlin")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(user_id: UUID) -> str:
    return f"poc061-{user_id}-server-session-token-value"


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
        headers={
            "Cookie": f"{SESSION_COOKIE_NAME}={token}",
            "X-Request-ID": request_id,
        },
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
    board_path = f"/api/v1/actions/{ACTION_ID}/acquisition/activity-board"
    activity_path = f"/api/v1/actions/{ACTION_ID}/acquisition/activities"
    today = datetime.now(BERLIN).date()
    yesterday = today - timedelta(days=1)

    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        initial = await request(
            api,
            "GET",
            board_path,
            tokens[ANNA_ID],
            "poc061:initial-board",
        )
        initial.raise_for_status()
        initial_body = initial.json()
        initial_names = {item["partyDisplayName"] for item in initial_body["workItems"]}
        if initial_names != {"Musterwerk GmbH", "Doppelkontakt AG"}:
            raise ContractFailure(
                f"Annas Arbeitsvorrat ist falsch: {sorted(initial_names)}"
            )

        overdue = await request(
            api,
            "POST",
            activity_path,
            tokens[ANNA_ID],
            "poc061:overdue-musterwerk",
            {
                "partyKind": "company",
                "partyId": str(MUSTERWERK_ID),
                "revision": 1,
                "channel": "phone",
                "outcome": "interested",
                "note": "  Einkauf möchte   das Angebot.\n\nKeine sensiblen Angaben.  ",
                "nextAction": "  Angebot per E-Mail senden ",
                "dueOn": yesterday.isoformat(),
            },
        )
        overdue.raise_for_status()
        overdue_body = overdue.json()
        if (
            overdue_body["assignment"]["revision"] != 2
            or overdue_body["assignment"]["status"] != "contacted"
            or overdue_body["activity"]["note"]
            != "Einkauf möchte das Angebot.\n\nKeine sensiblen Angaben."
            or overdue_body["activity"]["nextAction"] != "Angebot per E-Mail senden"
            or overdue_body["activity"]["assignmentRevision"] != 2
        ):
            raise ContractFailure("Überfällige Aktivität wurde nicht normalisiert")

        today_activity = await request(
            api,
            "POST",
            activity_path,
            tokens[ANNA_ID],
            "poc061:today-doppelkontakt",
            {
                "partyKind": "company",
                "partyId": str(DOPPELKONTAKT_ID),
                "revision": 1,
                "channel": "email",
                "outcome": "follow_up",
                "note": "Rückmeldung nach interner Abstimmung angekündigt.",
                "nextAction": "Rückmeldung telefonisch einholen",
                "dueOn": today.isoformat(),
            },
        )
        today_activity.raise_for_status()

        stale = await request(
            api,
            "POST",
            activity_path,
            tokens[ANNA_ID],
            "poc061:stale-revision",
            {
                "partyKind": "company",
                "partyId": str(MUSTERWERK_ID),
                "revision": 1,
                "channel": "phone",
                "outcome": "reached",
                "note": None,
                "nextAction": None,
                "dueOn": None,
            },
        )
        if (
            stale.status_code != 409
            or error_code(stale) != "assignment_revision_conflict"
        ):
            raise ContractFailure("Veraltete Aktivitätsrevision wurde akzeptiert")

        incomplete = await request(
            api,
            "POST",
            activity_path,
            tokens[ANNA_ID],
            "poc061:incomplete-reminder",
            {
                "partyKind": "company",
                "partyId": str(MUSTERWERK_ID),
                "revision": 2,
                "channel": "phone",
                "outcome": "reached",
                "note": None,
                "nextAction": "Nachfassen",
                "dueOn": None,
            },
        )
        if incomplete.status_code != 422:
            raise ContractFailure("Unvollständige Wiedervorlage wurde akzeptiert")

        board = await request(
            api,
            "GET",
            board_path,
            tokens[ANNA_ID],
            "poc061:prioritized-board",
        )
        board.raise_for_status()
        board_body = board.json()
        items = board_body["workItems"]
        if [item["partyDisplayName"] for item in items[:2]] != [
            "Musterwerk GmbH",
            "Doppelkontakt AG",
        ] or [item["urgency"] for item in items[:2]] != ["overdue", "today"]:
            raise ContractFailure(
                "Überfällige/heutige Wiedervorlagen sind falsch sortiert"
            )
        activities = board_body["activities"]
        if (
            len(activities) != 2
            or activities[0]["partyDisplayName"] != "Doppelkontakt AG"
            or activities[1]["partyDisplayName"] != "Musterwerk GmbH"
            or activities[0]["actorDisplayName"] != "Anna Akquise"
        ):
            raise ContractFailure("Append-only Aktivitätsverlauf ist falsch sortiert")

        shared = await request(
            api,
            "GET",
            board_path,
            tokens[BERND_ID],
            "poc061:shared-history",
        )
        shared.raise_for_status()
        shared_activities = shared.json()["activities"]
        if (
            len(shared_activities) != 1
            or shared_activities[0]["partyDisplayName"] != "Doppelkontakt AG"
            or shared_activities[0]["actorDisplayName"] != "Anna Akquise"
        ):
            raise ContractFailure("Mitzugeordneter sieht gemeinsamen Verlauf nicht")

        concealed = await request(
            api,
            "GET",
            board_path,
            tokens[CARLA_ID],
            "poc061:foreign-history",
        )
        concealed.raise_for_status()
        if concealed.json()["activities"]:
            raise ContractFailure("Fremde Persona sieht Annas Aktivitäten")

        admin_forbidden = await request(
            api,
            "GET",
            board_path,
            tokens[KLARA_ID],
            "poc061:admin-not-acquirer",
        )
        if (
            admin_forbidden.status_code != 403
            or error_code(admin_forbidden) != "acquirer_required"
        ):
            raise ContractFailure("Charity-Admin erhielt Akquisiteur-Arbeitsvorrat")

        database_rows = await connection.fetch(
            """
            SELECT
                activity.id,
                activity.assignment_id,
                activity.assignment_revision,
                activity.note,
                activity.next_action_snapshot,
                activity.due_at_snapshot,
                audit.id AS audit_id,
                audit.payload,
                history.id AS history_id
            FROM acquisition_activity AS activity
            JOIN audit_event AS audit
              ON audit.entity_type = 'acquisition_activity'
             AND audit.entity_id = activity.id
             AND audit.event_type = 'acquisition_activity_recorded'
            JOIN acquisition_assignment_history AS history
              ON history.assignment_id = activity.assignment_id
             AND history.changed_at = activity.occurred_at
            WHERE activity.id = ANY($1::uuid[])
            ORDER BY activity.occurred_at
            """,
            [
                UUID(overdue_body["activity"]["id"]),
                UUID(today_activity.json()["activity"]["id"]),
            ],
        )
        if len(database_rows) != 2:
            raise ContractFailure(
                "Aktivität, AuditEvent und Historie wurden nicht atomar geschrieben"
            )
        for row in database_rows:
            payload = (
                json.loads(row["payload"])
                if isinstance(row["payload"], str)
                else row["payload"]
            )
            if (
                int(row["assignment_revision"]) != 2
                or row["audit_id"] is None
                or row["history_id"] is None
                or not isinstance(payload, dict)
                or "note" in payload
                or int(payload.get("noteLength", -1)) < 0
            ):
                raise ContractFailure("Audit enthält falsche oder sensible Nutzdaten")

        history_counts = await connection.fetch(
            """
            SELECT assignment_id, count(*) AS entries
            FROM acquisition_assignment_history
            WHERE assignment_id = ANY($1::uuid[])
            GROUP BY assignment_id
            ORDER BY assignment_id
            """,
            [ANNA_MUSTERWERK_ASSIGNMENT, ANNA_DOPPELKONTAKT_ASSIGNMENT],
        )
        if len(history_counts) != 2 or any(
            int(row["entries"]) != 2 for row in history_counts
        ):
            raise ContractFailure("Aktivitäten überschreiben statt Historie anzuhängen")

        print(
            "activity-contract: OK:",
            "append-only Verlauf, Reminder-Priorität, Mitzuordnung,",
            "Sichtgrenzen, Revision, Historie und Audit atomar bewiesen",
        )


async def main() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"))
    try:
        await exercise(connection)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
