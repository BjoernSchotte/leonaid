#!/usr/bin/env python3
"""Real PostgreSQL/FastAPI contract for OpenFeature-backed flags."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
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
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
SESSION_NAMESPACE = UUID("f7bff30c-b132-43b2-bcb4-26776db4cf83")
SYSTEM_STATUS_KEY = "admin.system_status_panel"
PREVIEW_NOTICE_KEY = "admin.preview_notice"


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(label: str, user_id: UUID) -> str:
    return f"poc096-{label}-{user_id}-real-session-token-value"


def session_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def error_code(response: httpx.Response) -> str:
    value = response.json()
    if not isinstance(value, dict) or not isinstance(value.get("error"), dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Vertrag")
    return str(value["error"].get("code"))


async def seed_sessions(
    connection: asyncpg.Connection[Any],
    output: Path,
) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    sessions = (
        ("SIMONE_SESSION", "simone", SIMONE_ID, now),
        (
            "STALE_SIMONE_SESSION",
            "simone-stale",
            SIMONE_ID,
            now - timedelta(minutes=30),
        ),
        ("KLARA_SESSION", "klara", KLARA_ID, now),
    )
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        [SIMONE_ID, KLARA_ID],
    )
    tokens: dict[str, str] = {}
    lines: list[str] = []
    for env_name, label, user_id, fresh_at in sessions:
        token = token_for(label, user_id)
        tokens[label] = token
        lines.append(f"{env_name}={token}\n")
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at,
                last_seen_at, fresh_login_at, device_hint,
                created_at, updated_at
            )
            VALUES (
                $1, $2, $3, $4,
                $5, $6, 'POC-096 OpenFeature',
                $6, $5
            )
            """,
            uuid5(SESSION_NAMESPACE, label),
            user_id,
            session_token_digest(token),
            fresh_at + SESSION_LIFETIME,
            now,
            fresh_at,
        )
    output.write_text("".join(lines), encoding="utf-8")
    output.chmod(0o600)
    return tokens


def flags_by_key(payload: object) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("flags"), list):
        raise ContractFailure("Feature-Flag-Antwort besitzt keine Liste")
    result: dict[str, dict[str, Any]] = {}
    for item in payload["flags"]:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise ContractFailure(
                "Feature-Flag-Antwort enthält einen ungültigen Eintrag"
            )
        result[item["key"]] = item
    return result


async def prepare(
    connection: asyncpg.Connection[Any],
    sessions_path: Path,
) -> None:
    tokens = await seed_sessions(connection, sessions_path)
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        admin = await api.get(
            "/api/v1/admin/feature-flags",
            headers=session_headers(tokens["simone"]),
        )
        admin.raise_for_status()
        flags = flags_by_key(admin.json())
        if set(flags) != {SYSTEM_STATUS_KEY, PREVIEW_NOTICE_KEY} or any(
            flag.get("enabled") is not False or flag.get("revision") != 1
            for flag in flags.values()
        ):
            raise ContractFailure("Golden Feature-Flags starten nicht deterministisch")

        evaluation = await api.get(
            "/api/v1/feature-flags/evaluations?surface=web",
            headers=session_headers(tokens["klara"]),
        )
        evaluation.raise_for_status()
        evaluated = flags_by_key(evaluation.json())
        if any(
            flag.get("enabled") is not False
            or flag.get("provider") != "leonaid-postgres-snapshot"
            for flag in evaluated.values()
        ):
            raise ContractFailure("OpenFeature wertet den Golden-Startwert falsch aus")

        forbidden = await api.get(
            "/api/v1/admin/feature-flags",
            headers=session_headers(tokens["klara"]),
        )
        if (
            forbidden.status_code != 403
            or error_code(forbidden) != "system_admin_required"
        ):
            raise ContractFailure("Charity-Admin konnte Feature-Flags verwalten")

        stale = await api.put(
            f"/api/v1/admin/feature-flags/{SYSTEM_STATUS_KEY}",
            headers=session_headers(tokens["simone-stale"]),
            json={"enabled": True, "expectedRevision": 1},
        )
        if stale.status_code != 401 or error_code(stale) != "fresh_login_required":
            raise ContractFailure(
                "Feature-Flag-Änderung verlangte keinen frischen Login: "
                f"HTTP {stale.status_code} {stale.text}"
            )

        disabled = await api.get(
            "/api/v1/admin/system-status",
            headers=session_headers(tokens["simone"]),
        )
        if (
            disabled.status_code != 404
            or error_code(disabled) != "feature_flag_disabled"
        ):
            raise ContractFailure("Deaktiviertes Backend-Flag gab Diagnose frei")


