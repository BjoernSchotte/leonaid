#!/usr/bin/env python3
"""Real PostgreSQL/FastAPI/Mailpit contract for POC-114."""

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
KLARA_EMAIL = "klara.kern@leonaid.invalid"
SESSION_NAMESPACE = UUID("7d2daf5e-1965-41c0-bbbb-3379585cf027")
CONTRACT_REQUEST_ID = "poc114-contract-correlation"
SUPPORT_PROBE_REQUEST_ID = "pilot051-support-contract"


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def session_token() -> str:
    return f"poc114-system-admin-{SIMONE_ID}-real-session-token"


def session_headers(*, request_id: str = CONTRACT_REQUEST_ID) -> dict[str, str]:
    return {
        "Cookie": f"{SESSION_COOKIE_NAME}={session_token()}",
        "X-Request-ID": request_id,
    }


async def seed_session(connection: asyncpg.Connection[Any], output: Path) -> None:
    now = datetime.now(timezone.utc)
    token = session_token()
    await connection.execute(
        "DELETE FROM user_session WHERE id = $1",
        uuid5(SESSION_NAMESPACE, "simone"),
    )
    await connection.execute(
        """
        INSERT INTO user_session (
            id, user_id, token_digest, expires_at, last_seen_at,
            fresh_login_at, device_hint, created_at, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $5, 'POC-114 Betrieb', $5, $5)
        """,
        uuid5(SESSION_NAMESPACE, "simone"),
        SIMONE_ID,
        session_token_digest(token),
        now + SESSION_LIFETIME,
        now,
    )
    output.write_text(f"SIMONE_SESSION={token}\n", encoding="utf-8")
    output.chmod(0o600)


async def overview(
    api: httpx.AsyncClient,
    *,
    request_id: str = CONTRACT_REQUEST_ID,
) -> dict[str, Any]:
    response = await api.get(
        "/api/v1/admin/operations",
        headers=session_headers(request_id=request_id),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ContractFailure("Operations-Antwort ist kein Objekt")
    return payload


def dependency_states(payload: dict[str, Any]) -> dict[str, str]:
    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, list):
        raise ContractFailure("Operations-Antwort enthält keine Abhängigkeiten")
    return {
        str(item["dependency"]): str(item["status"])
        for item in dependencies
        if isinstance(item, dict)
    }


async def prepare(
    connection: asyncpg.Connection[Any],
    sessions_path: Path,
) -> None:
    await seed_session(connection, sessions_path)
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=30,
    ) as api:
        payload = await overview(api)
        states = dependency_states(payload)
        if states != {
            "twenty": "ready",
            "rustfs": "ready",
            "mail": "ready",
            "worker": "ready",
        }:
            raise ContractFailure(f"Startzustand nicht bereit: {states}")
        if payload.get("requestId") != CONTRACT_REQUEST_ID:
            raise ContractFailure("Korrelations-ID ging im API-Vertrag verloren")
        if any(
            item.get("requestId") != CONTRACT_REQUEST_ID
            for item in payload["dependencies"]
        ):
            raise ContractFailure("Abhängigkeitsprobes teilen nicht dieselbe ID")

        unauthorized = await api.get(
            "/api/v1/admin/operations",
            headers={"X-Request-ID": "poc114-anonymous"},
        )
        if unauthorized.status_code != 401:
            raise ContractFailure("Operations-Daten waren anonym lesbar")

        probe = await api.post(
            "/api/v1/admin/support/probe",
            headers=session_headers(request_id=SUPPORT_PROBE_REQUEST_ID),
        )
        if probe.status_code != 503:
            raise ContractFailure(
                f"Support-Probe lieferte HTTP {probe.status_code} statt 503"
            )
        probe_error = probe.json().get("error", {})
        if probe_error != {
            "code": "support_probe_failed",
            "message": (
                "Der kontrollierte Diagnosetest wurde wie vorgesehen "
                "abgebrochen. Kopiere den Support-Code und prüfe ihn direkt "
                "darunter."
            ),
            "requestId": SUPPORT_PROBE_REQUEST_ID,
        }:
            raise ContractFailure(f"Unsicherer Support-Probe-Vertrag: {probe_error}")

        diagnostic = await api.get(
            f"/api/v1/admin/support/requests/{SUPPORT_PROBE_REQUEST_ID}",
            headers=session_headers(request_id="pilot051-support-lookup"),
        )
        diagnostic.raise_for_status()
        support = diagnostic.json()
        expected = {
            "supportCode": SUPPORT_PROBE_REQUEST_ID,
            "method": "POST",
            "route": "/api/v1/admin/support/probe",
            "statusCode": 503,
            "errorCode": "support_probe_failed",
            "outcome": "failed",
        }
        for key, value in expected.items():
            if support.get(key) != value:
                raise ContractFailure(
                    f"Supportdiagnose {key}={support.get(key)!r}, erwartet {value!r}"
                )
        serialized = json.dumps(support, sort_keys=True).casefold()
        forbidden = (
            "klara.kern@",
            "system-admin@",
            "cookie",
            "payload",
            "token",
            "actor",
            "sponsor",
        )
        if any(value in serialized for value in forbidden):
            raise ContractFailure("Supportdiagnose enthält Payload oder Identität")

        anonymous_diagnostic = await api.get(
            f"/api/v1/admin/support/requests/{SUPPORT_PROBE_REQUEST_ID}",
            headers={"X-Request-ID": "pilot051-support-anonymous"},
        )
        if anonymous_diagnostic.status_code != 401:
            raise ContractFailure("Supportdiagnose war anonym lesbar")


