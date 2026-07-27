#!/usr/bin/env python3
"""Dynamic security contract against the real proxy, API and PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    LoginCode,
    LoginPurpose,
    login_code_digest,
    login_magic_digest,
)

ADMIN_ID = UUID("10000000-0000-4000-8000-000000000002")
ADMIN_EMAIL = "klara.kern@leonaid.invalid"
SAME_ORIGIN = "https://proxy:8443"
FOREIGN_ORIGIN = "https://attacker.invalid"


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def error_code(response: httpx.Response) -> str:
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Vertrag")
    return str(payload["error"].get("code"))


def session_from(response: httpx.Response) -> str:
    cookie = SimpleCookie()
    cookie.load(response.headers.get("set-cookie", ""))
    value = cookie.get(SESSION_COOKIE_NAME)
    if value is None:
        raise ContractFailure("Login setzt kein Sitzungs-Cookie")
    return value.value


async def insert_login_challenge(
    connection: asyncpg.Connection[Any],
    *,
    secret: str,
    code: LoginCode,
) -> None:
    now = datetime.now(timezone.utc)
    await connection.execute(
        "DELETE FROM login_challenge WHERE user_id = $1 AND purpose = 'login'",
        ADMIN_ID,
    )
    await connection.execute(
        """
        INSERT INTO login_challenge (
            id, user_id, purpose, email_snapshot,
            token_digest, code_digest, status, expires_at,
            failed_code_attempts, created_at, updated_at
        )
        VALUES ($1, $2, 'login', $3, $4, $5, 'pending', $6, 0, $7, $7)
        """,
        uuid4(),
        ADMIN_ID,
        ADMIN_EMAIL,
        login_magic_digest(secrets.token_urlsafe(32)),
        login_code_digest(ADMIN_EMAIL, code, secret, LoginPurpose.LOGIN),
        now + timedelta(minutes=10),
        now,
    )


async def prove() -> None:
    database_url = require_env("CORE_DATABASE_URL")
    secret = require_env("LEONAID_SECRET_KEY")
    canary_path = Path(require_env("LEONAID_SECURITY_CANARY_FILE"))
    canary = f"poc110-secret-{secrets.token_urlsafe(24)}"
    canary_path.write_text(canary, encoding="utf-8")
    canary_path.chmod(0o600)

    connection = await asyncpg.connect(database_url)
    code = LoginCode("731946")
    await insert_login_challenge(connection, secret=secret, code=code)

    async with httpx.AsyncClient(
        base_url=SAME_ORIGIN,
        verify=False,
        timeout=20,
        headers={"User-Agent": "LeonAid-POC110-real-contract/1"},
    ) as client:
        health = await client.get("/api/health/live")
        if health.status_code != 200:
            raise ContractFailure("Proxy-Health-Endpunkt ist nicht erreichbar")
        expected_headers = {
            "content-security-policy",
            "permissions-policy",
            "referrer-policy",
            "strict-transport-security",
            "x-content-type-options",
            "x-frame-options",
        }
        if not expected_headers.issubset(health.headers):
            raise ContractFailure("Security-Header fehlen am echten TLS-Proxy")

        allowed = await client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": SAME_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        denied = await client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": FOREIGN_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )
        if (
            allowed.status_code != 204
            or allowed.headers.get("access-control-allow-origin") != SAME_ORIGIN
            or denied.status_code != 403
            or error_code(denied) != "cors_origin_rejected"
        ):
            raise ContractFailure("CORS-Allowlist wird nicht strikt erzwungen")

        fixed = "attacker-controlled-session-value-that-must-not-survive"
        login = await client.post(
            "/api/v1/auth/login/complete",
            headers={"Cookie": f"{SESSION_COOKIE_NAME}={fixed}"},
            json={"email": ADMIN_EMAIL, "code": code.value},
        )
        if login.status_code != 200:
            raise ContractFailure(f"Vorbereiteter echter Login scheitert: {login.text}")
        session = session_from(login)
        if session == fixed:
            raise ContractFailure("Login übernimmt ein vorgegebenes Sitzungs-Token")
        identity = await client.get(
            "/api/v1/identity/me",
            headers={"Cookie": f"{SESSION_COOKIE_NAME}={session}"},
        )
        if identity.status_code != 200:
            raise ContractFailure("Neu rotierte Sitzung ist nicht verwendbar")

        cross_site = await client.post(
            "/api/v1/auth/logout",
            headers={
                "Cookie": f"{SESSION_COOKIE_NAME}={session}",
                "Origin": FOREIGN_ORIGIN,
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "cors",
            },
        )
        if cross_site.status_code != 403 or error_code(cross_site) != "csrf_rejected":
            raise ContractFailure("Cross-Site-Sitzungsmutation wird nicht abgewehrt")
        still_active = await client.get(
            "/api/v1/identity/me",
            headers={"Cookie": f"{SESSION_COOKIE_NAME}={session}"},
        )
        if still_active.status_code != 200:
            raise ContractFailure("Abgewiesener CSRF-Versuch verändert die Sitzung")

        foreign_action = await connection.fetchval(
            """
            SELECT action.id
            FROM charity_action AS action
            WHERE NOT EXISTS (
              SELECT 1 FROM action_membership AS membership
              WHERE membership.action_id = action.id
                AND membership.user_id = $1
            )
            ORDER BY action.id
            LIMIT 1
            """,
            ADMIN_ID,
        )
        if foreign_action is None:
            raise ContractFailure("Golden Data enthält keine fremde Charity-Aktion")
        horizontal = await client.get(
            f"/api/v1/actions/{foreign_action}",
            headers={"Cookie": f"{SESSION_COOKIE_NAME}={session}"},
        )
        if horizontal.status_code not in {403, 404}:
            raise ContractFailure("Fremde Charity-Aktion ist horizontal abrufbar")

        options = await client.get(
            "/api/v1/invitations/options",
            headers={"Cookie": f"{SESSION_COOKIE_NAME}={session}"},
        )
        option_payload = options.json()
        action_id = str(option_payload["actions"][0]["id"])
        invitation_headers = {
            "Cookie": f"{SESSION_COOKIE_NAME}={session}",
            "Origin": SAME_ORIGIN,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
        }
        invitation_body = {
            "actionId": action_id,
            "email": "poc110-rate-limit@leonaid.invalid",
            "displayName": "POC 110 Rate Limit",
            "role": "acquirer",
        }
        invitation_statuses = [
            (
                await client.post(
                    "/api/v1/invitations",
                    headers=invitation_headers,
                    json=invitation_body,
                )
            ).status_code
            for _ in range(11)
        ]
        if invitation_statuses[:10] != [202] * 10 or invitation_statuses[10] != 429:
            raise ContractFailure(
                "Einladungs-Rate-Limit greift nicht am elften Versuch"
            )

        login_statuses = [
            (
                await client.post(
                    "/api/v1/auth/login",
                    json={"email": "poc110-unknown@leonaid.invalid"},
                )
            ).status_code
            for _ in range(6)
        ]
        if login_statuses[:5] != [202] * 5 or login_statuses[5] != 429:
            raise ContractFailure("Login-Rate-Limit greift nicht am sechsten Versuch")

        leaked = await client.post(
            f"/api/v1/does-not-exist?probe={canary}",
            json={"probe": canary},
        )
        if canary in leaked.text:
            raise ContractFailure("Secret-Canary wird in der Fehlerantwort gespiegelt")

        same_site = await client.post(
            "/api/v1/auth/logout",
            headers={
                "Cookie": f"{SESSION_COOKIE_NAME}={session}",
                "Origin": SAME_ORIGIN,
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
            },
        )
        if same_site.status_code != 200:
            raise ContractFailure("Gleich-originiger Logout wird fälschlich blockiert")

    await connection.close()
    print(
        "security-contract: TLS/Headers, CORS, CSRF, Rotation, RBAC und Rate-Limits OK"
    )


if __name__ == "__main__":
    try:
        asyncio.run(prove())
    except (ContractFailure, asyncpg.PostgresError, httpx.HTTPError) as error:
        print(f"security-contract: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from None
