#!/usr/bin/env python3
"""Real HTTP/PostgreSQL maintenance contract for POC-113."""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any

import asyncpg
import httpx

ACTION_ID = "20000000-0000-4000-8000-000000000001"
KLARA_SESSION = "poc101-10000000-0000-4000-8000-000000000002-server-session-token-value"
SESSION_COOKIE = "__Host-leonaid_session"


class ContractFailure(RuntimeError):
    pass


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


async def counts(connection: asyncpg.Connection[Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for table in ("charity_action", "login_challenge", "audit_event", "outbox_event"):
        value = await connection.fetchval(f"SELECT count(*) FROM {table}")
        result[table] = int(value or 0)
    return result


async def assert_reads_available(client: httpx.AsyncClient) -> None:
    live = await client.get("/health/live")
    if live.status_code != 200:
        raise ContractFailure(f"Liveness-Read liefert {live.status_code}")
    dashboard = await client.get(
        f"/api/v1/actions/{ACTION_ID}/dashboard",
        cookies={SESSION_COOKIE: KLARA_SESSION},
    )
    if dashboard.status_code != 200:
        raise ContractFailure(f"Dashboard-Read liefert {dashboard.status_code}")


async def verify(mode: str) -> None:
    connection = await asyncpg.connect(required("CORE_DATABASE_URL"), timeout=10)
    try:
        async with httpx.AsyncClient(
            base_url=required("API_BASE_URL"),
            timeout=20,
        ) as client:
            await assert_reads_available(client)
            before = await counts(connection)
            if mode == "maintenance":
                response = await client.post(
                    "/api/v1/auth/login",
                    json={"email": "klara.kern@golden.leonaid.invalid"},
                    headers={"X-Request-ID": "poc113:maintenance-write"},
                )
                if response.status_code != 503:
                    raise ContractFailure(
                        f"Wartungsmodus akzeptiert POST mit {response.status_code}"
                    )
                payload = response.json()
                if payload.get("error", {}).get("code") != "maintenance_mode":
                    raise ContractFailure(
                        "Wartungsfehler hat keinen stabilen Fehlercode"
                    )
                if response.headers.get("retry-after") != "60":
                    raise ContractFailure("Wartungsfehler hat kein Retry-After")
                after = await counts(connection)
                if after != before:
                    raise ContractFailure(
                        f"Blockierter Write hat Daten verändert: {before} -> {after}"
                    )
            else:
                response = await client.post("/api/v1/auth/login", json={})
                if response.status_code != 422:
                    raise ContractFailure(
                        f"Write-Grenze blieb nach Wartung aktiv: {response.status_code}"
                    )
    finally:
        await connection.close()
    print(f"upgrade-contract: OK: {mode}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("available", "maintenance"))
    arguments = parser.parse_args()
    try:
        asyncio.run(verify(arguments.mode))
    except (ContractFailure, asyncpg.PostgresError, httpx.HTTPError) as error:
        print(f"upgrade-contract: ERROR: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
