#!/usr/bin/env python3
"""POC-020 smoke test against a real ASGI server and PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import asyncpg
import httpx

REQUEST_ID = "poc020:system-admin:golden-v1"


class SmokeError(RuntimeError):
    """The real platform contract did not hold."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeError(message)


def json_object(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise SmokeError(f"{response.url.path} lieferte kein JSON-Objekt")
    return value


async def verify_postgres() -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=10)
    try:
        value = await connection.fetchval("SELECT 1")
    finally:
        await connection.close()
    require(value == 1, "direkte PostgreSQL-Prüfung schlug fehl")


async def run() -> None:
    base_url = os.environ["LEONAID_INTEGRATION_BASE_URL"].rstrip("/")
    async with httpx.AsyncClient(base_url=base_url, timeout=20) as client:
        ready_response = await client.get(
            "/health/ready",
            headers={"X-Request-ID": REQUEST_ID},
        )
        ready = json_object(ready_response)
        require(ready_response.headers.get("X-Request-ID") == REQUEST_ID, "Request-ID")
        require(ready.get("status") == "ready", "API ist nicht fachlich bereit")
        checks = ready.get("checks")
        if not isinstance(checks, dict):
            raise SmokeError("Readiness-Checks fehlen")
        postgres = checks.get("postgres")
        if not isinstance(postgres, dict):
            raise SmokeError("PostgreSQL-Readiness fehlt")
        details = postgres.get("details")
        if (
            postgres.get("status") != "ready"
            or not isinstance(details, dict)
            or details.get("probe") != 1
        ):
            raise SmokeError("ASGI-Server hat PostgreSQL nicht real geprüft")

        information = json_object(await client.get("/api/v1/platform"))
        require(
            information
            == {
                "service": "leonaid-api",
                "release": "0.0.0",
                "api_version": "v1",
            },
            "versionierte Plattformantwort weicht ab",
        )

        missing_response = await client.get(
            "/api/v1/not-found",
            headers={"X-Request-ID": REQUEST_ID},
        )
        require(missing_response.status_code == 404, "404-Status fehlt")
        missing = missing_response.json()
        require(
            missing
            == {
                "error": {
                    "code": "endpoint_not_found",
                    "message": "Dieser API-Endpunkt existiert nicht.",
                    "requestId": REQUEST_ID,
                }
            },
            "einheitliches Fehlerformat weicht ab",
        )

        openapi = json_object(await client.get("/openapi.json"))
        paths = openapi.get("paths")
        require(
            isinstance(paths, dict) and "/api/v1/platform" in paths,
            "versionierte API-Basis fehlt im OpenAPI-Vertrag",
        )

    await verify_postgres()


def main() -> int:
    try:
        asyncio.run(run())
    except (
        KeyError,
        OSError,
        SmokeError,
        asyncpg.PostgresError,
        httpx.HTTPError,
    ) as error:
        print(
            "poc020-smoke: ERROR: "
            f"requestId={REQUEST_ID} persona=system-admin "
            f"aktion=platform dataset=golden-v1 type={type(error).__name__}",
            file=sys.stderr,
        )
        return 1
    print(
        "poc020-smoke: OK: realer ASGI-Server, PostgreSQL, "
        f"API-Vertrag und Fehlerformat requestId={REQUEST_ID}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
