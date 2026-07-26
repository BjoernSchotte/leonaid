#!/usr/bin/env python3
"""Real FastAPI/PostgreSQL contract for the neutral CharityAction core."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import stat
import sys
from datetime import datetime, timezone
from decimal import Decimal
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

KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
FELIX_ID = UUID("10000000-0000-4000-8000-000000000003")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
UNKNOWN_ACTION_ID = UUID("20000000-0000-4000-8000-ffffffffffff")
SESSION_NAMESPACE = UUID("d69948ee-bb22-4eed-ac01-f0d24c067112")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(user_id: UUID) -> str:
    return f"poc050-{user_id}-real-server-session-token"


async def seed_sessions(connection: asyncpg.Connection[Any]) -> dict[UUID, str]:
    now = datetime.now(timezone.utc)
    users = (KLARA_ID, FELIX_ID, ANNA_ID)
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
                id, user_id, token_digest, expires_at, last_seen_at,
                fresh_login_at, created_at, updated_at
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


def cookies(token: str) -> dict[str, str]:
    return {SESSION_COOKIE_NAME: token}


def request_headers(label: str) -> dict[str, str]:
    digest = hashlib.sha256(label.encode()).hexdigest()[:24]
    return {"X-Request-ID": f"poc050:{digest}", "Accept": "application/json"}


def error_signature(response: httpx.Response) -> tuple[int, str, str]:
    payload = response.json()
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Fehlervertrag")
    return response.status_code, str(error.get("code")), str(error.get("message"))


def action_payload(slug: str) -> dict[str, Any]:
    return {
        "carrierName": "Lions Hilfswerk Beispielstadt",
        "name": "Quartalsaktion Frühjahr 2027",
        "purpose": "Förderung lokaler Bildungs- und Freizeitangebote.",
        "startsOn": "2027-02-01",
        "endsOn": "2027-03-31",
        "archiveSlug": slug,
        "capabilities": [
            "acquisition",
            "offerings",
            "ordering",
            "invoicing",
        ],
        "beneficiaries": [
            {
                "organizationName": "Bildungshafen Beispielstadt",
                "publicDescription": "Finanziert Lernmaterial für Kinder.",
            },
            {
                "organizationName": "Freizeitbrücke Musterbogen",
                "publicDescription": "Ermöglicht inklusive Ferienangebote.",
            },
        ],
        "goal": {
            "goalValue": "12500",
            "actualValue": "250.50",
            "unit": "EUR",
            "currency": "EUR",
        },
    }


async def exercise(
    connection: asyncpg.Connection[Any],
    tokens: dict[UUID, str],
) -> UUID:
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=30,
    ) as client:
        anna_forbidden = await client.post(
            "/api/v1/actions",
            cookies=cookies(tokens[ANNA_ID]),
            headers=request_headers("anna-forbidden"),
            json=action_payload("quartalsaktion-anna-verboten"),
        )
        if error_signature(anna_forbidden)[:2] != (
            403,
            "action_creation_forbidden",
        ):
            raise ContractFailure("Akquisiteurin konnte eine Charity-Aktion anlegen")

        invalid = action_payload("quartalsaktion-ungueltig")
        invalid["capabilities"] = ["ordering"]
        invalid_capabilities = await client.post(
            "/api/v1/actions",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("invalid-capabilities"),
            json=invalid,
        )
        if error_signature(invalid_capabilities)[:2] != (
            422,
            "action_capability_dependency_invalid",
        ):
            raise ContractFailure("Capability-Abhängigkeit wurde nicht erzwungen")

        created = await client.post(
            "/api/v1/actions",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("create"),
            json=action_payload("quartalsaktion-fruehjahr-2027"),
        )
        created.raise_for_status()
        body = created.json()
        action_id = UUID(str(body["id"]))
        revision = int(body["revision"])
        if (
            created.status_code != 201
            or created.headers.get("location") != f"/api/v1/actions/{action_id}"
            or body["status"] != "draft"
            or body["goal"]["goalValue"] != "12500"
            or body["goal"]["actualValue"] != "250.5"
            or len(body["beneficiaries"]) != 2
            or set(body["capabilities"])
            != {"acquisition", "offerings", "ordering", "invoicing"}
        ):
            raise ContractFailure("Erstellte Charity-Aktion ist nicht vollständig")

        duplicate_slug = await client.post(
            "/api/v1/actions",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("duplicate-slug"),
            json=action_payload("quartalsaktion-fruehjahr-2027"),
        )
        if error_signature(duplicate_slug)[:2] != (
            409,
            "action_archive_slug_conflict",
        ):
            raise ContractFailure(
                "Doppelter Archiv-Slug besitzt keinen Konfliktvertrag"
            )

        direct_membership = await connection.fetchval(
            """
            SELECT count(*)
            FROM action_membership
            WHERE action_id = $1
              AND user_id = $2
              AND role = 'charity_admin'
              AND active_until IS NULL
            """,
            action_id,
            KLARA_ID,
        )
        if direct_membership != 1:
            raise ContractFailure("Erstellerin wurde nicht verantwortlich zugeordnet")

        own = await client.get(
            f"/api/v1/actions/{action_id}",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("own-detail"),
        )
        own.raise_for_status()
        foreign = await client.get(
            f"/api/v1/actions/{action_id}",
            cookies=cookies(tokens[FELIX_ID]),
            headers=request_headers("foreign-detail"),
        )
        unknown = await client.get(
            f"/api/v1/actions/{UNKNOWN_ACTION_ID}",
            cookies=cookies(tokens[FELIX_ID]),
            headers=request_headers("unknown-detail"),
        )
        if error_signature(foreign) != error_signature(unknown):
            raise ContractFailure("Fremde Aktion ist anhand des Fehlers erkennbar")

        goal_changed = await client.put(
            f"/api/v1/actions/{action_id}/goal",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("goal-1"),
            json={
                "revision": revision,
                "goalValue": "15000",
                "actualValue": "1000",
                "unit": "EUR",
                "currency": "EUR",
            },
        )
        goal_changed.raise_for_status()
        goal_body = goal_changed.json()
        revision = int(goal_body["revision"])
        if goal_body["goal"]["actualValue"] != "1000":
            raise ContractFailure("Ist-Wert wurde nicht manuell gespeichert")

        capabilities_changed = await client.put(
            f"/api/v1/actions/{action_id}/capabilities",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("capabilities"),
            json={
                "revision": revision,
                "capabilities": ["acquisition", "invoicing"],
            },
        )
        capabilities_changed.raise_for_status()
        capabilities_body = capabilities_changed.json()
        revision = int(capabilities_body["revision"])
        if capabilities_body["capabilities"] != [
            "acquisition",
            "invoicing",
        ]:
            raise ContractFailure("Capabilities wurden nicht typisiert ersetzt")

        beneficiaries_changed = await client.put(
            f"/api/v1/actions/{action_id}/beneficiaries",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("beneficiaries"),
            json={
                "revision": revision,
                "beneficiaries": [
                    {
                        "organizationName": "Bildungshafen Beispielstadt",
                        "publicDescription": "Lernmaterial und Lernräume.",
                    },
                    {
                        "organizationName": "Freizeitbrücke Musterbogen",
                        "publicDescription": "Inklusive Ferienangebote.",
                    },
                    {
                        "organizationName": "Kulturanker Nord",
                        "publicDescription": "Niedrigschwellige Kulturprojekte.",
                    },
                ],
            },
        )
        beneficiaries_changed.raise_for_status()
        beneficiaries_body = beneficiaries_changed.json()
        revision = int(beneficiaries_body["revision"])
        if len(beneficiaries_body["beneficiaries"]) != 3:
            raise ContractFailure("Mehrere Begünstigte wurden nicht gespeichert")

        invalid_transition = await client.post(
            f"/api/v1/actions/{action_id}/transitions",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("invalid-transition"),
            json={"revision": revision, "targetStatus": "active"},
        )
        if error_signature(invalid_transition)[:2] != (
            422,
            "action_status_transition_invalid",
        ):
            raise ContractFailure("Verbotener Lifecycle-Sprung wurde akzeptiert")

        for index, target in enumerate(
            ("scheduled", "draft", "scheduled", "active"),
        ):
            transitioned = await client.post(
                f"/api/v1/actions/{action_id}/transitions",
                cookies=cookies(tokens[KLARA_ID]),
                headers=request_headers(f"transition-{index}-{target}"),
                json={"revision": revision, "targetStatus": target},
            )
            transitioned.raise_for_status()
            transition_body = transitioned.json()
            revision = int(transition_body["revision"])
            if transition_body["status"] != target:
                raise ContractFailure(f"Lifecycle-Ziel {target} wurde nicht erreicht")

        locked_capabilities = await client.put(
            f"/api/v1/actions/{action_id}/capabilities",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("locked-capabilities"),
            json={"revision": revision, "capabilities": ["acquisition"]},
        )
        if error_signature(locked_capabilities)[:2] != (
            422,
            "action_capabilities_locked",
        ):
            raise ContractFailure("Aktive Capabilities waren unerwartet veränderbar")

        active_goal = await client.put(
            f"/api/v1/actions/{action_id}/goal",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("goal-active"),
            json={
                "revision": revision,
                "goalValue": "15000",
                "actualValue": "1500",
                "unit": "EUR",
                "currency": "EUR",
            },
        )
        active_goal.raise_for_status()
        revision = int(active_goal.json()["revision"])

        for target in ("completed", "archived"):
            transitioned = await client.post(
                f"/api/v1/actions/{action_id}/transitions",
                cookies=cookies(tokens[KLARA_ID]),
                headers=request_headers(f"transition-{target}"),
                json={"revision": revision, "targetStatus": target},
            )
            transitioned.raise_for_status()
            revision = int(transitioned.json()["revision"])

        archived_goal = await client.put(
            f"/api/v1/actions/{action_id}/goal",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("archived-goal"),
            json={
                "revision": revision,
                "goalValue": "15000",
                "actualValue": "1600",
                "unit": "EUR",
                "currency": "EUR",
            },
        )
        if error_signature(archived_goal)[:2] != (
            422,
            "action_archived_immutable",
        ):
            raise ContractFailure("Archivierte Aktion war noch veränderbar")

        persisted = await connection.fetchrow(
            """
            SELECT
                action.status,
                action.goal_value,
                action.actual_value,
                action.goal_unit,
                (SELECT count(*) FROM beneficiary WHERE action_id = action.id)
                    AS beneficiary_count,
                (
                    SELECT array_agg(capability ORDER BY capability)
                    FROM charity_action_capability
                    WHERE action_id = action.id
                ) AS capabilities,
                (
                    SELECT count(*)
                    FROM audit_event
                    WHERE action_id = action.id
                      AND entity_type = 'charity_action'
                ) AS audit_count
            FROM charity_action AS action
            WHERE action.id = $1
            """,
            action_id,
        )
        if (
            persisted is None
            or persisted["status"] != "archived"
            or Decimal(persisted["goal_value"]) != Decimal("15000")
            or Decimal(persisted["actual_value"]) != Decimal("1500")
            or persisted["goal_unit"] != "EUR"
            or persisted["beneficiary_count"] != 3
            or persisted["capabilities"] != ["acquisition", "invoicing"]
            or persisted["audit_count"] != 11
        ):
            raise ContractFailure("PostgreSQL-Snapshot oder Audit ist unvollständig")

        return action_id


def write_session(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(f"KLARA_SESSION={token}\n")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ContractFailure("Sitzungsnachweis besitzt nicht Dateimodus 0600")


async def run(session_output: Path) -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        tokens = await seed_sessions(connection)
        await exercise(connection, tokens)
        write_session(session_output, tokens[KLARA_ID])
    finally:
        await connection.close()
    print(
        "action-contract: neutraler Kern, 1-n Begünstigte, Ziele, Capabilities, "
        "Lifecycle und Audit real bewiesen"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        asyncio.run(run(arguments.session_output))
    except (ContractFailure, asyncpg.PostgresError, httpx.HTTPError) as error:
        print(f"action-contract: ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
