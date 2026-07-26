#!/usr/bin/env python3
"""Prove POC-040 identity behavior against real PostgreSQL and FastAPI."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.identity import AsyncpgIdentityRepository
from leonaid.adapters.postgres.pool import create_pool
from leonaid.application.errors import PermissionDenied
from leonaid.application.identity import IdentityAdministrationService
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
)

SYSTEM_ID = UUID("10000000-0000-4000-8000-000000000001")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
GESA_ID = UUID("10000000-0000-4000-8000-000000000008")
FOREIGN_ACTION_ID = UUID("20000000-0000-4000-8000-000000000003")
TEMPORARY_MEMBERSHIP_ID = UUID("21000000-0000-4000-8000-000000000040")


class ContractFailure(RuntimeError):
    """The real identity stack violated the POC-040 contract."""


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
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
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
        VALUES ($1, $2, $3, $4, $5, $5, 'POC-040 real contract', $5, $5)
        """,
        uuid4(),
        user_id,
        digest,
        now + timedelta(days=90),
        now,
    )
    return token


async def identity_response(
    client: httpx.AsyncClient,
    token: str,
) -> httpx.Response:
    return await client.get(
        "/api/v1/identity/me",
        cookies={"leonaid_session": token},
        headers={"X-Request-ID": f"poc040:http:{uuid4()}"},
    )


def require_identity(
    response: httpx.Response,
    *,
    display_name: str,
) -> dict[str, Any]:
    if response.status_code != 200:
        raise ContractFailure(
            f"Identitätsabfrage für {display_name} lieferte "
            f"HTTP {response.status_code}: {response.text[:300]}"
        )
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("displayName") != display_name:
        raise ContractFailure(f"Identitätsantwort für {display_name} ist ungültig")
    if response.headers.get("cache-control") != "no-store":
        raise ContractFailure("Identitätsantwort ist nicht gegen Caching geschützt")
    return payload


def navigation_keys(payload: dict[str, Any], surface: str) -> set[str]:
    navigation = payload.get("navigation")
    if not isinstance(navigation, list):
        raise ContractFailure("Identitätsantwort enthält keine Navigation")
    return {
        str(item["key"])
        for item in navigation
        if isinstance(item, dict) and item.get("surface") == surface
    }