async def assert_result(connection: asyncpg.Connection[Any]) -> None:
    simone = token_for("simone", SIMONE_ID)
    klara = token_for("klara", KLARA_ID)
    rows = await connection.fetch(
        """
        SELECT key, enabled, revision, updated_by_user_id
        FROM feature_flag
        ORDER BY key
        """
    )
    persisted = {
        str(row["key"]): {
            "enabled": bool(row["enabled"]),
            "revision": int(row["revision"]),
            "updatedBy": str(row["updated_by_user_id"]),
        }
        for row in rows
    }
    expected = {
        PREVIEW_NOTICE_KEY: {
            "enabled": True,
            "revision": 2,
            "updatedBy": str(SIMONE_ID),
        },
        SYSTEM_STATUS_KEY: {
            "enabled": True,
            "revision": 4,
            "updatedBy": str(SIMONE_ID),
        },
    }
    if persisted != expected:
        raise ContractFailure(f"Persistierter Flag-Zustand weicht ab: {persisted}")

    audit_rows = await connection.fetch(
        """
        SELECT payload
        FROM audit_event
        WHERE entity_type = 'feature_flag'
          AND event_type = 'feature_flag_changed'
        ORDER BY occurred_at, id
        """
    )
    if len(audit_rows) != 4:
        raise ContractFailure(
            f"Feature-Flag-Audit enthält {len(audit_rows)} statt 4 Änderungen"
        )
    audit_payloads = [
        json.loads(row["payload"])
        if isinstance(row["payload"], str)
        else row["payload"]
        for row in audit_rows
    ]
    if {payload.get("key") for payload in audit_payloads} != {
        SYSTEM_STATUS_KEY,
        PREVIEW_NOTICE_KEY,
    }:
        raise ContractFailure("Feature-Flag-Audit enthält unbekannte Schlüssel")

    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        admin = await api.get(
            "/api/v1/admin/feature-flags",
            headers=session_headers(simone),
        )
        admin.raise_for_status()
        flags = flags_by_key(admin.json())
        if (
            flags[SYSTEM_STATUS_KEY].get("revision") != 4
            or flags[PREVIEW_NOTICE_KEY].get("revision") != 2
        ):
            raise ContractFailure("API verlor Flags nach dem Prozessneustart")

        evaluation = await api.get(
            "/api/v1/feature-flags/evaluations?surface=web",
            headers=session_headers(klara),
        )
        evaluation.raise_for_status()
        evaluated = flags_by_key(evaluation.json())
        if any(
            flag.get("enabled") is not True
            or flag.get("reason") != "STATIC"
            or flag.get("provider") != "leonaid-postgres-snapshot"
            for flag in evaluated.values()
        ):
            raise ContractFailure("Python OpenFeature wertete Persistenz nicht aus")

        diagnostics = await api.get(
            "/api/v1/admin/system-status",
            headers=session_headers(simone),
        )
        diagnostics.raise_for_status()
        if diagnostics.json().get("evaluatedBy") != "openfeature":
            raise ContractFailure("Backend-Diagnose belegt OpenFeature nicht")

        forbidden_diagnostics = await api.get(
            "/api/v1/admin/system-status",
            headers=session_headers(klara),
        )
        if (
            forbidden_diagnostics.status_code != 403
            or error_code(forbidden_diagnostics) != "system_admin_required"
        ):
            raise ContractFailure("Browser-Flag umging Backend-RBAC")

        stale_revision = await api.put(
            f"/api/v1/admin/feature-flags/{SYSTEM_STATUS_KEY}",
            headers=session_headers(simone),
            json={"enabled": False, "expectedRevision": 1},
        )
        if (
            stale_revision.status_code != 409
            or error_code(stale_revision) != "feature_flag_revision_conflict"
        ):
            raise ContractFailure("Veraltete Flag-Version wurde nicht abgewiesen")

        same_value = await api.put(
            f"/api/v1/admin/feature-flags/{SYSTEM_STATUS_KEY}",
            headers=session_headers(simone),
            json={"enabled": True, "expectedRevision": 4},
        )
        same_value.raise_for_status()
        if same_value.json().get("revision") != 4:
            raise ContractFailure("Idempotente Flag-Änderung erhöhte die Version")
        audit_count = await connection.fetchval(
            """
            SELECT count(*)
            FROM audit_event
            WHERE entity_type = 'feature_flag'
              AND event_type = 'feature_flag_changed'
            """
        )
        if audit_count != 4:
            raise ContractFailure("Idempotente Flag-Änderung erzeugte ein AuditEvent")


async def run(command: str, sessions_path: Path | None) -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        if command == "prepare":
            if sessions_path is None:
                raise ContractFailure("prepare benötigt eine Sessions-Datei")
            await prepare(connection, sessions_path)
        else:
            await assert_result(connection)
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "assert"))
    parser.add_argument("sessions_path", nargs="?", type=Path)
    arguments = parser.parse_args()
    asyncio.run(run(arguments.command, arguments.sessions_path))
    print(f"feature-flag-contract: OK: {arguments.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
