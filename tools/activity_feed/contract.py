#!/usr/bin/env python3
"""Real API/PostgreSQL/Twenty contract for the POC-082 activity feed."""

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
from tools.public_orders.contract import (
    order_body,
    public_context,
    submit,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
MUSTERWERK_ID = UUID("40000000-0000-4000-8000-000000000001")
DOPPELKONTAKT_ID = UUID("40000000-0000-4000-8000-000000000003")
FREIE_FIRMA_ID = UUID("40000000-0000-4000-8000-000000000004")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
BERND_ID = UUID("10000000-0000-4000-8000-000000000005")
CARLA_ID = UUID("10000000-0000-4000-8000-000000000006")
ANNA_MUSTERWERK_ASSIGNMENT = UUID("60000000-0000-4000-8000-000000000001")
ANNA_DOPPELKONTAKT_ASSIGNMENT = UUID("60000000-0000-4000-8000-000000000003")
BERND_DOPPELKONTAKT_ASSIGNMENT = UUID("60000000-0000-4000-8000-000000000004")
SESSION_NAMESPACE = UUID("f49153f8-2f23-4cff-8291-8cb768a71fc8")
COMMAND_NAMESPACE = UUID("5f480ad8-163c-45e7-838a-5d306980e06d")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(user_id: UUID) -> str:
    return f"poc082-{user_id}-server-session-token-value"


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


async def authenticated_request(
    api: httpx.AsyncClient,
    method: str,
    path: str,
    token: str,
    request_id: str,
    body: Mapping[str, object] | None = None,
) -> httpx.Response:
    return await api.request(
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


def feed_items(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ContractFailure("Feed-Antwort ist kein Objekt")
    items = payload.get("items")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ContractFailure("Feed-Antwort besitzt keine gültigen Einträge")
    return items


async def create_order(
    api: httpx.AsyncClient,
    *,
    token: str,
    label: str,
    company_name: str,
    given_name: str,
    family_name: str,
    email: str,
    quantity: int,
    forwarded_for: str,
) -> UUID:
    response = await submit(
        api,
        order_body(
            token=token,
            command=uuid5(COMMAND_NAMESPACE, label),
            company_name=company_name,
            given_name=given_name,
            family_name=family_name,
            email=email,
            quantity=quantity,
        ),
        label=f"poc082-{label}",
        forwarded_for=forwarded_for,
    )
    if response.status_code != 201:
        raise ContractFailure(
            f"Öffentliche Bestellung {label} scheiterte: "
            f"{response.status_code} {response.text}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise ContractFailure("Bestellantwort ist kein Objekt")
    return UUID(str(payload["commitmentId"]))


async def assert_recipients(
    connection: asyncpg.Connection[Any],
    *,
    commitment_id: UUID,
    party_id: UUID,
    expected_recipients: set[UUID],
) -> UUID:
    event = await connection.fetchrow(
        """
        SELECT id, action_id, twenty_company_id, twenty_person_id
        FROM activity_event
        WHERE event_type = 'public_order_received'
          AND payload ->> 'commitmentId' = $1
        """,
        str(commitment_id),
    )
    if (
        event is None
        or event["action_id"] != ACTION_ID
        or event["twenty_company_id"] != party_id
        or event["twenty_person_id"] is not None
    ):
        raise ContractFailure(
            "ActivityEvent referenziert Aktion oder CRM-Partei falsch"
        )
    recipients = await connection.fetch(
        """
        SELECT user_id, read_at
        FROM activity_event_recipient
        WHERE activity_event_id = $1
        ORDER BY user_id
        """,
        event["id"],
    )
    if {row["user_id"] for row in recipients} != expected_recipients or any(
        row["read_at"] is not None for row in recipients
    ):
        raise ContractFailure("ActivityEvent-Empfänger sind nicht fachlich exakt")
    return UUID(str(event["id"]))


def assert_feed_item(
    item: Mapping[str, Any],
    *,
    party_id: UUID,
    assignment_id: UUID | None,
    admin: bool = False,
) -> None:
    href = str(item.get("nextActionHref"))
    expected_href = (
        f"/admin/orders?commitment={item.get('commitmentId')}"
        if admin
        else f"/app/activities?view=contacts&assignment={assignment_id}"
    )
    if (
        item.get("actionId") != str(ACTION_ID)
        or item.get("actionName") != "Krapfentaxi 2026"
        or item.get("eventType") != "public_order_received"
        or item.get("partyKind") != "company"
        or item.get("partyId") != str(party_id)
        or not isinstance(item.get("partyDisplayName"), str)
        or not str(item.get("partyDisplayName")).strip()
        or item.get("isRead") is not False
        or item.get("readAt") is not None
        or item.get("totalBoxes") not in {1, 2, 3}
        or int(item.get("totalPieces", -1)) != int(item["totalBoxes"]) * 24
        or item.get("currency") != "EUR"
        or href != expected_href
        or (admin and item.get("nextActionLabel") != "Bestellung prüfen und zuordnen")
        or (
            not admin
            and item.get("nextActionLabel") != "Kontakt und Bestellung abstimmen"
        )
    ):
        raise ContractFailure("Feed-Eintrag erklärt Referenz oder Folgeaktion falsch")


async def get_feed(
    api: httpx.AsyncClient,
    *,
    token: str,
    label: str,
    status: str = "all",
) -> dict[str, Any]:
    response = await authenticated_request(
        api,
        "GET",
        f"/api/v1/activity-feed?status={status}&limit=50&offset=0",
        token,
        f"poc082:{label}",
    )
    response.raise_for_status()
    if response.headers.get("cache-control") != "private, no-store":
        raise ContractFailure("Persönlicher Feed ist cachebar")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ContractFailure("Feed-Antwort ist kein Objekt")
    return payload


async def exercise(connection: asyncpg.Connection[Any]) -> None:
    tokens = await seed_sessions(connection)
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        form_token, _offering = await public_context(api)
        exclusive_commitment = await create_order(
            api,
            token=form_token,
            label="exclusive",
            company_name="Musterwerk GmbH",
            given_name="Mara",
            family_name="Muster",
            email="mara.muster@musterwerk.leonaid.invalid",
            quantity=1,
            forwarded_for="203.0.113.82",
        )
        shared_commitment = await create_order(
            api,
            token=form_token,
            label="shared",
            company_name="Doppelkontakt AG",
            given_name="Petra",
            family_name="Partner",
            email="petra.partner@doppelkontakt.leonaid.invalid",
            quantity=2,
            forwarded_for="203.0.113.83",
        )
        unassigned_commitment = await create_order(
            api,
            token=form_token,
            label="unassigned",
            company_name="Freie Firma e.K.",
            given_name="Frieda",
            family_name="Frei",
            email="frieda.frei@freie-firma.leonaid.invalid",
            quantity=3,
            forwarded_for="203.0.113.84",
        )

        exclusive_event = await assert_recipients(
            connection,
            commitment_id=exclusive_commitment,
            party_id=MUSTERWERK_ID,
            expected_recipients={ANNA_ID},
        )
        await assert_recipients(
            connection,
            commitment_id=shared_commitment,
            party_id=DOPPELKONTAKT_ID,
            expected_recipients={ANNA_ID, BERND_ID},
        )
        await assert_recipients(
            connection,
            commitment_id=unassigned_commitment,
            party_id=FREIE_FIRMA_ID,
            expected_recipients={KLARA_ID},
        )

        anna = await get_feed(api, token=tokens[ANNA_ID], label="anna")
        anna_items = feed_items(anna)
        if (
            anna.get("total") != 2
            or anna.get("unreadCount") != 2
            or len(anna_items) != 2
        ):
            raise ContractFailure("Exklusive und gemeinsame Feed-Sicht für Anna fehlt")
        anna_by_party = {item["partyId"]: item for item in anna_items}
        assert_feed_item(
            anna_by_party[str(MUSTERWERK_ID)],
            party_id=MUSTERWERK_ID,
            assignment_id=ANNA_MUSTERWERK_ASSIGNMENT,
        )
        assert_feed_item(
            anna_by_party[str(DOPPELKONTAKT_ID)],
            party_id=DOPPELKONTAKT_ID,
            assignment_id=ANNA_DOPPELKONTAKT_ASSIGNMENT,
        )

        bernd = await get_feed(api, token=tokens[BERND_ID], label="bernd")
        bernd_items = feed_items(bernd)
        if (
            bernd.get("total") != 1
            or bernd.get("unreadCount") != 1
            or len(bernd_items) != 1
        ):
            raise ContractFailure("Gemeinsame Feed-Sicht für Bernd fehlt")
        assert_feed_item(
            bernd_items[0],
            party_id=DOPPELKONTAKT_ID,
            assignment_id=BERND_DOPPELKONTAKT_ASSIGNMENT,
        )

        klara = await get_feed(api, token=tokens[KLARA_ID], label="klara")
        klara_items = feed_items(klara)
        if (
            klara.get("total") != 1
            or klara.get("unreadCount") != 1
            or len(klara_items) != 1
        ):
            raise ContractFailure("Unzugeordnete Bestellung fehlt im Admin-Feed")
        assert_feed_item(
            klara_items[0],
            party_id=FREIE_FIRMA_ID,
            assignment_id=None,
            admin=True,
        )

        carla = await get_feed(api, token=tokens[CARLA_ID], label="carla")
        if carla.get("total") != 0 or feed_items(carla):
            raise ContractFailure("Fremder Akquisiteur sieht Feed-Einträge")

        marked = await authenticated_request(
            api,
            "PATCH",
            f"/api/v1/activity-feed/{exclusive_event}",
            tokens[ANNA_ID],
            "poc082:mark-read",
            {"read": True},
        )
        marked.raise_for_status()
        if marked.json().get("isRead") is not True or not marked.json().get("readAt"):
            raise ContractFailure("Gelesen-Status wurde nicht gespeichert")
        unread = await get_feed(
            api,
            token=tokens[ANNA_ID],
            label="anna-unread",
            status="unread",
        )
        unread_items = feed_items(unread)
        if (
            unread.get("total") != 2
            or unread.get("unreadCount") != 1
            or len(unread_items) != 1
            or unread_items[0].get("partyId") != str(DOPPELKONTAKT_ID)
        ):
            raise ContractFailure("Ungelesen-Filter oder Zähler ist falsch")

        concealed = await authenticated_request(
            api,
            "PATCH",
            f"/api/v1/activity-feed/{exclusive_event}",
            tokens[CARLA_ID],
            "poc082:foreign-write",
            {"read": True},
        )
        if concealed.status_code != 404 or error_code(concealed) != (
            "resource_not_found"
        ):
            raise ContractFailure("Fremder Feed-Eintrag ist nicht verborgen")

        reset = await authenticated_request(
            api,
            "PATCH",
            f"/api/v1/activity-feed/{exclusive_event}",
            tokens[ANNA_ID],
            "poc082:mark-unread",
            {"read": False},
        )
        reset.raise_for_status()
        if (
            reset.json().get("isRead") is not False
            or reset.json().get("readAt") is not None
        ):
            raise ContractFailure("Ungelesen-Status wurde nicht wiederhergestellt")

        event_count = await connection.fetchval(
            """
            SELECT count(*)
            FROM activity_event
            WHERE event_type = 'public_order_received'
              AND payload ->> 'commitmentId' = ANY($1::text[])
            """,
            [
                str(exclusive_commitment),
                str(shared_commitment),
                str(unassigned_commitment),
            ],
        )
        if int(event_count) != 3:
            raise ContractFailure("Lesestatus hat ActivityEvents gelöscht")

    print(
        "activity-feed-contract: OK:",
        "exklusiv, gemeinsam und unzugeordnet adressiert;",
        "gelesen/ungelesen sowie Fremdzugriff real bewiesen",
    )


async def main() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        await exercise(connection)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
