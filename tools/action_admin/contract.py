#!/usr/bin/env python3
"""Real FastAPI/PostgreSQL contract for Charity-Admin action management."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
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

KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
FELIX_ID = UUID("10000000-0000-4000-8000-000000000003")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
GESA_ID = UUID("10000000-0000-4000-8000-000000000008")
KLARA_ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
FELIX_ACTION_ID = UUID("20000000-0000-4000-8000-000000000003")
UNKNOWN_ACTION_ID = UUID("20000000-0000-4000-8000-ffffffffffff")
SESSION_NAMESPACE = UUID("3345e584-98be-4017-a4d5-b6cd91e48908")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(user_id: UUID) -> str:
    return f"poc052-{user_id}-real-server-session-token"


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
    return {"X-Request-ID": f"poc052:{digest}", "Accept": "application/json"}


def error_signature(response: httpx.Response) -> tuple[int, str, str]:
    payload = response.json()
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Fehlervertrag")
    return response.status_code, str(error.get("code")), str(error.get("message"))


def creation_payload() -> dict[str, Any]:
    return {
        "templateKey": "krapfentaxi",
        "templateVersion": 1,
        "carrierName": "Lions Hilfswerk Beispielstadt",
        "name": "Krapfentaxi 2027",
        "purpose": "Krapfen bestellen und lokale Bildungsprojekte unterstützen.",
        "startsOn": "2027-09-01",
        "endsOn": "2027-11-15",
        "archiveSlug": "krapfentaxi-2027",
        "beneficiaries": [
            {
                "organizationName": "Bildungshafen Beispielstadt",
                "publicDescription": "Finanziert Lernmaterial für Kinder.",
            }
        ],
        "goal": {
            "goalValue": "1500",
            "actualValue": "0",
            "unit": "Boxen",
            "currency": None,
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
        created = await client.post(
            "/api/v1/actions/from-template",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("create"),
            json=creation_payload(),
        )
        created.raise_for_status()
        action = created.json()["action"]
        action_id = UUID(str(action["id"]))
        revision = int(action["revision"])
        if revision != 1:
            raise ContractFailure("Neue Aktion beginnt nicht mit Revision 1")

        own = await client.get(
            f"/api/v1/actions/{action_id}/management",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("management-own"),
        )
        own.raise_for_status()
        management = own.json()
        responsible = {
            item["userId"]
            for item in management["administratorOptions"]
            if item["isResponsible"]
        }
        if (
            management["publicAlias"] is not None
            or responsible != {str(KLARA_ID)}
            or management["allowedTransitions"] != ["scheduled"]
            or not any(
                item["userId"] == str(FELIX_ID) and item["isAvailable"]
                for item in management["administratorOptions"]
            )
        ):
            raise ContractFailure("Management-Sicht ist nicht vollständig")

        foreign = await client.get(
            f"/api/v1/actions/{action_id}/management",
            cookies=cookies(tokens[ANNA_ID]),
            headers=request_headers("management-foreign"),
        )
        unknown = await client.get(
            f"/api/v1/actions/{UNKNOWN_ACTION_ID}/management",
            cookies=cookies(tokens[ANNA_ID]),
            headers=request_headers("management-unknown"),
        )
        if error_signature(foreign) != error_signature(unknown):
            raise ContractFailure("Fremde Aktionsverwaltung ist erkennbar")

        details_payload = {
            "revision": revision,
            "carrierName": "Lions Hilfswerk Beispielstadt e. V.",
            "name": "Krapfentaxi Beispielstadt 2027",
            "purpose": "Gemeinsam Krapfen bestellen und zwei Lernorte fördern.",
            "startsOn": "2027-09-02",
            "endsOn": "2027-11-16",
        }
        details = await client.put(
            f"/api/v1/actions/{action_id}/details",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("details"),
            json=details_payload,
        )
        details.raise_for_status()
        revision = int(details.json()["revision"])
        if revision != 2 or details.json()["name"] != details_payload["name"]:
            raise ContractFailure("Grunddaten oder Revision wurden nicht gespeichert")

        idempotent_retry = await client.put(
            f"/api/v1/actions/{action_id}/details",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("details-idempotent"),
            json=details_payload,
        )
        idempotent_retry.raise_for_status()
        if int(idempotent_retry.json()["revision"]) != revision:
            raise ContractFailure("Idempotenter Retry erzeugte eine neue Revision")

        stale = {**details_payload, "name": "Veralteter Browserstand"}
        stale_update = await client.put(
            f"/api/v1/actions/{action_id}/details",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("details-stale"),
            json=stale,
        )
        if error_signature(stale_update)[:2] != (
            409,
            "action_revision_conflict",
        ):
            raise ContractFailure("Veraltete Bearbeitung wurde nicht abgefangen")

        incomplete_publication = await client.put(
            f"/api/v1/actions/{action_id}/publication",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("publication-incomplete"),
            json={
                "revision": revision,
                "publicationStartsAt": "2027-08-01T08:00:00+02:00",
                "publicationEndsAt": None,
                "publicAlias": "krapfentaxi-kommend",
            },
        )
        if error_signature(incomplete_publication)[:2] != (
            422,
            "action_publication_window_incomplete",
        ):
            raise ContractFailure(
                "Unvollständiges Publikationsfenster wurde akzeptiert"
            )

        await connection.execute(
            """
            INSERT INTO public_action_alias (alias, action_id)
            VALUES ('fremde-aktion', $1)
            """,
            FELIX_ACTION_ID,
        )
        unavailable_alias = await client.put(
            f"/api/v1/actions/{action_id}/publication",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("publication-foreign-alias"),
            json={
                "revision": revision,
                "publicationStartsAt": "2027-08-01T08:00:00+02:00",
                "publicationEndsAt": "2027-11-16T23:00:00+01:00",
                "publicAlias": "fremde-aktion",
            },
        )
        if error_signature(unavailable_alias)[:2] != (
            409,
            "action_public_alias_unavailable",
        ):
            raise ContractFailure("Fremder öffentlicher Alias konnte übernommen werden")

        publication = await client.put(
            f"/api/v1/actions/{action_id}/publication",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("publication-switch"),
            json={
                "revision": revision,
                "publicationStartsAt": "2027-08-01T08:00:00+02:00",
                "publicationEndsAt": "2027-11-16T23:00:00+01:00",
                "publicAlias": "krapfentaxi",
            },
        )
        publication.raise_for_status()
        publication_body = publication.json()
        revision = int(publication_body["action"]["revision"])
        if revision != 3 or publication_body["publicAlias"] != "krapfentaxi":
            raise ContractFailure("Publikationsdaten wurden nicht atomar gespeichert")
        alias_target = await connection.fetchval(
            "SELECT action_id FROM public_action_alias WHERE alias = 'krapfentaxi'"
        )
        old_revision = await connection.fetchval(
            "SELECT revision FROM charity_action WHERE id = $1",
            KLARA_ACTION_ID,
        )
        if alias_target != action_id or old_revision != 2:
            raise ContractFailure("Alias wurde nicht nachvollziehbar umgeschaltet")

        unavailable_admin = await client.put(
            f"/api/v1/actions/{action_id}/responsible-administrators",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("responsibles-unavailable"),
            json={"revision": revision, "userIds": [str(KLARA_ID), str(GESA_ID)]},
        )
        if error_signature(unavailable_admin)[:2] != (
            409,
            "action_responsible_administrator_unavailable",
        ):
            raise ContractFailure("Gesperrtes Mitglied wurde verantwortlich")

        responsibles = await client.put(
            f"/api/v1/actions/{action_id}/responsible-administrators",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("responsibles-two"),
            json={"revision": revision, "userIds": [str(KLARA_ID), str(FELIX_ID)]},
        )
        responsibles.raise_for_status()
        revision = int(responsibles.json()["action"]["revision"])
        if revision != 4:
            raise ContractFailure("Verantwortlichenwechsel erhöhte Revision nicht")

        felix_access = await client.get(
            f"/api/v1/actions/{action_id}/management",
            cookies=cookies(tokens[FELIX_ID]),
            headers=request_headers("felix-new-access"),
        )
        felix_access.raise_for_status()

        felix_only = await client.put(
            f"/api/v1/actions/{action_id}/responsible-administrators",
            cookies=cookies(tokens[FELIX_ID]),
            headers=request_headers("responsibles-felix-only"),
            json={"revision": revision, "userIds": [str(FELIX_ID)]},
        )
        felix_only.raise_for_status()
        revision = int(felix_only.json()["action"]["revision"])
        if revision != 5:
            raise ContractFailure("Verantwortlichenhistorie erhielt keine Revision")

        klara_removed = await client.get(
            f"/api/v1/actions/{action_id}/management",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("klara-removed"),
        )
        if error_signature(klara_removed)[:2] != (404, "resource_not_found"):
            raise ContractFailure("Entfernte Verantwortliche behielt Zugriff")

        persisted = await connection.fetchrow(
            """
            SELECT
                action.name,
                action.publication_starts_at,
                action.publication_ends_at,
                action.revision,
                (
                    SELECT count(*)
                    FROM action_membership
                    WHERE action_id = action.id
                      AND role = 'charity_admin'
                      AND active_until IS NULL
                ) AS active_admins,
                (
                    SELECT count(*)
                    FROM action_membership
                    WHERE action_id = action.id
                      AND role = 'charity_admin'
                      AND active_until IS NOT NULL
                ) AS historical_admins,
                (
                    SELECT count(*)
                    FROM audit_event
                    WHERE action_id = action.id
                      AND event_type IN (
                        'charity_action.details_changed',
                        'charity_action.publication_changed',
                        'charity_action.responsibles_changed'
                      )
                ) AS management_audits
            FROM charity_action AS action
            WHERE action.id = $1
            """,
            action_id,
        )
        if (
            persisted is None
            or persisted["name"] != details_payload["name"]
            or persisted["publication_starts_at"] is None
            or persisted["publication_ends_at"] is None
            or persisted["revision"] != 5
            or persisted["active_admins"] != 1
            or persisted["historical_admins"] != 1
            or persisted["management_audits"] != 4
        ):
            raise ContractFailure("Management-Snapshot oder Audit ist unvollständig")
        return action_id


async def run() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        tokens = await seed_sessions(connection)
        await exercise(connection, tokens)
    finally:
        await connection.close()
    print(
        "action-admin-contract: Grunddaten, Revisionen, Publikation, Aliaswechsel "
        "und Verantwortliche real bewiesen"
    )


def main() -> int:
    try:
        asyncio.run(run())
    except (ContractFailure, asyncpg.PostgresError, httpx.HTTPError) as error:
        print(f"action-admin-contract: ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
