#!/usr/bin/env python3
"""Real PostgreSQL/Twenty negative contract for POC-043."""

from __future__ import annotations

import asyncio
import json
import os
import sys
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

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
FOREIGN_ACTION_ID = UUID("20000000-0000-4000-8000-000000000003")
UNKNOWN_ACTION_ID = UUID("20000000-0000-4000-8000-ffffffffffff")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
BERND_ID = UUID("10000000-0000-4000-8000-000000000005")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
SYSTEM_ID = UUID("10000000-0000-4000-8000-000000000001")
COMPANY_ANNA = UUID("40000000-0000-4000-8000-000000000001")
COMPANY_BERND = UUID("40000000-0000-4000-8000-000000000002")
COMPANY_SHARED = UUID("40000000-0000-4000-8000-000000000003")
UNKNOWN_COMPANY = UUID("40000000-0000-4000-8000-ffffffffffff")
ANNA_DOCUMENT = UUID("90000000-0000-4000-8000-000000000002")
BERND_DOCUMENT = UUID("90000000-0000-4000-8000-000000000003")
UNKNOWN_DOCUMENT = UUID("90000000-0000-4000-8000-ffffffffffff")
ANNA_ASSIGNMENT = UUID("60000000-0000-4000-8000-000000000001")
ANNA_MEMBERSHIP = UUID("21000000-0000-4000-8000-000000000004")
SESSION_NAMESPACE = UUID("a136587a-0e5d-4caa-a7a0-1ea60e177e25")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def load_dataset(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractFailure("Golden Dataset ist kein JSON-Objekt")
    return value


def token_for(user_id: UUID) -> str:
    return f"poc043-{user_id}-server-session-token-value"


async def seed_sessions(connection: asyncpg.Connection[Any]) -> dict[UUID, str]:
    now = datetime.now(timezone.utc)
    users = (SYSTEM_ID, KLARA_ID, ANNA_ID, BERND_ID)
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


def error_signature(response: httpx.Response) -> tuple[int, str, str]:
    payload = response.json()
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Fehlervertrag")
    return response.status_code, str(error.get("code")), str(error.get("message"))


def item_ids(payload: dict[str, Any]) -> set[UUID]:
    return {UUID(str(item["twentyId"])) for item in payload["items"]}


async def get(
    client: httpx.AsyncClient,
    path: str,
    token: str,
    *,
    params: dict[str, str | int] | None = None,
) -> httpx.Response:
    return await client.get(
        path,
        params=params,
        cookies={SESSION_COOKIE_NAME: token},
        headers={"X-Request-ID": f"poc043:{UUID(int=len(path) + len(token))}"},
    )


async def assert_no_twenty_account() -> None:
    response = httpx.post(
        f"{require_env('TWENTY_BASE_URL').rstrip('/')}/metadata",
        headers={"Origin": require_env("TWENTY_ORIGIN")},
        json={
            "query": (
                "query Check($email: String!) { "
                "checkUserExists(email: $email) { exists } }"
            ),
            "variables": {"email": "anna.akquise@leonaid.invalid"},
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    exists = payload.get("data", {}).get("checkUserExists", {}).get("exists")
    if exists is not False:
        raise ContractFailure("Akquisiteurin besitzt unerwartet ein Twenty-Konto")


async def exercise(
    connection: asyncpg.Connection[Any],
    tokens: dict[UUID, str],
) -> None:
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=30,
    ) as client:
        anna = tokens[ANNA_ID]
        bernd = tokens[BERND_ID]
        klara = tokens[KLARA_ID]
        system = tokens[SYSTEM_ID]
        list_path = f"/api/v1/actions/{ACTION_ID}/acquisition/parties"

        anna_list = await get(client, list_path, anna)
        anna_list.raise_for_status()
        anna_payload = anna_list.json()
        if anna_payload["total"] != 2 or item_ids(anna_payload) != {
            COMPANY_ANNA,
            COMPANY_SHARED,
        }:
            raise ContractFailure("Annas Liste ist nicht exakt zeilenbegrenzt")

        bernd_list = await get(client, list_path, bernd)
        bernd_list.raise_for_status()
        bernd_payload = bernd_list.json()
        if bernd_payload["total"] != 2 or item_ids(bernd_payload) != {
            COMPANY_BERND,
            COMPANY_SHARED,
        }:
            raise ContractFailure("Bernds Liste ist nicht exakt zeilenbegrenzt")

        for admin_token in (klara, system):
            admin_list = await get(client, list_path, admin_token)
            admin_list.raise_for_status()
            if admin_list.json()["total"] != 4:
                raise ContractFailure(
                    "Aktions-/System-Admin sieht nicht alle zugeordneten Partner"
                )

        shared_path = f"{list_path}/company/{COMPANY_SHARED}"
        for token in (anna, bernd):
            shared = await get(client, shared_path, token)
            shared.raise_for_status()
            if set(shared.json()["assignedAcquirerIds"]) != {
                str(ANNA_ID),
                str(BERND_ID),
            }:
                raise ContractFailure("Gemeinsame Zuweisung ist nicht transparent")

        anna_detail = await get(
            client,
            f"{list_path}/company/{COMPANY_ANNA}",
            anna,
        )
        anna_detail.raise_for_status()
        if anna_detail.json()["assignedAcquirerIds"] != [str(ANNA_ID)]:
            raise ContractFailure("Detail enthält aktionsfremde Zuweisungen")

        hidden_detail = await get(
            client,
            f"{list_path}/company/{COMPANY_BERND}",
            anna,
        )
        unknown_detail = await get(
            client,
            f"{list_path}/company/{UNKNOWN_COMPANY}",
            anna,
        )
        if error_signature(hidden_detail) != error_signature(unknown_detail):
            raise ContractFailure("Detailfehler verrät einen verborgenen Datensatz")

        hidden_search = await get(
            client,
            list_path,
            anna,
            params={"q": "Sonnenseite"},
        )
        empty_search = await get(
            client,
            list_path,
            anna,
            params={"q": "gibt-es-nicht"},
        )
        hidden_search.raise_for_status()
        empty_search.raise_for_status()
        if (
            hidden_search.json()["total"] != 0
            or hidden_search.json() != empty_search.json()
        ):
            raise ContractFailure("Suche oder Count verrät die verborgene Firma")

        count = await get(
            client,
            f"{list_path}/count",
            anna,
        )
        count.raise_for_status()
        if count.json() != {"total": 2}:
            raise ContractFailure("Count verwendet nicht denselben Scope")

        first_page = await get(
            client,
            list_path,
            anna,
            params={"offset": 0, "limit": 1},
        )
        second_page = await get(
            client,
            list_path,
            anna,
            params={"offset": 1, "limit": 1},
        )
        first_page.raise_for_status()
        second_page.raise_for_status()
        if (
            first_page.json()["total"] != 2
            or second_page.json()["total"] != 2
            or item_ids(first_page.json()) & item_ids(second_page.json())
        ):
            raise ContractFailure("Pagination oder Total ist nicht scope-stabil")

        exported = await get(client, f"{list_path}/export", anna)
        exported.raise_for_status()
        if item_ids(exported.json()) != {COMPANY_ANNA, COMPANY_SHARED}:
            raise ContractFailure("Export umgeht den Zeilen-Scope")

        manipulated = await get(
            client,
            list_path,
            anna,
            params={"assigneeId": str(BERND_ID)},
        )
        if error_signature(manipulated)[:2] != (422, "request_invalid"):
            raise ContractFailure("Manipulierte Assignee-ID wurde nicht abgewiesen")

        foreign = await get(
            client,
            f"/api/v1/actions/{FOREIGN_ACTION_ID}/acquisition/parties",
            anna,
        )
        unknown_action = await get(
            client,
            f"/api/v1/actions/{UNKNOWN_ACTION_ID}/acquisition/parties",
            anna,
        )
        if error_signature(foreign) != error_signature(unknown_action):
            raise ContractFailure("Aktionsfehler verrät eine fremde Aktion")

        activities = await get(
            client,
            f"/api/v1/actions/{ACTION_ID}/acquisition/activities",
            anna,
        )
        activities.raise_for_status()
        activity_ids = {item["id"] for item in activities.json()["items"]}
        if (
            "a0000000-0000-4000-8000-000000000005" in activity_ids
            or activities.json()["total"] != 4
        ):
            raise ContractFailure("Aktivitätsfeed enthält fremde Aktivität")

        hidden_document = await get(
            client,
            (f"/api/v1/actions/{ACTION_ID}/acquisition/documents/{BERND_DOCUMENT}"),
            anna,
        )
        unknown_document = await get(
            client,
            (f"/api/v1/actions/{ACTION_ID}/acquisition/documents/{UNKNOWN_DOCUMENT}"),
            anna,
        )
        if error_signature(hidden_document) != error_signature(unknown_document):
            raise ContractFailure("Dokumentfehler verrät fremde Metadaten")
        visible_document = await get(
            client,
            (f"/api/v1/actions/{ACTION_ID}/acquisition/documents/{ANNA_DOCUMENT}"),
            anna,
        )
        visible_document.raise_for_status()

        removed_assignment = await connection.fetchrow(
            """
            DELETE FROM acquisition_assignment
            WHERE id = $1
            RETURNING
                id, action_id, twenty_company_id, twenty_person_id,
                acquirer_user_id, status, priority, next_action, due_at,
                created_at, updated_at, revision
            """,
            ANNA_ASSIGNMENT,
        )
        if removed_assignment is None:
            raise ContractFailure("Golden Assignment fehlt")
        after_assignment_removal = await get(client, list_path, anna)
        after_assignment_removal.raise_for_status()
        if item_ids(after_assignment_removal.json()) != {COMPANY_SHARED}:
            raise ContractFailure("Assignment-Entzug wirkt nicht ohne Neuanmeldung")
        await connection.execute(
            """
            INSERT INTO acquisition_assignment (
                id, action_id, twenty_company_id, twenty_person_id,
                acquirer_user_id, status, priority, next_action, due_at,
                created_at, updated_at, revision
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
            )
            """,
            *tuple(removed_assignment.values()),
        )

        ended = await connection.fetchval(
            """
            UPDATE action_membership
            SET active_until = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
              AND active_until IS NULL
            RETURNING true
            """,
            ANNA_MEMBERSHIP,
        )
        if ended is not True:
            raise ContractFailure("Golden Membership fehlt")
        after_membership_removal = await get(client, list_path, anna)
        if error_signature(after_membership_removal) != error_signature(unknown_action):
            raise ContractFailure("Membership-Entzug wirkt nicht ohne Neuanmeldung")
        await connection.execute(
            """
            UPDATE action_membership
            SET active_until = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            ANNA_MEMBERSHIP,
        )

        restored = await get(client, list_path, anna)
        restored.raise_for_status()
        if item_ids(restored.json()) != {COMPANY_ANNA, COMPANY_SHARED}:
            raise ContractFailure("Golden Scope ließ sich nicht wiederherstellen")

        bodies = " ".join(
            response.text
            for response in (
                anna_list,
                bernd_list,
                exported,
                activities,
                visible_document,
            )
        )
        if require_env("TWENTY_INTEGRATION_API_KEY") in bodies:
            raise ContractFailure("Twenty-Integrations-Key gelangte in API-Antwort")


async def run(dataset_path: Path) -> None:
    dataset = load_dataset(dataset_path)
    if len(dataset.get("assignments", [])) != 5:
        raise ContractFailure("Golden Dataset enthält nicht fünf Zuweisungen")
    await assert_no_twenty_account()
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        tokens = await seed_sessions(connection)
        await exercise(connection, tokens)
    finally:
        await connection.close()
    print(
        "policy-contract: Listen, Suche, Counts, Export, Aktivität, Dokumente "
        "und Sofortentzug real bewiesen"
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("Nutzung: contract.py DATASET_JSON", file=sys.stderr)
        return 64
    try:
        asyncio.run(run(Path(sys.argv[1])))
    except (ContractFailure, asyncpg.PostgresError, httpx.HTTPError) as error:
        print(f"policy-contract: ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