async def expect_dependency(dependency: str) -> None:
    expected = {
        "twenty": "ready",
        "rustfs": "ready",
        "mail": "ready",
        "worker": "ready",
    }
    expected[dependency] = "unavailable"
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=30,
    ) as api:
        live = await api.get("/health/live")
        if live.status_code != 200:
            raise ContractFailure(f"Liveness fiel mit {dependency} aus")
        ready = await api.get("/health/ready")
        expected_ready = 200 if dependency in {"mail", "worker"} else 503
        if ready.status_code != expected_ready:
            raise ContractFailure(
                f"Readiness für {dependency}: HTTP {ready.status_code}, "
                f"erwartet {expected_ready}"
            )
        states = dependency_states(await overview(api))
        if states != expected:
            raise ContractFailure(
                f"Ausfallsignal für {dependency} nicht trennscharf: {states}"
            )


async def create_failed_mail(
    connection: asyncpg.Connection[Any],
    state_path: Path,
) -> None:
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=30,
    ) as api:
        response = await api.post(
            "/api/v1/auth/login",
            headers={"X-Request-ID": "poc114-login-mail-failure"},
            json={"email": KLARA_EMAIL},
        )
        if response.status_code != 202:
            raise ContractFailure(
                f"Realer Login-Mail-Job entstand nicht: {response.status_code}"
            )
    row = await connection.fetchrow(
        """
        SELECT id
        FROM outbox_event
        WHERE event_type = 'mail.send.v1' AND status = 'pending'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    if row is None:
        raise ContractFailure("Login erzeugte keinen pending Outbox-Job")
    state_path.write_text(
        json.dumps({"eventId": str(row["id"])}, separators=(",", ":")),
        encoding="utf-8",
    )


async def assert_dead_letter(
    connection: asyncpg.Connection[Any],
    state_path: Path,
) -> None:
    event_id = UUID(json.loads(state_path.read_text(encoding="utf-8"))["eventId"])
    row = await connection.fetchrow(
        """
        SELECT status, attempts, last_error_code, last_error_detail
        FROM outbox_event
        WHERE id = $1
        """,
        event_id,
    )
    if (
        row is None
        or row["status"] != "dead_letter"
        or row["attempts"] != 1
        or not row["last_error_code"]
        or not row["last_error_detail"]
    ):
        raise ContractFailure(
            f"Realer Mail-Ausfall ist kein Dead Letter: {dict(row or {})}"
        )
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=30,
    ) as api:
        payload = await overview(api)
        failed_ids = {item["id"] for item in payload.get("failedJobs", [])}
        if str(event_id) not in failed_ids:
            raise ContractFailure("Dead Letter fehlt im Admin-Vertrag")


async def assert_recovered(
    connection: asyncpg.Connection[Any],
    state_path: Path,
) -> None:
    event_id = UUID(json.loads(state_path.read_text(encoding="utf-8"))["eventId"])
    deadline = asyncio.get_running_loop().time() + 30
    row = None
    while asyncio.get_running_loop().time() < deadline:
        row = await connection.fetchrow(
            """
            SELECT status, attempts, manual_retry_count, last_manual_retry_by,
                   last_error_code
            FROM outbox_event
            WHERE id = $1
            """,
            event_id,
        )
        if row is not None and row["status"] == "completed":
            break
        await asyncio.sleep(0.2)
    if (
        row is None
        or row["status"] != "completed"
        or row["attempts"] != 2
        or row["manual_retry_count"] != 1
        or row["last_manual_retry_by"] != str(SIMONE_ID)
    ):
        raise ContractFailure(
            f"UI-Retry wurde nicht sicher verarbeitet: {dict(row or {})}"
        )
    delivered = await connection.fetchval(
        "SELECT count(*) FROM mail_delivery WHERE outbox_event_id = $1",
        event_id,
    )
    audited = await connection.fetchval(
        """
        SELECT count(*)
        FROM audit_event
        WHERE event_type = 'system.outbox.manual_retry'
          AND entity_id = $1 AND actor_user_id = $2
        """,
        event_id,
        SIMONE_ID,
    )
    if delivered != 1 or audited != 1:
        raise ContractFailure(
            f"Retry-Nachweise unvollständig: delivery={delivered}, audit={audited}"
        )
    async with httpx.AsyncClient(
        base_url=require_env("MAIL_TEST_API_URL").rstrip("/"),
        timeout=30,
    ) as mailpit:
        response = await mailpit.get("/api/v1/messages")
        response.raise_for_status()
        if not response.json().get("messages"):
            raise ContractFailure("Mailpit enthält die real wiederholte Mail nicht")


async def execute(arguments: argparse.Namespace) -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"))
    try:
        if arguments.command == "prepare":
            await prepare(connection, arguments.sessions)
        elif arguments.command == "expect-dependency":
            await expect_dependency(arguments.dependency)
        elif arguments.command == "create-failed-mail":
            await create_failed_mail(connection, arguments.state)
        elif arguments.command == "assert-dead-letter":
            await assert_dead_letter(connection, arguments.state)
        elif arguments.command == "assert-recovered":
            await assert_recovered(connection, arguments.state)
        else:
            raise ContractFailure(f"Unbekannter Befehl: {arguments.command}")
    finally:
        await connection.close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("sessions", type=Path)
    failure = commands.add_parser("create-failed-mail")
    failure.add_argument("state", type=Path)
    dead_letter = commands.add_parser("assert-dead-letter")
    dead_letter.add_argument("state", type=Path)
    recovered = commands.add_parser("assert-recovered")
    recovered.add_argument("state", type=Path)
    dependency = commands.add_parser("expect-dependency")
    dependency.add_argument(
        "dependency",
        choices=("twenty", "rustfs", "mail", "worker"),
    )
    return result


if __name__ == "__main__":
    asyncio.run(execute(parser().parse_args()))
