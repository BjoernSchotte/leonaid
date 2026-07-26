#!/usr/bin/env python3
"""Real Twenty/PostgreSQL/API contract for the POC-062 PWA."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import httpx
from pydantic import SecretStr

from leonaid.adapters.twenty.gateway import (
    TwentyCrmGateway,
    TwentyGatewaySettings,
)
from leonaid.application.crm import PersonUpdate
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
MARA_ID = UUID("50000000-0000-4000-8000-000000000001")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
BERND_ID = UUID("10000000-0000-4000-8000-000000000005")
CARLA_ID = UUID("10000000-0000-4000-8000-000000000006")
GESA_ID = UUID("10000000-0000-4000-8000-000000000008")
SESSION_NAMESPACE = UUID("16c66204-ded1-45bd-9800-a3e561328a83")
MARA_PHONE = "+493012345678"


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(user_id: UUID) -> str:
    return f"poc062-{user_id}-server-session-token-value"


async def prepare_personas(connection: asyncpg.Connection[Any]) -> None:
    now = datetime.now(timezone.utc)
    users = (ANNA_ID, BERND_ID, CARLA_ID, GESA_ID)
    await connection.execute(
        """
        UPDATE user_account
        SET status = 'active',
            updated_at = $2
        WHERE id = $1
          AND status = 'suspended'
        """,
        GESA_ID,
        now,
    )
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        list(users),
    )
    for user_id in users:
        token = token_for(user_id)
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


async def add_real_phone() -> None:
    settings = TwentyGatewaySettings(
        base_url=require_env("TWENTY_BASE_URL"),
        api_key=SecretStr(require_env("TWENTY_INTEGRATION_API_KEY")),
        timeout_seconds=30,
    )
    async with TwentyCrmGateway(settings) as crm:
        record, receipt = await crm.update_person(
            MARA_ID,
            MARA_ID,
            PersonUpdate(phone=MARA_PHONE),
            correlation_id="poc062:golden-phone",
        )
        if record.data.phone != MARA_PHONE or receipt.twenty_id != MARA_ID:
            raise ContractFailure(
                "Telefonnummer wurde nicht über den CRM-Port persistiert"
            )
        reread = await crm.get_person(
            MARA_ID,
            correlation_id="poc062:golden-phone-reread",
        )
        if reread is None or reread.data.phone != MARA_PHONE:
            raise ContractFailure(
                "Telefonnummer ist nach echtem Twenty-Read nicht sichtbar"
            )


async def request_board(
    api: httpx.AsyncClient,
    user_id: UUID,
    request_id: str,
) -> Mapping[str, Any]:
    response = await api.get(
        f"/api/v1/actions/{ACTION_ID}/acquisition/activity-board",
        headers={
            "Cookie": f"{SESSION_COOKIE_NAME}={token_for(user_id)}",
            "X-Request-ID": request_id,
        },
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ContractFailure("Arbeitsvorrat besitzt keinen Objektvertrag")
    return payload


def names(payload: Mapping[str, Any]) -> set[str]:
    items = payload.get("workItems")
    if not isinstance(items, list):
        raise ContractFailure("Arbeitsvorrat enthält keine workItems")
    return {
        str(item.get("partyDisplayName")) for item in items if isinstance(item, dict)
    }


async def exercise(connection: asyncpg.Connection[Any]) -> None:
    await prepare_personas(connection)
    await add_real_phone()
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        anna = await request_board(api, ANNA_ID, "poc062:anna-board")
        bernd = await request_board(api, BERND_ID, "poc062:bernd-board")
        carla = await request_board(api, CARLA_ID, "poc062:carla-board")
        gesa = await request_board(api, GESA_ID, "poc062:empty-board")

    if names(anna) != {"Musterwerk GmbH", "Doppelkontakt AG"}:
        raise ContractFailure(f"Annas Sichtgrenze ist falsch: {sorted(names(anna))}")
    if names(bernd) != {"Bäckerei Sonnenseite KG", "Doppelkontakt AG"}:
        raise ContractFailure(f"Bernds Sichtgrenze ist falsch: {sorted(names(bernd))}")
    if names(carla) != {"Sophie Sponsor"}:
        raise ContractFailure(f"Carlas Sichtgrenze ist falsch: {sorted(names(carla))}")
    if names(gesa):
        raise ContractFailure(f"Leere Persona besitzt unerwartete Daten: {names(gesa)}")

    anna_items = anna["workItems"]
    musterwerk = next(
        item for item in anna_items if item["partyDisplayName"] == "Musterwerk GmbH"
    )
    if (
        musterwerk["contactName"] != "Mara Muster"
        or musterwerk["email"] != "mara.muster@musterwerk.leonaid.invalid"
        or musterwerk["phone"] != MARA_PHONE
    ):
        raise ContractFailure("Twenty-Kontaktwege fehlen in Annas Sponsorzeile")

    shared = next(
        item for item in anna_items if item["partyDisplayName"] == "Doppelkontakt AG"
    )
    shared_names = {item["displayName"] for item in shared.get("assignedAcquirers", [])}
    if shared_names != {"Anna Akquise", "Bernd Binder"}:
        raise ContractFailure(f"Mitzuordnung ist unvollständig: {shared_names}")

    print(
        "pwa-contract: OK:",
        "reale Twenty-Kontakte, vier Personas, Sichtgrenzen, Leerzustand",
        "und Mitzuordnung bewiesen",
    )


async def main() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"))
    try:
        await exercise(connection)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
