#!/usr/bin/env python3
"""Prove POC-042 against real FastAPI, PostgreSQL, worker SMTP and Mailpit."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.domain.sessions import SESSION_COOKIE_NAME

SYSTEM_ID = UUID("10000000-0000-4000-8000-000000000001")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
SYSTEM_EMAIL = "system-admin@leonaid.invalid"
ANNA_EMAIL = "anna.akquise@leonaid.invalid"
UNKNOWN_EMAIL = "unknown-login@leonaid.invalid"
TOKEN_PATTERN = re.compile(r"/(?:login|fresh-login)\?token=([A-Za-z0-9_-]{32,256})")
CODE_PATTERN = re.compile(r"\bCode ([0-9]{6})\b")


class ContractFailure(RuntimeError):
    """The live session stack violated its product contract."""


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"required environment variable missing: {name}")
    return value


def cookie_header(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def session_from_response(response: httpx.Response) -> str:
    matching = [
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{SESSION_COOKIE_NAME}=")
    ]
    if len(matching) != 1:
        raise ContractFailure(
            "response does not set exactly one host-only session cookie"
        )
    parsed = SimpleCookie()
    parsed.load(matching[0])
    morsel = parsed.get(SESSION_COOKIE_NAME)
    if morsel is None:
        raise ContractFailure("session cookie is syntactically invalid")
    if (
        not morsel["secure"]
        or not morsel["httponly"]
        or morsel["samesite"].casefold() != "lax"
        or morsel["path"] != "/"
        or morsel["domain"]
        or not morsel["expires"]
    ):
        raise ContractFailure(
            "session cookie is not Secure/HttpOnly/host-only/SameSite=Lax"
        )
    return morsel.value


def recipient_addresses(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, str):
        if "@" in value:
            result.add(value.casefold())
    elif isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in {"address", "email"} and isinstance(item, str):
                result.add(item.casefold())
            else:
                result.update(recipient_addresses(item))
    elif isinstance(value, list):
        for item in value:
            result.update(recipient_addresses(item))
    return result


async def message_ids(mailpit: httpx.AsyncClient) -> set[str]:
    response = await mailpit.get("/api/v1/messages")
    response.raise_for_status()
    payload = response.json()
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list):
        raise ContractFailure("Mailpit message list is invalid")
    return {
        str(message["ID"])
        for message in messages
        if isinstance(message, dict) and isinstance(message.get("ID"), str)
    }


async def wait_for_new_mail(
    mailpit: httpx.AsyncClient,
    *,
    recipient: str,
    previous_ids: set[str],
) -> str:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = await mailpit.get("/api/v1/messages")
        response.raise_for_status()
        payload = response.json()
        messages = payload.get("messages") if isinstance(payload, dict) else None
        if isinstance(messages, list):
            for summary in messages:
                if (
                    not isinstance(summary, dict)
                    or summary.get("ID") in previous_ids
                    or recipient.casefold()
                    not in recipient_addresses(summary.get("To"))
                ):
                    continue
                message_id = summary.get("ID")
                if not isinstance(message_id, str):
                    continue
                detail_response = await mailpit.get(f"/api/v1/message/{message_id}")
                detail_response.raise_for_status()
                detail = detail_response.json()
                text = detail.get("Text") if isinstance(detail, dict) else None
                if not isinstance(text, str):
                    raise ContractFailure("Mailpit message has no text")
                if (
                    recipient_addresses(detail.get("From"))
                    != {"noreply@leonaid.invalid"}
                    or recipient_addresses(detail.get("ReplyTo"))
                    != {"support@leonaid.invalid"}
                    or detail.get("Subject")
                    not in {"Dein LeonAid-Login", "LeonAid-Anmeldung bestätigen"}
                    or "antworte auf diese E-Mail" not in text
                ):
                    raise ContractFailure(
                        "login mail lacks a unique sender identity, "
                        "subject or support guidance"
                    )
                return text
        await asyncio.sleep(0.2)
    raise ContractFailure(f"mail to {recipient} was not delivered in time")


def credentials_from_mail(text: str) -> tuple[str, str]:
    token = TOKEN_PATTERN.search(text)
    code = CODE_PATTERN.search(text)
    if token is None or code is None:
        raise ContractFailure("login mail does not contain link and code")
    return token.group(1), code.group(1)


async def request_login(
    client: httpx.AsyncClient,
    mailpit: httpx.AsyncClient,
    email: str,
) -> tuple[str, str]:
    before = await message_ids(mailpit)
    first = await client.post(
        "/api/v1/auth/login",
        headers={"X-Request-ID": f"poc042:login:request:{uuid4()}"},
        json={"email": email},
    )
    second = await client.post(
        "/api/v1/auth/login",
        headers={"X-Request-ID": f"poc042:login:repeat:{uuid4()}"},
        json={"email": email},
    )
    expected = {"status": "queued"}
    if first.status_code != 202 or first.json() != expected:
        raise ContractFailure("login request does not return the generic 202 contract")
    if second.status_code != 202 or second.json() != expected:
        raise ContractFailure("repeated login request is not generic/idempotent")
    return credentials_from_mail(
        await wait_for_new_mail(
            mailpit,
            recipient=email,
            previous_ids=before,
        )
    )


async def complete_login(
    client: httpx.AsyncClient,
    *,
    magic_token: str | None = None,
    email: str | None = None,
    code: str | None = None,
) -> tuple[httpx.Response, str]:
    body: dict[str, str]
    if magic_token is not None:
        body = {"magicToken": magic_token}
    else:
        if email is None or code is None:
            raise ContractFailure("code login needs email and code")
        body = {"email": email, "code": code}
    response = await client.post(
        "/api/v1/auth/login/complete",
        headers={
            "X-Request-ID": f"poc042:login:complete:{uuid4()}",
            "User-Agent": "POC-042 real contract",
        },
        json=body,
    )
    if response.status_code != 200:
        raise ContractFailure(
            f"login completion returned HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )
    return response, session_from_response(response)


async def expect_login_invalid(response: httpx.Response, label: str) -> None:
    if (
        response.status_code != 401
        or response.json().get("error", {}).get("code") != "login_invalid"
    ):
        raise ContractFailure(f"{label} was not rejected generically")


async def require_identity(
    client: httpx.AsyncClient,
    token: str,
    *,
    display_name: str,
) -> dict[str, Any]:
    response = await client.get(
        "/api/v1/identity/me",
        headers={
            **cookie_header(token),
            "X-Request-ID": f"poc042:identity:{uuid4()}",
        },
    )
    if response.status_code != 200:
        raise ContractFailure(f"valid 90-day session was rejected: {response.text}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ContractFailure("identity response is not an object")
    if payload.get("displayName") != display_name:
        raise ContractFailure("session was assigned to the wrong account")
    for field in (
        "sessionExpiresAt",
        "sessionLastSeenAt",
        "freshLoginAt",
        "freshUntil",
    ):
        if field not in payload:
            raise ContractFailure(f"session metadata field missing: {field}")
    return dict(payload)


async def run() -> None:
    database_url = require_env("CORE_DATABASE_URL")
    api_url = require_env("LEONAID_API_BASE_URL").rstrip("/")
    mailpit_url = require_env("MAIL_TEST_API_URL").rstrip("/")
    connection = await asyncpg.connect(database_url, timeout=10)
    try:
        await connection.execute(
            """
            DELETE FROM login_challenge;
            DELETE FROM user_session;
            DELETE FROM outbox_event
            WHERE aggregate_type = 'login_challenge';
            """
        )
        async with (
            httpx.AsyncClient(base_url=api_url, timeout=15) as client,
            httpx.AsyncClient(base_url=mailpit_url, timeout=10) as mailpit,
        ):
            unknown_before = await message_ids(mailpit)
            unknown = await client.post(
                "/api/v1/auth/login",
                headers={"X-Request-ID": f"poc042:unknown:{uuid4()}"},
                json={"email": UNKNOWN_EMAIL},
            )
            if unknown.status_code != 202 or unknown.json() != {"status": "queued"}:
                raise ContractFailure("unknown account received a different response")
            if await message_ids(mailpit) != unknown_before:
                raise ContractFailure("unknown account triggered an email")

            anna_magic, anna_code = await request_login(client, mailpit, ANNA_EMAIL)
            anna_response, anna_token = await complete_login(
                client,
                magic_token=anna_magic,
            )
            if anna_response.json().get("userId") != str(ANNA_ID):
                raise ContractFailure("magic-link login activated the wrong account")
            await require_identity(client, anna_token, display_name="Anna Akquise")
            alternate = await client.post(
                "/api/v1/auth/login/complete",
                headers={"X-Request-ID": f"poc042:alternate:{uuid4()}"},
                json={"email": ANNA_EMAIL, "code": anna_code},
            )
            await expect_login_invalid(alternate, "alternate consumed code")

            anna_digest = hashlib.sha256(anna_token.encode()).hexdigest()
            anna_session = await connection.fetchrow(
                """
                SELECT id, user_id, token_digest, created_at, expires_at,
                       last_seen_at, fresh_login_at, revoked_at, device_hint
                FROM user_session
                WHERE token_digest = $1
                """,
                anna_digest,
            )
            if anna_session is None:
                raise ContractFailure("session was not stored server-side")
            if (
                anna_session["user_id"] != ANNA_ID
                or anna_session["expires_at"] - anna_session["created_at"]
                != timedelta(days=90)
                or anna_session["last_seen_at"] < anna_session["created_at"]
                or anna_session["fresh_login_at"] != anna_session["created_at"]
                or anna_session["revoked_at"] is not None
                or anna_session["device_hint"] != "POC-042 real contract"
            ):
                raise ContractFailure("90-day session record is inconsistent")

            system_magic, system_code = await request_login(
                client,
                mailpit,
                SYSTEM_EMAIL,
            )
            system_response, system_token = await complete_login(
                client,
                email=SYSTEM_EMAIL,
                code=system_code,
            )
            system_session_id = UUID(str(system_response.json()["userId"]))
            if system_session_id != SYSTEM_ID:
                raise ContractFailure("code login activated the wrong system account")
            system_digest = hashlib.sha256(system_token.encode()).hexdigest()
            before_rotation = await connection.fetchrow(
                """
                UPDATE user_session
                SET created_at = created_at - INTERVAL '1 day',
                    expires_at = expires_at - INTERVAL '1 day',
                    fresh_login_at = fresh_login_at - INTERVAL '1 day'
                WHERE token_digest = $1
                RETURNING id, expires_at
                """,
                system_digest,
            )
            if before_rotation is None:
                raise ContractFailure("system session missing")
            await require_identity(client, system_token, display_name="Simone System")
            stale_admin = await client.delete(
                f"/api/v1/admin/users/{ANNA_ID}/sessions",
                headers={
                    **cookie_header(system_token),
                    "X-Request-ID": f"poc042:stale-admin:{uuid4()}",
                },
            )
            if (
                stale_admin.status_code != 401
                or stale_admin.json().get("error", {}).get("code")
                != "fresh_login_required"
            ):
                raise ContractFailure(
                    "sensitive admin action did not require a fresh login"
                )

            fresh_before = await message_ids(mailpit)
            requested = await client.post(
                "/api/v1/auth/fresh",
                headers={
                    **cookie_header(system_token),
                    "X-Request-ID": f"poc042:fresh:request:{uuid4()}",
                },
            )
            if requested.status_code != 202:
                raise ContractFailure("fresh-login challenge was not sent")
            fresh_magic, fresh_code = credentials_from_mail(
                await wait_for_new_mail(
                    mailpit,
                    recipient=SYSTEM_EMAIL,
                    previous_ids=fresh_before,
                )
            )
            refreshed = await client.post(
                "/api/v1/auth/fresh/complete",
                headers={
                    **cookie_header(system_token),
                    "X-Request-ID": f"poc042:fresh:complete:{uuid4()}",
                    "User-Agent": "POC-042 refreshed contract",
                },
                json={"code": fresh_code},
            )
            if refreshed.status_code != 200:
                raise ContractFailure(f"fresh login failed: {refreshed.text[:300]}")
            refreshed_token = session_from_response(refreshed)
            refreshed_digest = hashlib.sha256(refreshed_token.encode()).hexdigest()
            after_rotation = await connection.fetchrow(
                """
                SELECT id, expires_at, fresh_login_at, token_digest
                FROM user_session
                WHERE token_digest = $1
                """,
                refreshed_digest,
            )
            if (
                after_rotation is None
                or after_rotation["id"] != before_rotation["id"]
                or after_rotation["expires_at"] != before_rotation["expires_at"]
                or after_rotation["token_digest"] == system_digest
            ):
                raise ContractFailure(
                    "fresh login did not rotate the same absolute session token"
                )
            old_after_rotation = await client.get(
                "/api/v1/identity/me",
                headers={
                    **cookie_header(system_token),
                    "X-Request-ID": f"poc042:old-after-rotation:{uuid4()}",
                },
            )
            if old_after_rotation.status_code != 401:
                raise ContractFailure("old cookie stayed valid after token rotation")
            fresh_reuse = await client.post(
                "/api/v1/auth/fresh/complete",
                headers={
                    **cookie_header(refreshed_token),
                    "X-Request-ID": f"poc042:fresh:reuse:{uuid4()}",
                },
                json={"magicToken": fresh_magic},
            )
            await expect_login_invalid(fresh_reuse, "consumed fresh magic link")

            revoked = await client.delete(
                f"/api/v1/admin/users/{ANNA_ID}/sessions",
                headers={
                    **cookie_header(refreshed_token),
                    "X-Request-ID": f"poc042:admin-revoke:{uuid4()}",
                },
            )
            if revoked.status_code != 200 or revoked.json().get("revokedCount") != 1:
                raise ContractFailure("admin session revocation had no effect")
            stolen = await client.get(
                "/api/v1/identity/me",
                headers={
                    **cookie_header(anna_token),
                    "X-Request-ID": f"poc042:stolen:{uuid4()}",
                },
            )
            if stolen.status_code != 401:
                raise ContractFailure("stolen cookie stayed valid after revocation")

            logout = await client.post(
                "/api/v1/auth/logout",
                headers={
                    **cookie_header(refreshed_token),
                    "X-Request-ID": f"poc042:logout:{uuid4()}",
                },
            )
            if logout.status_code != 200 or logout.json() != {"status": "signed_out"}:
                raise ContractFailure("logout response is invalid")
            cleared = [
                value
                for value in logout.headers.get_list("set-cookie")
                if value.startswith(f"{SESSION_COOKIE_NAME}=")
            ]
            if len(cleared) != 1 or "Max-Age=0" not in cleared[0]:
                raise ContractFailure("logout does not clear the secure cookie")
            after_logout = await client.get(
                "/api/v1/identity/me",
                headers={
                    **cookie_header(refreshed_token),
                    "X-Request-ID": f"poc042:after-logout:{uuid4()}",
                },
            )
            if after_logout.status_code != 401:
                raise ContractFailure("logout did not revoke the session immediately")

            expired_token = secrets.token_urlsafe(48)
            explicit_now = datetime.now(timezone.utc)
            await connection.execute(
                """
                INSERT INTO user_session (
                    id, user_id, token_digest, expires_at, last_seen_at,
                    fresh_login_at, device_hint, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, 'POC-042 expired',
                        $6, $5)
                """,
                uuid4(),
                ANNA_ID,
                hashlib.sha256(expired_token.encode()).hexdigest(),
                explicit_now - timedelta(days=1),
                explicit_now - timedelta(days=2),
                explicit_now - timedelta(days=91),
            )
            expired = await client.get(
                "/api/v1/identity/me",
                headers={
                    **cookie_header(expired_token),
                    "X-Request-ID": f"poc042:expired:{uuid4()}",
                },
            )
            if expired.status_code != 401:
                raise ContractFailure("explicitly expired session stayed valid")

            leaked = await connection.fetchval(
                """
                SELECT count(*)
                FROM outbox_event
                WHERE aggregate_type = 'login_challenge'
                  AND (
                    payload::text ILIKE '%anna.akquise%'
                    OR payload::text ILIKE '%system-admin%'
                    OR payload::text LIKE $1
                    OR payload::text LIKE $2
                  )
                """,
                f"%{anna_magic}%",
                f"%{anna_code}%",
            )
            audit_leaks = await connection.fetchval(
                """
                SELECT count(*)
                FROM audit_event
                WHERE event_type LIKE 'identity.%'
                  AND (
                    payload::text ILIKE '%@leonaid.invalid%'
                    OR payload::text LIKE $1
                    OR payload::text LIKE $2
                  )
                """,
                f"%{system_token}%",
                f"%{fresh_code}%",
            )
            if leaked != 0 or audit_leaks != 0:
                raise ContractFailure("outbox or audit contains login secrets")
    finally:
        await connection.close()


def main() -> int:
    try:
        asyncio.run(run())
    except (
        ContractFailure,
        KeyError,
        OSError,
        asyncpg.PostgresError,
        httpx.HTTPError,
    ) as error:
        print(
            f"session-contract: ERROR: type={type(error).__name__} detail={error}",
            file=sys.stderr,
        )
        return 1
    print(
        "session-contract: 90 days, fresh login, rotation, logout and "
        "admin revocation proven against real services"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