async def run(arguments: argparse.Namespace) -> None:
    database_url = require_env("CORE_DATABASE_URL")
    now = datetime.now(timezone.utc)
    connection = await asyncpg.connect(database_url, timeout=10)
    try:
        await connection.execute(
            "DELETE FROM audit_event WHERE request_id LIKE 'poc040:%'"
        )
        await connection.execute(
            "DELETE FROM user_session WHERE device_hint = 'POC-040 real contract'"
        )
        tokens = {
            "SYSTEM_SESSION": await create_session(connection, SYSTEM_ID, now=now),
            "KLARA_SESSION": await create_session(connection, KLARA_ID, now=now),
            "ANNA_OLD_SESSION": await create_session(connection, ANNA_ID, now=now),
            "GESA_SESSION": await create_session(connection, GESA_ID, now=now),
        }
        original_anna_email = await connection.fetchval(
            "SELECT email FROM user_account WHERE id = $1",
            ANNA_ID,
        )
    finally:
        await connection.close()

    pool = await create_pool(database_url, minimum_size=1, maximum_size=3)
    repository = AsyncpgIdentityRepository(pool)
    administration = IdentityAdministrationService(repository)
    base_url = require_env("LEONAID_API_BASE_URL").rstrip("/")
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
            system_payload = require_identity(
                await identity_response(client, tokens["SYSTEM_SESSION"]),
                display_name="Simone System",
            )
            klara_payload = require_identity(
                await identity_response(client, tokens["KLARA_SESSION"]),
                display_name="Klara Kern",
            )
            anna_payload = require_identity(
                await identity_response(client, tokens["ANNA_OLD_SESSION"]),
                display_name="Anna Akquise",
            )
            if (
                system_payload.get("globalRoles") != ["system_admin"]
                or system_payload.get("actionMemberships") != []
                or "system" not in navigation_keys(system_payload, "web")
            ):
                raise ContractFailure(
                    "globale Systemrolle ist nicht sauber von Aktionen getrennt"
                )
            klara_memberships = klara_payload.get("actionMemberships")
            if (
                not isinstance(klara_memberships, list)
                or len(klara_memberships) != 2
                or {item.get("role") for item in klara_memberships} != {"charity_admin"}
                or "system" in navigation_keys(klara_payload, "web")
                or "members" not in navigation_keys(klara_payload, "web")
            ):
                raise ContractFailure(
                    "aktionsbezogene Charity-Admin-Sicht ist nicht korrekt"
                )
            if navigation_keys(anna_payload, "pwa") != {
                "overview-pwa",
                "sponsors",
                "activities",
                "commitment",
            } or navigation_keys(anna_payload, "web") != {"overview-web"}:
                raise ContractFailure("Akquisiteur-Navigation enthält falsche Bereiche")

            suspended = await identity_response(client, tokens["GESA_SESSION"])
            if (
                suspended.status_code != 401
                or suspended.json().get("error", {}).get("code") != "session_invalid"
            ):
                raise ContractFailure("gesperrtes Golden-Konto erhielt Zugriff")

            email_attempt = await client.patch(
                "/api/v1/identity/me",
                json={"email": "andere@leonaid.invalid"},
                cookies={"leonaid_session": tokens["ANNA_OLD_SESSION"]},
            )
            if email_attempt.status_code != 405:
                raise ContractFailure(
                    "Login-E-Mail besitzt unerwartet einen Self-Service"
                )

        system = await repository.principal_for_session(
            hashlib.sha256(tokens["SYSTEM_SESSION"].encode()).hexdigest(),
            now=now,
        )
        klara = await repository.principal_for_session(
            hashlib.sha256(tokens["KLARA_SESSION"].encode()).hexdigest(),
            now=now,
        )
        if system is None or klara is None:
            raise ContractFailure("reale Admin-Principals konnten nicht geladen werden")

        try:
            await administration.add_global_role(
                klara,
                ANNA_ID,
                GlobalRole.FINANCE_READER,
                request_id="poc040:forbidden:global-role",
            )
        except PermissionDenied:
            pass
        else:
            raise ContractFailure("Charity-Admin durfte globale Rolle vergeben")

        if not await administration.add_global_role(
            system,
            KLARA_ID,
            GlobalRole.FINANCE_READER,
            request_id="poc040:global-role:grant",
        ):
            raise ContractFailure("globale Rolle wurde nicht hinzugefügt")
        if await administration.add_global_role(
            system,
            KLARA_ID,
            GlobalRole.FINANCE_READER,
            request_id="poc040:global-role:duplicate",
        ):
            raise ContractFailure("doppelte globale Rolle wurde erneut angelegt")

        membership = ActionMembership(
            id=TEMPORARY_MEMBERSHIP_ID,
            action_id=FOREIGN_ACTION_ID,
            action_name="Krapfentaxi Nord 2026",
            user_id=KLARA_ID,
            role=ActionRole.FINANCE_READER,
            active_from=now,
        )
        if not await administration.add_action_membership(
            system,
            membership,
            request_id="poc040:membership:grant",
        ):
            raise ContractFailure("zweite Aktionsrolle wurde nicht hinzugefügt")
        if await administration.add_action_membership(
            system,
            membership,
            request_id="poc040:membership:duplicate",
        ):
            raise ContractFailure("doppelte Aktionsrolle wurde erneut angelegt")

        klara_with_roles = await repository.principal_for_session(
            hashlib.sha256(tokens["KLARA_SESSION"].encode()).hexdigest(),
            now=now,
        )
        if (
            klara_with_roles is None
            or klara_with_roles.global_roles != frozenset({GlobalRole.FINANCE_READER})
            or len(klara_with_roles.action_memberships) != 3
            or klara_with_roles.roles_for(FOREIGN_ACTION_ID)
            != frozenset({ActionRole.FINANCE_READER})
        ):
            raise ContractFailure(
                "mehrere globale/Aktionsrollen wurden nicht getrennt persistiert"
            )

        if not await administration.remove_action_membership(
            system,
            TEMPORARY_MEMBERSHIP_ID,
            request_id="poc040:membership:revoke",
        ):
            raise ContractFailure("temporäre Aktionsrolle wurde nicht entfernt")
        if not await administration.remove_global_role(
            system,
            KLARA_ID,
            GlobalRole.FINANCE_READER,
            request_id="poc040:global-role:revoke",
        ):
            raise ContractFailure("temporäre globale Rolle wurde nicht entfernt")

        changed = await administration.change_status(
            system,
            ANNA_ID,
            AccountStatus.SUSPENDED,
            request_id="poc040:status:suspend",
        )
        if changed.status is not AccountStatus.SUSPENDED:
            raise ContractFailure("Suspendierung wurde nicht persistiert")
        async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
            denied = await identity_response(client, tokens["ANNA_OLD_SESSION"])
            if denied.status_code != 401:
                raise ContractFailure(
                    "bestehende Sitzung blieb nach Suspendierung wirksam"
                )

        await administration.change_status(
            system,
            ANNA_ID,
            AccountStatus.ACTIVE,
            request_id="poc040:status:reactivate",
        )
        async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
            still_denied = await identity_response(client, tokens["ANNA_OLD_SESSION"])
            if still_denied.status_code != 401:
                raise ContractFailure(
                    "widerrufene alte Sitzung lebte nach Reaktivierung wieder auf"
                )

        connection = await asyncpg.connect(database_url, timeout=10)
        try:
            tokens["ANNA_SESSION"] = await create_session(
                connection,
                ANNA_ID,
                now=datetime.now(timezone.utc),
            )
            current_anna_email = await connection.fetchval(
                "SELECT email FROM user_account WHERE id = $1",
                ANNA_ID,
            )
            audit_rows = await connection.fetch(
                """
                SELECT event_type, payload::text AS payload
                FROM audit_event
                WHERE request_id LIKE 'poc040:%'
                  AND request_id <> 'poc040:forbidden:global-role'
                ORDER BY occurred_at, event_type
                """
            )
        finally:
            await connection.close()
        if current_anna_email != original_anna_email:
            raise ContractFailure("Login-E-Mail wurde verändert")
        event_types = [str(row["event_type"]) for row in audit_rows]
        if sorted(event_types) != sorted(
            [
                "identity.global_role.granted",
                "identity.global_role.revoked",
                "identity.action_membership.granted",
                "identity.action_membership.revoked",
                "identity.account.status_changed",
                "identity.account.status_changed",
            ]
        ):
            raise ContractFailure(f"AuditEvents sind unvollständig: {event_types}")
        if any("email" in str(row["payload"]).casefold() for row in audit_rows):
            raise ContractFailure("AuditEvent enthält unerwartet eine E-Mail")

        output = arguments.session_output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "\n".join(
                f"{name}={value}"
                for name, value in tokens.items()
                if name in {"SYSTEM_SESSION", "KLARA_SESSION", "ANNA_SESSION"}
            )
            + "\n",
            encoding="utf-8",
        )
        output.chmod(0o600)
    finally:
        await pool.close()

    print(
        "identity-contract: Rollen, Mehrfachmitgliedschaften, Audit, "
        "E-Mail-Grenze und sofortiger Sitzungsentzug real bewiesen"
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
        print(f"identity-contract: ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
