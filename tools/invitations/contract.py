#!/usr/bin/env python3
"""Prove POC-041 against real FastAPI, PostgreSQL, worker SMTP and Mailpit."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

SYSTEM_ID = UUID("10000000-0000-4000-8000-000000000001")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
FOREIGN_ACTION_ID = UUID("20000000-0000-4000-8000-000000000003")
CODE_USER_ID = UUID("10000000-0000-4000-8000-000000000041")
EMAIL_CHANGE_USER_ID = UUID("10000000-0000-4000-8000-000000000042")
UI_EMAIL_CONFIRM_USER_ID = UUID("10000000-0000-4000-8000-000000000043")
UI_EMAIL_START_USER_ID = UUID("10000000-0000-4000-8000-000000000044")
EXPIRED_INVITATION_ID = UUID("41000000-0000-4000-8000-000000000099")
EXPIRED_EMAIL_CHANGE_ID = UUID("71000000-0000-4000-8000-000000000099")
LINK_EMAIL = "link-pilot@leonaid.invalid"
CODE_EMAIL = "code-pilot@leonaid.invalid"
REVOKED_EMAIL = "revoked-pilot@leonaid.invalid"
BRUTE_FORCE_EMAIL = "code-limit-pilot@leonaid.invalid"
REISSUE_EMAIL = "reissue-pilot@leonaid.invalid"
CORRECTED_EMAIL = "reissue-corrected-pilot@leonaid.invalid"
UI_RESEND_EMAIL = "ui-resend-pilot@leonaid.invalid"
UI_CORRECT_EMAIL = "ui-correct-pilot@leonaid.invalid"
UI_REVOKE_EMAIL = "ui-revoke-pilot@leonaid.invalid"
FOREIGN_EMAIL = "foreign-lifecycle-pilot@leonaid.invalid"
EMAIL_CHANGE_OLD = "email-change-old@leonaid.invalid"
EMAIL_CHANGE_NEW = "email-change-new@leonaid.invalid"
UI_EMAIL_CONFIRM_OLD = "ui-email-confirm-old@leonaid.invalid"
UI_EMAIL_CONFIRM_NEW = "ui-email-confirm-new@leonaid.invalid"
UI_EMAIL_START_OLD = "ui-email-start-old@leonaid.invalid"
EXPIRED_EMAIL_CHANGE_NEW = "expired-email-change@leonaid.invalid"
TOKEN_PATTERN = re.compile(r"/invite\?token=([A-Za-z0-9_-]{32,256})")
EMAIL_CHANGE_TOKEN_PATTERN = re.compile(r"/email-change\?token=([A-Za-z0-9_-]{32,256})")
CODE_PATTERN = re.compile(r"\bCode ([0-9]{6})\b")


class ContractFailure(RuntimeError):
    """The live invitation stack violated its product contract."""


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"erforderliche Umgebungsvariable fehlt: {name}")
    return value


async def create_session(
    connection: asyncpg.Connection[Any],
    user_id: UUID,
    *,
    now: datetime,
) -> str:
    token = secrets.token_urlsafe(48)
    await connection.execute(
        """
        INSERT INTO user_session (
            id,
            user_id,
            token_digest,
            expires_at,
            last_seen_at,
            fresh_login_at,
            device_hint,
            created_at,
            updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $5, 'POC-041 real contract', $5, $5)
        """,
        uuid4(),
        user_id,
        hashlib.sha256(token.encode()).hexdigest(),
        now + timedelta(days=90),
        now,
    )
    return token


def cookies(token: str) -> dict[str, str]:
    return {"__Host-leonaid_session": token}


async def create_invitation(
    client: httpx.AsyncClient,
    token: str,
    *,
    action_id: UUID,
    email: str,
    display_name: str,
    role: str,
) -> tuple[UUID, dict[str, Any]]:
    response = await client.post(
        "/api/v1/invitations",
        cookies=cookies(token),
        headers={"X-Request-ID": f"poc041:create:{uuid4()}"},
        json={
            "actionId": str(action_id),
            "email": email,
            "displayName": display_name,
            "role": role,
        },
    )
    if response.status_code != 202:
        raise ContractFailure(
            f"Einladung an {email} lieferte HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )
    payload = response.json()
    if set(payload) != {"invitationId", "status"} or payload["status"] != "queued":
        raise ContractFailure("Einladungsantwort verrät unerwartete Kontoinformationen")
    return UUID(str(payload["invitationId"])), payload


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


async def wait_for_mail(
    mailpit: httpx.AsyncClient,
    recipient: str,
) -> tuple[str, dict[str, Any]]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = await mailpit.get("/api/v1/messages")
        response.raise_for_status()
        payload = response.json()
        messages = payload.get("messages") if isinstance(payload, dict) else None
        if isinstance(messages, list):
            for summary in messages:
                if isinstance(
                    summary, dict
                ) and recipient.casefold() in recipient_addresses(summary.get("To")):
                    message_id = summary.get("ID")
                    if not isinstance(message_id, str):
                        continue
                    detail_response = await mailpit.get(f"/api/v1/message/{message_id}")
                    detail_response.raise_for_status()
                    detail = detail_response.json()
                    if not isinstance(detail, dict):
                        raise ContractFailure("Mailpit-Nachricht ist kein Objekt")
                    text = detail.get("Text")
                    if not isinstance(text, str):
                        raise ContractFailure("Mailpit-Nachricht enthält keinen Text")
                    return text, detail
        await asyncio.sleep(0.2)
    raise ContractFailure(f"Mail an {recipient} wurde nicht rechtzeitig zugestellt")


def credentials_from_mail(text: str) -> tuple[str, str]:
    token = TOKEN_PATTERN.search(text)
    code = CODE_PATTERN.search(text)
    if token is None or code is None:
        raise ContractFailure("Einladungsmail enthält nicht Link und Code")
    return token.group(1), code.group(1)


def email_change_credentials_from_mail(text: str) -> tuple[str, str]:
    token = EMAIL_CHANGE_TOKEN_PATTERN.search(text)
    code = CODE_PATTERN.search(text)
    if token is None or code is None:
        raise ContractFailure("E-Mail-Korrektur enthält nicht Link und Code")
    return token.group(1), code.group(1)


async def require_invalid(
    response: httpx.Response,
    label: str,
) -> None:
    if (
        response.status_code != 400
        or response.json().get("error", {}).get("code") != "invitation_invalid"
    ):
        raise ContractFailure(f"{label} wurde nicht generisch abgewiesen")


async def verify_accepted(
    connection: asyncpg.Connection[Any],
    *,
    invitation_id: UUID,
    email: str,
    method: str,
    role: str,
) -> None:
    row = await connection.fetchrow(
        """
        SELECT
          invitation.status,
          invitation.accepted_via,
          account.status AS account_status,
          account.email_verified_at IS NOT NULL AS verified,
          membership.role AS membership_role
        FROM action_invitation AS invitation
        JOIN user_account AS account
          ON account.id = invitation.accepted_user_id
        JOIN action_membership AS membership
          ON membership.action_id = invitation.action_id
         AND membership.user_id = account.id
         AND membership.role = invitation.role_snapshot
        WHERE invitation.id = $1
          AND account.email = $2
        """,
        invitation_id,
        email,
    )
    expected = {
        "status": "accepted",
        "accepted_via": method,
        "account_status": "active",
        "verified": True,
        "membership_role": role,
    }
    if row is None or dict(row) != expected:
        raise ContractFailure(f"Annahme war nicht atomar sichtbar: {dict(row or {})}")


async def run(arguments: argparse.Namespace) -> None:
    database_url = require_env("CORE_DATABASE_URL")
    api_url = require_env("LEONAID_API_BASE_URL").rstrip("/")
    mailpit_url = require_env("MAIL_TEST_API_URL").rstrip("/")
    now = datetime.now(timezone.utc)
    connection = await asyncpg.connect(database_url, timeout=10)
    try:
        await connection.execute(
            "DELETE FROM user_session WHERE device_hint = 'POC-041 real contract'"
        )
        await connection.execute(
            """
            INSERT INTO user_account (
                id, email, display_name, status, created_at, updated_at
            )
            VALUES ($1, $2, 'Code Pilot', 'invited', $3, $3)
            """,
            CODE_USER_ID,
            CODE_EMAIL,
            now,
        )
        await connection.executemany(
            """
            INSERT INTO user_account (
                id, email, display_name, status,
                email_verified_at, created_at, updated_at
            )
            VALUES ($1, $2, $3, 'active', $4, $4, $4)
            """,
            (
                (
                    EMAIL_CHANGE_USER_ID,
                    EMAIL_CHANGE_OLD,
                    "E-Mail Wechsel Real",
                    now,
                ),
                (
                    UI_EMAIL_CONFIRM_USER_ID,
                    UI_EMAIL_CONFIRM_OLD,
                    "E-Mail Bestätigung UI",
                    now,
                ),
                (
                    UI_EMAIL_START_USER_ID,
                    UI_EMAIL_START_OLD,
                    "E-Mail Korrektur UI",
                    now,
                ),
            ),
        )
        email_session_one = await create_session(
            connection,
            EMAIL_CHANGE_USER_ID,
            now=now,
        )
        email_session_two = await create_session(
            connection,
            EMAIL_CHANGE_USER_ID,
            now=now,
        )
        system_session = await create_session(connection, SYSTEM_ID, now=now)
        klara_session = await create_session(connection, KLARA_ID, now=now)
        expired_email_token = secrets.token_urlsafe(32)
        await connection.execute(
            """
            INSERT INTO email_change_request (
              id, user_id, requested_by_user_id,
              old_email_snapshot, new_email_snapshot,
              display_name_snapshot, status, token_digest, code_digest,
              expires_at, created_at, updated_at
            )
            VALUES (
              $1, $2, $3, $4, $5, 'E-Mail Korrektur UI', 'pending',
              $6, $7, $8, $9, $9
            )
            """,
            EXPIRED_EMAIL_CHANGE_ID,
            UI_EMAIL_START_USER_ID,
            SYSTEM_ID,
            UI_EMAIL_START_OLD,
            EXPIRED_EMAIL_CHANGE_NEW,
            hashlib.sha256(expired_email_token.encode()).hexdigest(),
            hashlib.sha256(b"expired-email-change-code").hexdigest(),
            now - timedelta(minutes=1),
            now - timedelta(minutes=31),
        )
    finally:
        await connection.close()

    async with (
        httpx.AsyncClient(base_url=api_url, timeout=20) as client,
        httpx.AsyncClient(base_url=mailpit_url, timeout=10) as mailpit,
    ):
        await mailpit.delete("/api/v1/messages")

        expired_email_change = await client.post(
            "/api/v1/email-changes/confirm",
            json={"magicToken": expired_email_token},
        )
        if (
            expired_email_change.status_code != 400
            or expired_email_change.json().get("error", {}).get("code")
            != "email_change_invalid"
        ):
            raise ContractFailure(
                "Abgelaufene E-Mail-Bestätigung wurde nicht generisch abgewiesen"
            )

        klara_options = await client.get(
            "/api/v1/invitations/options",
            cookies=cookies(klara_session),
        )
        if klara_options.status_code != 200 or {
            UUID(str(item["id"])) for item in klara_options.json().get("actions", [])
        } != {ACTION_ID}:
            raise ContractFailure("Charity-Admin erhielt fremde Einladungsoptionen")
        system_options = await client.get(
            "/api/v1/invitations/options",
            cookies=cookies(system_session),
        )
        if system_options.status_code != 200 or {
            UUID(str(item["id"])) for item in system_options.json().get("actions", [])
        } != {ACTION_ID, FOREIGN_ACTION_ID}:
            raise ContractFailure("System-Admin erhielt nicht alle aktiven Optionen")

        forbidden = await client.post(
            "/api/v1/invitations",
            cookies=cookies(klara_session),
            json={
                "actionId": str(FOREIGN_ACTION_ID),
                "email": "foreign-direct@leonaid.invalid",
                "displayName": "Foreign Direct",
                "role": "acquirer",
            },
        )
        if (
            forbidden.status_code != 403
            or forbidden.json().get("error", {}).get("code")
            != "invitation_action_forbidden"
        ):
            raise ContractFailure("Direkter Fremdaktions-Request wurde nicht verboten")

        link_id, link_dispatch = await create_invitation(
            client,
            klara_session,
            action_id=ACTION_ID,
            email=LINK_EMAIL,
            display_name="Link Pilot",
            role="acquirer",
        )
        link_text, _link_mail = await wait_for_mail(mailpit, LINK_EMAIL)
        link_token, link_code = credentials_from_mail(link_text)
        duplicate_link_id, _ = await create_invitation(
            client,
            klara_session,
            action_id=ACTION_ID,
            email=LINK_EMAIL,
            display_name="Andere Wiederholung",
            role="acquirer",
        )
        if duplicate_link_id != link_id:
            raise ContractFailure("Wiederholte Einladung erzeugte zweite Zugangsdaten")

        code_id, code_dispatch = await create_invitation(
            client,
            klara_session,
            action_id=ACTION_ID,
            email=CODE_EMAIL,
            display_name="Code Pilot Snapshot",
            role="driver",
        )
        code_text, _code_mail = await wait_for_mail(mailpit, CODE_EMAIL)
        code_token, code_value = credentials_from_mail(code_text)
        if set(link_dispatch) != set(code_dispatch):
            raise ContractFailure("Account-Existenz verändert die Antwortstruktur")

        revoked_id, _ = await create_invitation(
            client,
            klara_session,
            action_id=ACTION_ID,
            email=REVOKED_EMAIL,
            display_name="Revoked Pilot",
            role="finance_reader",
        )
        revoked_text, _revoked_mail = await wait_for_mail(mailpit, REVOKED_EMAIL)
        revoked_token, _revoked_code = credentials_from_mail(revoked_text)

        code_limit_id, _ = await create_invitation(
            client,
            klara_session,
            action_id=ACTION_ID,
            email=BRUTE_FORCE_EMAIL,
            display_name="Code Limit Pilot",
            role="acquirer",
        )
        code_limit_text, _code_limit_mail = await wait_for_mail(
            mailpit,
            BRUTE_FORCE_EMAIL,
        )
        code_limit_token, code_limit_value = credentials_from_mail(code_limit_text)
        wrong_code = "999999" if code_limit_value != "999999" else "000000"
        brute_force_headers = {"User-Agent": "LeonAid-POC041-invitation-lock-contract"}
        for attempt in range(5):
            await require_invalid(
                await client.post(
                    "/api/v1/invitations/accept",
                    headers={
                        **brute_force_headers,
                        "X-Request-ID": f"poc041:code-limit:{attempt + 1}",
                    },
                    json={
                        "email": BRUTE_FORCE_EMAIL,
                        "code": wrong_code,
                    },
                ),
                f"falscher Codeversuch {attempt + 1}",
            )
        await require_invalid(
            await client.post(
                "/api/v1/invitations/accept",
                headers=brute_force_headers,
                json={
                    "email": BRUTE_FORCE_EMAIL,
                    "code": code_limit_value,
                },
            ),
            "richtiger Code nach Fehlversuchssperre",
        )
        await require_invalid(
            await client.post(
                "/api/v1/invitations/accept",
                headers=brute_force_headers,
                json={"magicToken": code_limit_token},
            ),
            "Magic Link nach Fehlversuchssperre",
        )

        connection = await asyncpg.connect(database_url, timeout=10)
        try:
            stored = await connection.fetchrow(
                """
                SELECT
                  invitation.email_snapshot,
                  invitation.display_name_snapshot,
                  invitation.action_name_snapshot,
                  invitation.invited_by_name_snapshot,
                  invitation.role_snapshot,
                  invitation.token_digest,
                  invitation.code_digest,
                  event.payload::text AS outbox_payload
                FROM action_invitation AS invitation
                JOIN outbox_event AS event
                  ON event.aggregate_id = invitation.id
                 AND event.aggregate_type = 'action_invitation'
                WHERE invitation.id = $1
                """,
                link_id,
            )
            if stored is None:
                raise ContractFailure("Einladungs-Snapshot oder Outbox fehlt")
            outbox_count = await connection.fetchval(
                """
                SELECT count(*)
                FROM outbox_event
                WHERE aggregate_type = 'action_invitation'
                  AND aggregate_id = $1
                """,
                link_id,
            )
            if outbox_count != 1:
                raise ContractFailure("Idempotente Einladung erzeugte mehrere Mails")
            if {
                "email_snapshot": stored["email_snapshot"],
                "display_name_snapshot": stored["display_name_snapshot"],
                "action_name_snapshot": stored["action_name_snapshot"],
                "invited_by_name_snapshot": stored["invited_by_name_snapshot"],
                "role_snapshot": stored["role_snapshot"],
            } != {
                "email_snapshot": LINK_EMAIL,
                "display_name_snapshot": "Link Pilot",
                "action_name_snapshot": "Krapfentaxi 2026",
                "invited_by_name_snapshot": "Klara Kern",
                "role_snapshot": "acquirer",
            }:
                raise ContractFailure("Einladungs-Snapshots sind unvollständig")
            if (
                stored["token_digest"]
                != hashlib.sha256(link_token.encode()).hexdigest()
            ):
                raise ContractFailure("Magic Token wurde nicht passend gehasht")
            if (
                len(str(stored["code_digest"])) != 64
                or stored["code_digest"]
                == hashlib.sha256(link_code.encode()).hexdigest()
            ):
                raise ContractFailure("Code-Digest ist nicht geeignet gepeppert")
            payload_text = str(stored["outbox_payload"])
            if (
                set(json.loads(payload_text)) != {"secureMail"}
                or link_token in payload_text
                or link_code in payload_text
                or LINK_EMAIL in payload_text
            ):
                raise ContractFailure("Outbox speichert Einladung im Klartext")
            try:
                await connection.execute(
                    """
                    UPDATE action_invitation
                    SET action_name_snapshot = 'Manipuliert'
                    WHERE id = $1
                    """,
                    link_id,
                )
            except asyncpg.CheckViolationError:
                pass
            else:
                raise ContractFailure("Einladungs-Snapshot war veränderlich")

            expired_token = secrets.token_urlsafe(32)
            await connection.execute(
                """
                INSERT INTO action_invitation (
                    id,
                    action_id,
                    invited_by_user_id,
                    email_snapshot,
                    display_name_snapshot,
                    action_name_snapshot,
                    invited_by_name_snapshot,
                    role_snapshot,
                    status,
                    token_digest,
                    code_digest,
                    expires_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    $1, $2, $3, 'expired-pilot@leonaid.invalid',
                    'Expired Pilot', 'Krapfentaxi 2026', 'Klara Kern',
                    'acquirer', 'pending', $4, $5, $6, $7, $7
                )
                """,
                EXPIRED_INVITATION_ID,
                ACTION_ID,
                KLARA_ID,
                hashlib.sha256(expired_token.encode()).hexdigest(),
                "e" * 64,
                now - timedelta(minutes=5),
                now - timedelta(minutes=10),
            )
        finally:
            await connection.close()

        accepted_link = await client.post(
            "/api/v1/invitations/accept",
            json={"magicToken": link_token},
        )
        if (
            accepted_link.status_code != 200
            or accepted_link.json().get("role") != "acquirer"
        ):
            raise ContractFailure("Magic Link wurde nicht angenommen")
        await require_invalid(
            await client.post(
                "/api/v1/invitations/accept",
                json={"magicToken": link_token},
            ),
            "wiederverwendeter Magic Link",
        )
        await require_invalid(
            await client.post(
                "/api/v1/invitations/accept",
                json={"email": LINK_EMAIL, "code": link_code},
            ),
            "Code einer bereits per Link angenommenen Einladung",
        )

        accepted_code = await client.post(
            "/api/v1/invitations/accept",
            json={"email": CODE_EMAIL, "code": code_value},
        )
        if (
            accepted_code.status_code != 200
            or accepted_code.json().get("role") != "driver"
        ):
            raise ContractFailure(
                "Sechsstelliger Code wurde nicht angenommen: "
                f"HTTP {accepted_code.status_code} {accepted_code.text[:300]}"
            )
        await require_invalid(
            await client.post(
                "/api/v1/invitations/accept",
                json={"email": CODE_EMAIL, "code": code_value},
            ),
            "wiederverwendeter Code",
        )
        await require_invalid(
            await client.post(
                "/api/v1/invitations/accept",
                json={"magicToken": code_token},
            ),
            "Link einer bereits per Code angenommenen Einladung",
        )

        revoked = await client.delete(
            f"/api/v1/invitations/{revoked_id}",
            cookies=cookies(klara_session),
        )
        if revoked.status_code != 200 or revoked.json() != {"status": "revoked"}:
            raise ContractFailure("Einladung wurde nicht widerrufen")
        await require_invalid(
            await client.post(
                "/api/v1/invitations/accept",
                json={"magicToken": revoked_token},
            ),
            "widerrufene Einladung",
        )
        await require_invalid(
            await client.post(
                "/api/v1/invitations/accept",
                json={"magicToken": expired_token},
            ),
            "abgelaufene Einladung",
        )
        await require_invalid(
            await client.post(
                "/api/v1/invitations/accept",
                json={
                    "email": "unknown@leonaid.invalid",
                    "code": "000000",
                },
            ),
            "unbekanntes Konto",
        )

        foreign_id, _ = await create_invitation(
            client,
            system_session,
            action_id=FOREIGN_ACTION_ID,
            email=FOREIGN_EMAIL,
            display_name="Foreign Lifecycle Pilot",
            role="acquirer",
        )
        lifecycle_id, _ = await create_invitation(
            client,
            klara_session,
            action_id=ACTION_ID,
            email=REISSUE_EMAIL,
            display_name="Reissue Pilot",
            role="acquirer",
        )
        lifecycle_text, _ = await wait_for_mail(mailpit, REISSUE_EMAIL)
        lifecycle_token, _ = credentials_from_mail(lifecycle_text)

        klara_list = await client.get(
            "/api/v1/invitations",
            cookies=cookies(klara_session),
        )
        if klara_list.status_code != 200:
            raise ContractFailure("Charity-Admin konnte Einladungen nicht auflisten")
        klara_items = klara_list.json().get("items", [])
        if (
            not klara_items
            or {UUID(str(item["actionId"])) for item in klara_items} != {ACTION_ID}
            or foreign_id in {UUID(str(item["id"])) for item in klara_items}
            or {"pending", "accepted", "expired", "revoked"}
            - {str(item["status"]) for item in klara_items}
        ):
            raise ContractFailure(
                "Einladungsliste verletzt Aktionsscope oder Lifecycle-Vollständigkeit"
            )
        system_list = await client.get(
            "/api/v1/invitations",
            cookies=cookies(system_session),
            params={"actionId": str(FOREIGN_ACTION_ID), "status": "pending"},
        )
        if system_list.status_code != 200 or foreign_id not in {
            UUID(str(item["id"])) for item in system_list.json().get("items", [])
        }:
            raise ContractFailure("System-Admin-Filter enthält die fremde Aktion nicht")

        connection = await asyncpg.connect(database_url, timeout=10)
        try:
            await connection.execute(
                """
                UPDATE action_invitation
                SET created_at = $2
                WHERE id = $1
                """,
                lifecycle_id,
                now - timedelta(minutes=2),
            )
        finally:
            await connection.close()

        await mailpit.delete("/api/v1/messages")
        reissued = await client.post(
            f"/api/v1/invitations/{lifecycle_id}/resend",
            cookies=cookies(klara_session),
            headers={"X-Request-ID": f"pilot013:resend:{uuid4()}"},
        )
        if reissued.status_code != 202:
            raise ContractFailure(
                f"Neuversand scheiterte: {reissued.status_code} {reissued.text[:300]}"
            )
        reissued_id = UUID(str(reissued.json()["invitationId"]))
        reissued_text, _ = await wait_for_mail(mailpit, REISSUE_EMAIL)
        reissued_token, _ = credentials_from_mail(reissued_text)
        if reissued_id == lifecycle_id or reissued_token == lifecycle_token:
            raise ContractFailure("Neuversand rotierte Einladung oder Token nicht")
        await require_invalid(
            await client.post(
                "/api/v1/invitations/accept",
                headers={"User-Agent": "LeonAid-PILOT013-reissue-contract"},
                json={"magicToken": lifecycle_token},
            ),
            "Link vor Neuversand",
        )
        too_soon = await client.post(
            f"/api/v1/invitations/{reissued_id}/resend",
            cookies=cookies(klara_session),
        )
        if (
            too_soon.status_code != 400
            or too_soon.json().get("error", {}).get("code")
            != "invitation_reissue_unavailable"
        ):
            raise ContractFailure("Neuversand wurde nicht zeitlich begrenzt")

        await mailpit.delete("/api/v1/messages")
        corrected = await client.post(
            f"/api/v1/invitations/{reissued_id}/correct-address",
            cookies=cookies(klara_session),
            headers={"X-Request-ID": f"pilot013:correct:{uuid4()}"},
            json={"email": CORRECTED_EMAIL},
        )
        if corrected.status_code != 202:
            raise ContractFailure(
                "Adresskorrektur scheiterte: "
                f"{corrected.status_code} {corrected.text[:300]}"
            )
        corrected_id = UUID(str(corrected.json()["invitationId"]))
        corrected_text, _ = await wait_for_mail(mailpit, CORRECTED_EMAIL)
        corrected_token, _ = credentials_from_mail(corrected_text)
        await require_invalid(
            await client.post(
                "/api/v1/invitations/accept",
                headers={"User-Agent": "LeonAid-PILOT013-correction-contract"},
                json={"magicToken": reissued_token},
            ),
            "Link vor Adresskorrektur",
        )

        ui_resend_id, _ = await create_invitation(
            client,
            klara_session,
            action_id=ACTION_ID,
            email=UI_RESEND_EMAIL,
            display_name="UI Neuversand",
            role="acquirer",
        )
        ui_correct_id, _ = await create_invitation(
            client,
            klara_session,
            action_id=ACTION_ID,
            email=UI_CORRECT_EMAIL,
            display_name="UI Adresskorrektur",
            role="driver",
        )
        ui_revoke_id, _ = await create_invitation(
            client,
            klara_session,
            action_id=ACTION_ID,
            email=UI_REVOKE_EMAIL,
            display_name="UI Widerruf",
            role="finance_reader",
        )
        connection = await asyncpg.connect(database_url, timeout=10)
        try:
            await connection.execute(
                "UPDATE action_invitation SET created_at = $2 WHERE id = $1",
                ui_resend_id,
                now - timedelta(minutes=2),
            )
            replacement_rows = await connection.fetch(
                """
                SELECT
                  id,
                  email_snapshot,
                  status,
                  supersedes_invitation_id
                FROM action_invitation
                WHERE id = ANY($1::uuid[])
                ORDER BY created_at, id
                """,
                [lifecycle_id, reissued_id, corrected_id],
            )
            expected_chain = {
                lifecycle_id: (REISSUE_EMAIL, "revoked", None),
                reissued_id: (REISSUE_EMAIL, "revoked", lifecycle_id),
                corrected_id: (CORRECTED_EMAIL, "pending", reissued_id),
            }
            if {
                row["id"]: (
                    row["email_snapshot"],
                    row["status"],
                    row["supersedes_invitation_id"],
                )
                for row in replacement_rows
            } != expected_chain:
                raise ContractFailure(
                    "Historie von Neuversand und Adresskorrektur ist nicht unveränderlich"
                )
        finally:
            await connection.close()

        await mailpit.delete("/api/v1/messages")
        login_before_change = await client.post(
            "/api/v1/auth/login",
            json={"email": EMAIL_CHANGE_OLD},
        )
        if login_before_change.status_code != 202:
            raise ContractFailure("Login-Challenge vor E-Mail-Wechsel fehlt")
        await wait_for_mail(mailpit, EMAIL_CHANGE_OLD)
        await mailpit.delete("/api/v1/messages")
        requested_change = await client.post(
            f"/api/v1/identity/members/{EMAIL_CHANGE_USER_ID}/email-change",
            cookies=cookies(system_session),
            headers={"X-Request-ID": f"pilot013:email-change:{uuid4()}"},
            json={"newEmail": EMAIL_CHANGE_NEW},
        )
        if requested_change.status_code != 202:
            raise ContractFailure(
                "E-Mail-Korrektur konnte nicht angefordert werden: "
                f"{requested_change.status_code} {requested_change.text[:300]}"
            )
        old_notice_text, _ = await wait_for_mail(mailpit, EMAIL_CHANGE_OLD)
        new_confirmation_text, _ = await wait_for_mail(mailpit, EMAIL_CHANGE_NEW)
        if "bleibt aktiv" not in old_notice_text:
            raise ContractFailure("Alte Adresse erhielt keinen Sicherheitshinweis")
        email_change_token, email_change_code = email_change_credentials_from_mail(
            new_confirmation_text
        )
        duplicate_change = await client.post(
            f"/api/v1/identity/members/{EMAIL_CHANGE_USER_ID}/email-change",
            cookies=cookies(system_session),
            json={"newEmail": "duplicate-email-change@leonaid.invalid"},
        )
        if (
            duplicate_change.status_code != 409
            or duplicate_change.json().get("error", {}).get("code")
            != "email_change_already_pending"
        ):
            raise ContractFailure(
                "Konkurrierende E-Mail-Korrektur wurde nicht abgewiesen"
            )
        occupied_change = await client.post(
            f"/api/v1/identity/members/{UI_EMAIL_START_USER_ID}/email-change",
            cookies=cookies(system_session),
            json={"newEmail": "system-admin@leonaid.invalid"},
        )
        if (
            occupied_change.status_code != 409
            or occupied_change.json().get("error", {}).get("code")
            != "email_change_address_in_use"
        ):
            raise ContractFailure("Belegte E-Mail-Adresse wurde nicht abgewiesen")
        forbidden_change = await client.post(
            f"/api/v1/identity/members/{EMAIL_CHANGE_USER_ID}/email-change",
            cookies=cookies(klara_session),
            json={"newEmail": "forbidden-change@leonaid.invalid"},
        )
        if forbidden_change.status_code != 403:
            raise ContractFailure("Charity-Admin konnte Login-E-Mail korrigieren")
        still_active = await client.get(
            "/api/v1/identity/me",
            cookies=cookies(email_session_one),
        )
        if still_active.status_code != 200:
            raise ContractFailure("Alte Adresse wurde vor Bestätigung deaktiviert")

        await mailpit.delete("/api/v1/messages")
        confirmed_change = await client.post(
            "/api/v1/email-changes/confirm",
            headers={"User-Agent": "LeonAid-PILOT013-email-change-confirm"},
            cookies=cookies(system_session),
            json={"email": EMAIL_CHANGE_NEW, "code": email_change_code},
        )
        if confirmed_change.status_code != 200 or confirmed_change.json() != {
            "status": "confirmed",
            "revokedSessionCount": 2,
        }:
            raise ContractFailure(
                "E-Mail-Korrektur wurde nicht atomar bestätigt: "
                f"{confirmed_change.status_code} {confirmed_change.text[:300]}"
            )
        if confirmed_change.headers.get("set-cookie") is not None:
            raise ContractFailure(
                "E-Mail-Bestätigung löschte die unabhängige Browser-Sitzung"
            )
        admin_still_active = await client.get(
            "/api/v1/identity/me",
            cookies=cookies(system_session),
        )
        if admin_still_active.status_code != 200:
            raise ContractFailure(
                "E-Mail-Bestätigung widerrief die unabhängige Admin-Sitzung"
            )
        replay = await client.post(
            "/api/v1/email-changes/confirm",
            headers={"User-Agent": "LeonAid-PILOT013-email-change-replay"},
            json={"magicToken": email_change_token},
        )
        if (
            replay.status_code != 400
            or replay.json().get("error", {}).get("code") != "email_change_invalid"
        ):
            raise ContractFailure("E-Mail-Bestätigung war wiederverwendbar")
        for old_session in (email_session_one, email_session_two):
            denied = await client.get(
                "/api/v1/identity/me",
                cookies=cookies(old_session),
            )
            if denied.status_code != 401:
                raise ContractFailure("Alte Sitzung blieb nach E-Mail-Wechsel aktiv")
        completed_old, _ = await wait_for_mail(mailpit, EMAIL_CHANGE_OLD)
        completed_new, _ = await wait_for_mail(mailpit, EMAIL_CHANGE_NEW)
        if "wurde bestätigt und geändert" not in completed_old or (
            "wurde bestätigt und geändert" not in completed_new
        ):
            raise ContractFailure("Abschlussinformation erreichte nicht beide Adressen")

        await mailpit.delete("/api/v1/messages")
        ui_confirm_change = await client.post(
            f"/api/v1/identity/members/{UI_EMAIL_CONFIRM_USER_ID}/email-change",
            cookies=cookies(system_session),
            headers={"X-Request-ID": f"pilot013:ui-email-confirm:{uuid4()}"},
            json={"newEmail": UI_EMAIL_CONFIRM_NEW},
        )
        if ui_confirm_change.status_code != 202:
            raise ContractFailure("UI-Bestätigungsfixture konnte nicht erstellt werden")
        ui_confirm_text, _ = await wait_for_mail(mailpit, UI_EMAIL_CONFIRM_NEW)
        ui_email_confirm_token, _ = email_change_credentials_from_mail(ui_confirm_text)

    connection = await asyncpg.connect(database_url, timeout=10)
    try:
        await verify_accepted(
            connection,
            invitation_id=link_id,
            email=LINK_EMAIL,
            method="magic_link",
            role="acquirer",
        )
        await verify_accepted(
            connection,
            invitation_id=code_id,
            email=CODE_EMAIL,
            method="code",
            role="driver",
        )
        expired_status = await connection.fetchval(
            "SELECT status FROM action_invitation WHERE id = $1",
            EXPIRED_INVITATION_ID,
        )
        expired_email_change_status = await connection.fetchval(
            "SELECT status FROM email_change_request WHERE id = $1",
            EXPIRED_EMAIL_CHANGE_ID,
        )
        revoked_status = await connection.fetchval(
            "SELECT status FROM action_invitation WHERE id = $1",
            revoked_id,
        )
        code_limit = await connection.fetchrow(
            """
            SELECT status, failed_code_attempts, last_failed_code_at IS NOT NULL AS failed
            FROM action_invitation
            WHERE id = $1
            """,
            code_limit_id,
        )
        if (
            expired_status != "expired"
            or revoked_status != "revoked"
            or expired_email_change_status != "expired"
        ):
            raise ContractFailure(
                "Terminale Einladungs- oder E-Mail-Änderungsstatus fehlen"
            )
        if code_limit is None or dict(code_limit) != {
            "status": "revoked",
            "failed_code_attempts": 5,
            "failed": True,
        }:
            raise ContractFailure("Fehlversuchssperre wurde nicht persistiert")
        email_change_state = await connection.fetchrow(
            """
            SELECT
              account.email,
              change.status,
              (
                SELECT count(*)
                FROM user_session
                WHERE user_id = account.id
                  AND revoked_at IS NULL
              ) AS active_sessions,
              (
                SELECT count(*)
                FROM login_challenge
                WHERE user_id = account.id
                  AND status = 'pending'
              ) AS pending_challenges
            FROM user_account AS account
            JOIN email_change_request AS change
              ON change.user_id = account.id
            WHERE account.id = $1
            """,
            EMAIL_CHANGE_USER_ID,
        )
        if email_change_state is None or dict(email_change_state) != {
            "email": EMAIL_CHANGE_NEW,
            "status": "confirmed",
            "active_sessions": 0,
            "pending_challenges": 0,
        }:
            raise ContractFailure(
                "E-Mail-Wechsel, Sessionentzug und Challengeentzug waren nicht atomar"
            )
        audit_payloads = await connection.fetch(
            """
            SELECT event_type, payload::text AS payload
            FROM audit_event
            WHERE event_type LIKE 'identity.invitation.%'
            ORDER BY occurred_at, event_type
            """
        )
        if not audit_payloads:
            raise ContractFailure("Einladungs-AuditEvents fehlen")
        sensitive = {
            LINK_EMAIL,
            CODE_EMAIL,
            REVOKED_EMAIL,
            BRUTE_FORCE_EMAIL,
            link_token,
            link_code,
            code_token,
            code_value,
            revoked_token,
            code_limit_token,
            code_limit_value,
            lifecycle_token,
            reissued_token,
            corrected_token,
            email_change_token,
            email_change_code,
            ui_email_confirm_token,
        }
        if any(
            secret in str(row["payload"])
            for row in audit_payloads
            for secret in sensitive
        ):
            raise ContractFailure("AuditEvent enthält Zugangsdaten oder E-Mail")
    finally:
        await connection.close()

    output = arguments.session_output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(
            (
                f"SYSTEM_SESSION={system_session}",
                f"KLARA_SESSION={klara_session}",
                f"UI_RESEND_INVITATION_ID={ui_resend_id}",
                f"UI_CORRECT_INVITATION_ID={ui_correct_id}",
                f"UI_REVOKE_INVITATION_ID={ui_revoke_id}",
                f"UI_EMAIL_CONFIRM_TOKEN={ui_email_confirm_token}",
                "",
            )
        ),
        encoding="utf-8",
    )
    output.chmod(0o600)
    print(
        "invitation-contract: Link, Code, Ablauf, Widerruf, atomare "
        "Aktivierung, Lifecycle-Liste, Neuversand, Adresskorrektur und "
        "bestätigten Login-E-Mail-Wechsel mit Sessionentzug sowie echten "
        "Outbox/SMTP-Versand bewiesen"
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--session-output", type=Path, required=True)
    return result


def main() -> int:
    try:
        asyncio.run(run(parser().parse_args()))
    except (
        ContractFailure,
        OSError,
        ValueError,
        asyncpg.PostgresError,
        httpx.HTTPError,
    ) as error:
        print(f"invitation-contract: ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
