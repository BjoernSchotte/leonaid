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
from leonaid.application.errors import Conflict, PermissionDenied
from leonaid.application.identity import IdentityAdministrationService
from leonaid.domain.identity import (
    AccountStatus,
    ActionRole,
    GlobalRole,
)

SYSTEM_ID = UUID("10000000-0000-4000-8000-000000000001")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
BERND_ID = UUID("10000000-0000-4000-8000-000000000005")
CARLA_ID = UUID("10000000-0000-4000-8000-000000000006")
FINN_ID = UUID("10000000-0000-4000-8000-000000000007")
GESA_ID = UUID("10000000-0000-4000-8000-000000000008")
ACTIVE_ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
ARCHIVED_ACTION_ID = UUID("20000000-0000-4000-8000-000000000002")
FOREIGN_ACTION_ID = UUID("20000000-0000-4000-8000-000000000003")


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
    fresh_login_at: datetime | None = None,
    created_at: datetime | None = None,
) -> str:
    token = secrets.token_urlsafe(48)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session_created_at = created_at or now
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
        VALUES ($1, $2, $3, $4, $5, $6, 'POC-040 real contract', $7, $5)
        """,
        uuid4(),
        user_id,
        digest,
        session_created_at + timedelta(days=90),
        now,
        fresh_login_at or session_created_at,
        session_created_at,
    )
    return token


async def identity_response(
    client: httpx.AsyncClient,
    token: str,
) -> httpx.Response:
    return await client.get(
        "/api/v1/identity/me",
        cookies={"__Host-leonaid_session": token},
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


def require_http(
    response: httpx.Response,
    expected_status: int,
    message: str,
) -> dict[str, Any]:
    if response.status_code != expected_status:
        raise ContractFailure(
            f"{message}: HTTP {response.status_code}: {response.text[:300]}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise ContractFailure(f"{message}: Antwort ist kein Objekt")
    return payload


async def prove_role_administration(
    pool: asyncpg.Pool[Any],
    *,
    base_url: str,
    tokens: dict[str, str],
) -> None:
    system_cookies = {"__Host-leonaid_session": tokens["SYSTEM_SESSION"]}
    stale_system_cookies = {
        "__Host-leonaid_session": tokens["SYSTEM_ROLE_STALE_SESSION"]
    }
    klara_cookies = {"__Host-leonaid_session": tokens["KLARA_SESSION"]}
    anna_cookies = {"__Host-leonaid_session": tokens["ANNA_OLD_SESSION"]}
    successful_commands: set[str] = set()

    async def member_revision(
        client: httpx.AsyncClient,
        user_id: UUID,
    ) -> int:
        payload = require_http(
            await client.get(
                f"/api/v1/admin/members/{user_id}",
                cookies=system_cookies,
            ),
            200,
            "Mitgliedsrevision konnte nicht geladen werden",
        )
        return int(payload["revision"])

    async def change_global_role(
        client: httpx.AsyncClient,
        *,
        cookies: dict[str, str],
        user_id: UUID,
        role: GlobalRole,
        enabled: bool,
        revision: int,
        command_id: str,
        expected_status: int = 200,
    ) -> dict[str, Any]:
        payload = require_http(
            await client.patch(
                f"/api/v1/admin/members/{user_id}/global-roles/{role.value}",
                cookies=cookies,
                headers={
                    "Idempotency-Key": command_id,
                    "X-Request-ID": command_id,
                },
                json={"enabled": enabled, "expectedRevision": revision},
            ),
            expected_status,
            f"Globale Rollenänderung {role.value}",
        )
        if expected_status == 200:
            successful_commands.add(command_id)
        return payload

    async def change_action_role(
        client: httpx.AsyncClient,
        *,
        cookies: dict[str, str],
        user_id: UUID,
        action_id: UUID,
        role: ActionRole,
        enabled: bool,
        revision: int,
        command_id: str,
        expected_status: int = 200,
    ) -> dict[str, Any]:
        payload = require_http(
            await client.patch(
                (
                    f"/api/v1/admin/members/{user_id}/actions/"
                    f"{action_id}/roles/{role.value}"
                ),
                cookies=cookies,
                headers={
                    "Idempotency-Key": command_id,
                    "X-Request-ID": command_id,
                },
                json={"enabled": enabled, "expectedRevision": revision},
            ),
            expected_status,
            f"Aktionsrollenänderung {role.value}",
        )
        if expected_status == 200:
            successful_commands.add(command_id)
        return payload

    async with pool.acquire() as connection:
        outbox_before = int(
            await connection.fetchval("SELECT count(*) FROM outbox_event")
        )
        await connection.execute(
            """
            INSERT INTO charity_action_capability (action_id, capability)
            VALUES ($1, 'delivery')
            ON CONFLICT DO NOTHING
            """,
            ACTIVE_ACTION_ID,
        )

    async with httpx.AsyncClient(base_url=base_url, timeout=20) as client:
        anna_revision = await member_revision(client, ANNA_ID)
        stale = await change_global_role(
            client,
            cookies=stale_system_cookies,
            user_id=ANNA_ID,
            role=GlobalRole.FINANCE_READER,
            enabled=True,
            revision=anna_revision,
            command_id="pilot012:stale:global-finance",
            expected_status=401,
        )
        if stale.get("error", {}).get("code") != "fresh_login_required":
            raise ContractFailure("Rollenänderung akzeptierte veraltetes Fresh Login")

        forbidden_global = await change_global_role(
            client,
            cookies=klara_cookies,
            user_id=ANNA_ID,
            role=GlobalRole.FINANCE_READER,
            enabled=True,
            revision=anna_revision,
            command_id="pilot012:charity:forbidden-global",
            expected_status=403,
        )
        if forbidden_global.get("error", {}).get("code") != "system_admin_required":
            raise ContractFailure(
                "Charity-Admin erhielt für globale Rolle keinen klaren Scopefehler"
            )
        forbidden_foreign = await change_action_role(
            client,
            cookies=klara_cookies,
            user_id=ANNA_ID,
            action_id=FOREIGN_ACTION_ID,
            role=ActionRole.ACQUIRER,
            enabled=True,
            revision=anna_revision,
            command_id="pilot012:charity:forbidden-foreign",
            expected_status=403,
        )
        if (
            forbidden_foreign.get("error", {}).get("code")
            != "role_action_scope_forbidden"
        ):
            raise ContractFailure(
                "Charity-Admin erhielt für fremde Aktion keinen klaren Scopefehler"
            )

        finance_grant_id = "pilot012:charity:finance-grant"
        finance_grant = await change_action_role(
            client,
            cookies=klara_cookies,
            user_id=ANNA_ID,
            action_id=ACTIVE_ACTION_ID,
            role=ActionRole.FINANCE_READER,
            enabled=True,
            revision=anna_revision,
            command_id=finance_grant_id,
        )
        finance_replay = await change_action_role(
            client,
            cookies=klara_cookies,
            user_id=ANNA_ID,
            action_id=ACTIVE_ACTION_ID,
            role=ActionRole.FINANCE_READER,
            enabled=True,
            revision=anna_revision,
            command_id=finance_grant_id,
        )
        if (
            finance_grant.get("replayed") is not False
            or finance_replay.get("replayed") is not True
        ):
            raise ContractFailure("Aktionsrollenänderung ist nicht idempotent")

        anna_with_finance = require_identity(
            await identity_response(client, tokens["ANNA_OLD_SESSION"]),
            display_name="Anna Akquise",
        )
        if "invoices" not in navigation_keys(anna_with_finance, "web"):
            raise ContractFailure(
                "Finanzrolle wirkte nicht im nächsten Navigationsrequest"
            )
        for path in (
            f"/api/v1/actions/{ACTIVE_ACTION_ID}/invoices",
            f"/api/v1/actions/{ACTIVE_ACTION_ID}/documents",
        ):
            if (await client.get(path, cookies=anna_cookies)).status_code != 200:
                raise ContractFailure(
                    "Finanzrolle wirkte nicht im nächsten Rechnungs-/Dokumentrequest"
                )

        finance_revoke = await change_action_role(
            client,
            cookies=klara_cookies,
            user_id=ANNA_ID,
            action_id=ACTIVE_ACTION_ID,
            role=ActionRole.FINANCE_READER,
            enabled=False,
            revision=int(finance_grant["revision"]),
            command_id="pilot012:charity:finance-revoke",
        )
        anna_without_finance = require_identity(
            await identity_response(client, tokens["ANNA_OLD_SESSION"]),
            display_name="Anna Akquise",
        )
        if "invoices" in navigation_keys(anna_without_finance, "web"):
            raise ContractFailure(
                "Entzogene Finanzrolle blieb im nächsten Navigationsrequest wirksam"
            )
        for path in (
            f"/api/v1/actions/{ACTIVE_ACTION_ID}/invoices",
            f"/api/v1/actions/{ACTIVE_ACTION_ID}/documents",
        ):
            denied = await client.get(path, cookies=anna_cookies)
            if denied.status_code != 403 or denied.json().get("error", {}).get(
                "code"
            ) not in {"invoice_read_required", "document_download_required"}:
                raise ContractFailure(
                    "Entzogene Finanzrolle blieb für Rechnungen/Dokumente wirksam"
                )

        async with pool.acquire() as connection:
            membership_before = await connection.fetchrow(
                """
                SELECT id, active_from, active_until
                FROM action_membership
                WHERE action_id = $1 AND user_id = $2 AND role = 'acquirer'
                """,
                ACTIVE_ACTION_ID,
                ANNA_ID,
            )
            association_counts_before = (
                int(
                    await connection.fetchval(
                        """
                        SELECT count(*)
                        FROM acquisition_assignment
                        WHERE action_id = $1 AND acquirer_user_id = $2
                        """,
                        ACTIVE_ACTION_ID,
                        ANNA_ID,
                    )
                ),
                int(
                    await connection.fetchval(
                        """
                        SELECT count(*)
                        FROM acquisition_assignment_history AS history
                        JOIN acquisition_assignment AS assignment
                          ON assignment.id = history.assignment_id
                        WHERE assignment.action_id = $1
                          AND assignment.acquirer_user_id = $2
                        """,
                        ACTIVE_ACTION_ID,
                        ANNA_ID,
                    )
                ),
            )
        if membership_before is None or membership_before["active_until"] is not None:
            raise ContractFailure("Golden-Akquisiteur-Membership fehlt")

        acquirer_revoke = await change_action_role(
            client,
            cookies=klara_cookies,
            user_id=ANNA_ID,
            action_id=ACTIVE_ACTION_ID,
            role=ActionRole.ACQUIRER,
            enabled=False,
            revision=int(finance_revoke["revision"]),
            command_id="pilot012:charity:acquirer-revoke",
        )
        anna_offboarded = require_identity(
            await identity_response(client, tokens["ANNA_OLD_SESSION"]),
            display_name="Anna Akquise",
        )
        if navigation_keys(anna_offboarded, "pwa") != {"overview-pwa"}:
            raise ContractFailure(
                "Membership-Entzug wirkte nicht im nächsten PWA-Request"
            )
        async with pool.acquire() as connection:
            membership_after = await connection.fetchrow(
                """
                SELECT id, active_from, active_until
                FROM action_membership
                WHERE action_id = $1 AND user_id = $2 AND role = 'acquirer'
                """,
                ACTIVE_ACTION_ID,
                ANNA_ID,
            )
            association_counts_after = (
                int(
                    await connection.fetchval(
                        """
                        SELECT count(*)
                        FROM acquisition_assignment
                        WHERE action_id = $1 AND acquirer_user_id = $2
                        """,
                        ACTIVE_ACTION_ID,
                        ANNA_ID,
                    )
                ),
                int(
                    await connection.fetchval(
                        """
                        SELECT count(*)
                        FROM acquisition_assignment_history AS history
                        JOIN acquisition_assignment AS assignment
                          ON assignment.id = history.assignment_id
                        WHERE assignment.action_id = $1
                          AND assignment.acquirer_user_id = $2
                        """,
                        ACTIVE_ACTION_ID,
                        ANNA_ID,
                    )
                ),
            )
        if (
            membership_after is None
            or membership_after["id"] != membership_before["id"]
            or membership_after["active_from"] != membership_before["active_from"]
            or membership_after["active_until"] is None
            or association_counts_after != association_counts_before
        ):
            raise ContractFailure(
                "Membership-Entzug löschte historische Fachzuordnungen"
            )
        acquirer_restore = await change_action_role(
            client,
            cookies=klara_cookies,
            user_id=ANNA_ID,
            action_id=ACTIVE_ACTION_ID,
            role=ActionRole.ACQUIRER,
            enabled=True,
            revision=int(acquirer_revoke["revision"]),
            command_id="pilot012:charity:acquirer-restore",
        )

        driver_grant = await change_action_role(
            client,
            cookies=system_cookies,
            user_id=ANNA_ID,
            action_id=ACTIVE_ACTION_ID,
            role=ActionRole.DRIVER,
            enabled=True,
            revision=int(acquirer_restore["revision"]),
            command_id="pilot012:system:driver-grant",
        )
        anna_with_driver = require_identity(
            await identity_response(client, tokens["ANNA_OLD_SESSION"]),
            display_name="Anna Akquise",
        )
        if "delivery" not in navigation_keys(anna_with_driver, "pwa"):
            raise ContractFailure("Ausfahrerrolle wirkte nicht im nächsten Request")
        await change_action_role(
            client,
            cookies=system_cookies,
            user_id=ANNA_ID,
            action_id=ACTIVE_ACTION_ID,
            role=ActionRole.DRIVER,
            enabled=False,
            revision=int(driver_grant["revision"]),
            command_id="pilot012:system:driver-revoke",
        )

        klara_revision = await member_revision(client, KLARA_ID)
        system_admin_grant = await change_global_role(
            client,
            cookies=system_cookies,
            user_id=KLARA_ID,
            role=GlobalRole.SYSTEM_ADMIN,
            enabled=True,
            revision=klara_revision,
            command_id="pilot012:system:system-admin-grant",
        )
        klara_as_system = require_identity(
            await identity_response(client, tokens["KLARA_SESSION"]),
            display_name="Klara Kern",
        )
        if "system" not in navigation_keys(klara_as_system, "web"):
            raise ContractFailure(
                "System-Admin-Rolle wirkte nicht im nächsten Navigationsrequest"
            )
        full_directory = require_http(
            await client.get(
                "/api/v1/admin/members",
                params={"limit": 100},
                cookies=klara_cookies,
            ),
            200,
            "Globale Mitgliederliste",
        )
        if full_directory.get("partial") is not False:
            raise ContractFailure(
                "System-Admin-Rolle wirkte nicht auf die nächste Listenabfrage"
            )
        privacy_export = await client.post(
            "/api/v1/admin/privacy/exports",
            cookies=klara_cookies,
            json={"email": "mara.muster@musterwerk.leonaid.invalid"},
        )
        if privacy_export.status_code != 200:
            raise ContractFailure(
                "System-Admin-Rolle wirkte nicht auf den nächsten Exportrequest"
            )
        await change_global_role(
            client,
            cookies=system_cookies,
            user_id=KLARA_ID,
            role=GlobalRole.SYSTEM_ADMIN,
            enabled=False,
            revision=int(system_admin_grant["revision"]),
            command_id="pilot012:system:system-admin-revoke",
        )
        klara_after_system = require_identity(
            await identity_response(client, tokens["KLARA_SESSION"]),
            display_name="Klara Kern",
        )
        if "system" in navigation_keys(klara_after_system, "web"):
            raise ContractFailure(
                "Entzogene System-Admin-Rolle blieb im nächsten Request wirksam"
            )
        partial_directory = require_http(
            await client.get(
                "/api/v1/admin/members",
                params={"limit": 100},
                cookies=klara_cookies,
            ),
            200,
            "Aktionsbezogene Mitgliederliste",
        )
        if partial_directory.get("partial") is not True:
            raise ContractFailure(
                "Entzogene System-Admin-Rolle blieb auf Listen wirksam"
            )
        denied_export = await client.post(
            "/api/v1/admin/privacy/exports",
            cookies=klara_cookies,
            json={"email": "mara.muster@musterwerk.leonaid.invalid"},
        )
        if (
            denied_export.status_code != 403
            or denied_export.json().get("error", {}).get("code")
            != "system_admin_required"
        ):
            raise ContractFailure(
                "Entzogene System-Admin-Rolle blieb auf Export wirksam"
            )

        anna_revision = await member_revision(client, ANNA_ID)
        successor_grant = await change_action_role(
            client,
            cookies=klara_cookies,
            user_id=ANNA_ID,
            action_id=ACTIVE_ACTION_ID,
            role=ActionRole.CHARITY_ADMIN,
            enabled=True,
            revision=anna_revision,
            command_id="pilot012:charity:successor-grant",
        )
        klara_revision = await member_revision(client, KLARA_ID)
        klara_revoke = await change_action_role(
            client,
            cookies=system_cookies,
            user_id=KLARA_ID,
            action_id=ACTIVE_ACTION_ID,
            role=ActionRole.CHARITY_ADMIN,
            enabled=False,
            revision=klara_revision,
            command_id="pilot012:system:klara-admin-revoke",
        )
        stale_scope = await change_action_role(
            client,
            cookies=klara_cookies,
            user_id=BERND_ID,
            action_id=ACTIVE_ACTION_ID,
            role=ActionRole.FINANCE_READER,
            enabled=True,
            revision=await member_revision(client, BERND_ID),
            command_id="pilot012:charity:scope-changed",
            expected_status=403,
        )
        if stale_scope.get("error", {}).get("code") != "role_action_scope_forbidden":
            raise ContractFailure(
                "Entzogene Charity-Admin-Rolle wirkte noch im nächsten Request"
            )
        klara_restore = await change_action_role(
            client,
            cookies=system_cookies,
            user_id=KLARA_ID,
            action_id=ACTIVE_ACTION_ID,
            role=ActionRole.CHARITY_ADMIN,
            enabled=True,
            revision=int(klara_revoke["revision"]),
            command_id="pilot012:system:klara-admin-restore",
        )
        await change_action_role(
            client,
            cookies=klara_cookies,
            user_id=ANNA_ID,
            action_id=ACTIVE_ACTION_ID,
            role=ActionRole.CHARITY_ADMIN,
            enabled=False,
            revision=int(successor_grant["revision"]),
            command_id="pilot012:charity:successor-revoke",
        )
        last_admin = await change_action_role(
            client,
            cookies=system_cookies,
            user_id=KLARA_ID,
            action_id=ACTIVE_ACTION_ID,
            role=ActionRole.CHARITY_ADMIN,
            enabled=False,
            revision=int(klara_restore["revision"]),
            command_id="pilot012:system:last-charity-admin",
            expected_status=409,
        )
        if (
            last_admin.get("error", {}).get("code")
            != "last_charity_admin_role_forbidden"
        ):
            raise ContractFailure(
                "Letzter Charity-Admin lieferte keinen verständlichen Konflikt"
            )

        finn_revision = await member_revision(client, FINN_ID)

        async def concurrent_global_role(
            role: GlobalRole,
            command_id: str,
        ) -> tuple[GlobalRole, str, httpx.Response]:
            return (
                role,
                command_id,
                await client.patch(
                    (f"/api/v1/admin/members/{FINN_ID}/global-roles/{role.value}"),
                    cookies=system_cookies,
                    headers={
                        "Idempotency-Key": command_id,
                        "X-Request-ID": command_id,
                    },
                    json={"enabled": True, "expectedRevision": finn_revision},
                ),
            )

        concurrent_results = await asyncio.gather(
            concurrent_global_role(
                GlobalRole.FINANCE_READER,
                "pilot012:concurrency:finance-reader",
            ),
            concurrent_global_role(
                GlobalRole.FINANCE_MANAGER,
                "pilot012:concurrency:finance-manager",
            ),
        )
        if sorted(item[2].status_code for item in concurrent_results) != [200, 409]:
            raise ContractFailure(
                "Widersprüchliche Rollenänderungen gewannen nicht exakt einmal"
            )
        winning_role, winning_id, winning_response = next(
            item for item in concurrent_results if item[2].status_code == 200
        )
        losing_role, _, losing_response = next(
            item for item in concurrent_results if item[2].status_code == 409
        )
        successful_commands.add(winning_id)
        winning_payload = winning_response.json()
        if (
            losing_response.json().get("error", {}).get("code")
            != "account_revision_conflict"
            or winning_payload.get("revision") != finn_revision + 1
        ):
            raise ContractFailure(
                "Rollen-Revision löste Konkurrenz nicht verständlich auf"
            )
        losing_grant = await change_global_role(
            client,
            cookies=system_cookies,
            user_id=FINN_ID,
            role=losing_role,
            enabled=True,
            revision=int(winning_payload["revision"]),
            command_id=f"pilot012:system:{losing_role.value}-grant",
        )
        first_revoke = await change_global_role(
            client,
            cookies=system_cookies,
            user_id=FINN_ID,
            role=winning_role,
            enabled=False,
            revision=int(losing_grant["revision"]),
            command_id=f"pilot012:system:{winning_role.value}-revoke",
        )
        await change_global_role(
            client,
            cookies=system_cookies,
            user_id=FINN_ID,
            role=losing_role,
            enabled=False,
            revision=int(first_revoke["revision"]),
            command_id=f"pilot012:system:{losing_role.value}-revoke",
        )

    async with pool.acquire() as connection:
        outbox_after = int(
            await connection.fetchval("SELECT count(*) FROM outbox_event")
        )
        audit_rows = await connection.fetch(
            """
            SELECT request_id, payload::text AS payload
            FROM audit_event
            WHERE request_id LIKE 'pilot012:%'
              AND event_type IN (
                'identity.global_role.granted',
                'identity.global_role.revoked',
                'identity.action_membership.granted',
                'identity.action_membership.revoked'
              )
            ORDER BY request_id
            """
        )
        receipt_keys = {
            str(row["idempotency_key"])
            for row in await connection.fetch(
                """
                SELECT idempotency_key
                FROM command_receipt
                WHERE command_type = 'identity.role.assignment.change'
                  AND idempotency_key LIKE 'pilot012:%'
                  AND result IS NOT NULL
                """
            )
        }
    audit_keys = {str(row["request_id"]) for row in audit_rows}
    if (
        outbox_after != outbox_before
        or audit_keys != successful_commands
        or receipt_keys != successful_commands
        or len(audit_rows) != len(successful_commands)
        or any("email" in str(row["payload"]).casefold() for row in audit_rows)
    ):
        raise ContractFailure(
            "Rollenänderungen besitzen keine exakten, PII-freien Audit-/"
            "Idempotenzbelege oder lösten unerwartete E-Mail-Effekte aus"
        )


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
            "SYSTEM_STALE_SESSION": await create_session(
                connection,
                SYSTEM_ID,
                now=now,
                fresh_login_at=now - timedelta(hours=1),
                created_at=now - timedelta(hours=1),
            ),
            "SYSTEM_ROLE_STALE_SESSION": await create_session(
                connection,
                SYSTEM_ID,
                now=now,
                fresh_login_at=now - timedelta(hours=1),
                created_at=now - timedelta(hours=1),
            ),
            "KLARA_SESSION": await create_session(connection, KLARA_ID, now=now),
            "ANNA_OLD_SESSION": await create_session(connection, ANNA_ID, now=now),
            "ANNA_SECOND_SESSION": await create_session(connection, ANNA_ID, now=now),
            "FINN_SESSION": await create_session(connection, FINN_ID, now=now),
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
                cookies={"__Host-leonaid_session": tokens["ANNA_OLD_SESSION"]},
            )
            if email_attempt.status_code != 405:
                raise ContractFailure(
                    "Login-E-Mail besitzt unerwartet einen Self-Service"
                )

        system_identity = await repository.principal_for_session(
            hashlib.sha256(tokens["SYSTEM_SESSION"].encode()).hexdigest(),
            now=now,
        )
        klara_identity = await repository.principal_for_session(
            hashlib.sha256(tokens["KLARA_SESSION"].encode()).hexdigest(),
            now=now,
        )
        if system_identity is None or klara_identity is None:
            raise ContractFailure("reale Admin-Principals konnten nicht geladen werden")
        system = system_identity.principal
        klara = klara_identity.principal

        try:
            await administration.add_global_role(
                klara,
                ANNA_ID,
                GlobalRole.FINANCE_READER,
                enabled=True,
                expected_revision=1,
                idempotency_key="poc040:forbidden:global-role",
                request_id="poc040:forbidden:global-role",
            )
        except PermissionDenied:
            pass
        else:
            raise ContractFailure("Charity-Admin durfte globale Rolle vergeben")

        klara_revision = int(
            await pool.fetchval(
                "SELECT revision FROM user_account WHERE id = $1",
                KLARA_ID,
            )
        )
        global_grant = await administration.add_global_role(
            system,
            KLARA_ID,
            GlobalRole.FINANCE_READER,
            enabled=True,
            expected_revision=klara_revision,
            idempotency_key="poc040:global-role:grant",
            request_id="poc040:global-role:grant",
        )
        if not global_grant.enabled:
            raise ContractFailure("globale Rolle wurde nicht hinzugefügt")
        global_replay = await administration.add_global_role(
            system,
            KLARA_ID,
            GlobalRole.FINANCE_READER,
            enabled=True,
            expected_revision=klara_revision,
            idempotency_key="poc040:global-role:grant",
            request_id="poc040:global-role:grant:replay",
        )
        if not global_replay.replayed:
            raise ContractFailure("globale Rollenänderung ist nicht wiederholbar")

        membership_grant = await administration.add_action_membership(
            system,
            KLARA_ID,
            FOREIGN_ACTION_ID,
            ActionRole.FINANCE_READER,
            enabled=True,
            expected_revision=global_grant.revision,
            idempotency_key="poc040:membership:grant",
            request_id="poc040:membership:grant",
        )
        if not membership_grant.enabled:
            raise ContractFailure("zweite Aktionsrolle wurde nicht hinzugefügt")
        membership_replay = await administration.add_action_membership(
            system,
            KLARA_ID,
            FOREIGN_ACTION_ID,
            ActionRole.FINANCE_READER,
            enabled=True,
            expected_revision=global_grant.revision,
            idempotency_key="poc040:membership:grant",
            request_id="poc040:membership:grant:replay",
        )
        if not membership_replay.replayed:
            raise ContractFailure("Aktionsrollenänderung ist nicht wiederholbar")

        klara_identity_with_roles = await repository.principal_for_session(
            hashlib.sha256(tokens["KLARA_SESSION"].encode()).hexdigest(),
            now=datetime.now(timezone.utc),
        )
        if klara_identity_with_roles is None:
            raise ContractFailure(
                "Klaras aktualisierte Rollen konnten nicht geladen werden"
            )
        klara_with_roles = klara_identity_with_roles.principal
        if (
            klara_with_roles.global_roles != frozenset({GlobalRole.FINANCE_READER})
            or len(klara_with_roles.action_memberships) != 3
            or klara_with_roles.roles_for(FOREIGN_ACTION_ID)
            != frozenset({ActionRole.FINANCE_READER})
        ):
            raise ContractFailure(
                "mehrere globale/Aktionsrollen wurden nicht getrennt persistiert"
            )

        async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
            system_cookies = {"__Host-leonaid_session": tokens["SYSTEM_SESSION"]}
            system_page = await client.get(
                "/api/v1/admin/members",
                params={"limit": 3},
                cookies=system_cookies,
            )
            if (
                system_page.status_code != 200
                or system_page.headers.get("cache-control") != "no-store"
            ):
                raise ContractFailure(
                    "System-Admin-Mitgliederliste ist nicht sicher erreichbar"
                )
            system_payload = system_page.json()
            first_items = system_payload.get("items")
            next_cursor = system_payload.get("nextCursor")
            if (
                system_payload.get("total") != 8
                or system_payload.get("partial") is not False
                or not isinstance(first_items, list)
                or [item.get("displayName") for item in first_items]
                != ["Anna Akquise", "Bernd Binder", "Carla Club"]
                or not isinstance(next_cursor, str)
            ):
                raise ContractFailure(
                    "System-Admin-Sortierung oder Cursor-Seite ist inkorrekt"
                )
            second_page = await client.get(
                "/api/v1/admin/members",
                params={"limit": 3, "cursor": next_cursor},
                cookies=system_cookies,
            )
            if second_page.status_code != 200 or [
                item.get("displayName") for item in second_page.json().get("items", [])
            ] != ["Felix Fremd", "Finn Finanzen", "Gesa Gesperrt"]:
                raise ContractFailure("zweite Cursor-Seite ist inkorrekt")

            suspended = await client.get(
                "/api/v1/admin/members",
                params={"status": "suspended"},
                cookies=system_cookies,
            )
            foreign = await client.get(
                "/api/v1/admin/members",
                params={"action_id": str(FOREIGN_ACTION_ID)},
                cookies=system_cookies,
            )
            search = await client.get(
                "/api/v1/admin/members",
                params={"search": "anna akquise"},
                cookies=system_cookies,
            )
            if (
                suspended.status_code != 200
                or [
                    item.get("displayName")
                    for item in suspended.json().get("items", [])
                ]
                != ["Gesa Gesperrt"]
                or foreign.status_code != 200
                or [item.get("displayName") for item in foreign.json().get("items", [])]
                != ["Felix Fremd", "Klara Kern"]
                or search.status_code != 200
                or [item.get("displayName") for item in search.json().get("items", [])]
                != ["Anna Akquise"]
            ):
                raise ContractFailure(
                    "Mitgliedersuche, Status- oder Aktionsfilter ist inkorrekt"
                )

            system_detail = await client.get(
                f"/api/v1/admin/members/{KLARA_ID}",
                cookies=system_cookies,
            )
            system_detail_payload = system_detail.json()
            if (
                system_detail.status_code != 200
                or system_detail_payload.get("globalRoles") != ["finance_reader"]
                or len(system_detail_payload.get("actionMemberships", [])) != 3
            ):
                raise ContractFailure("System-Admin-Detail enthält nicht alle Rollen")

            klara_cookies = {"__Host-leonaid_session": tokens["KLARA_SESSION"]}
            klara_page = await client.get(
                "/api/v1/admin/members",
                params={"limit": 100},
                cookies=klara_cookies,
            )
            klara_payload = klara_page.json()
            klara_items = klara_payload.get("items")
            if (
                klara_page.status_code != 200
                or klara_payload.get("partial") is not True
                or klara_payload.get("total") != 6
                or not isinstance(klara_items, list)
                or {item.get("displayName") for item in klara_items}
                != {
                    "Anna Akquise",
                    "Bernd Binder",
                    "Carla Club",
                    "Finn Finanzen",
                    "Gesa Gesperrt",
                    "Klara Kern",
                }
                or any(item.get("globalRoles") for item in klara_items)
                or any(
                    membership.get("actionId")
                    not in {str(ACTIVE_ACTION_ID), str(ARCHIVED_ACTION_ID)}
                    for item in klara_items
                    for membership in item.get("actionMemberships", [])
                )
            ):
                raise ContractFailure(
                    "Charity-Admin-Row-Level-Sicht oder Rollenredaktion ist inkorrekt"
                )
            klara_detail = await client.get(
                f"/api/v1/admin/members/{KLARA_ID}",
                cookies=klara_cookies,
            )
            if (
                klara_detail.status_code != 200
                or klara_detail.json().get("globalRoles") != []
                or len(klara_detail.json().get("actionMemberships", [])) != 2
            ):
                raise ContractFailure(
                    "Charity-Admin-Detail redigiert den Fremdscope nicht"
                )
            forbidden_action = await client.get(
                "/api/v1/admin/members",
                params={"action_id": str(FOREIGN_ACTION_ID)},
                cookies=klara_cookies,
            )
            concealed_member = await client.get(
                f"/api/v1/admin/members/{UUID('10000000-0000-4000-8000-000000000003')}",
                cookies=klara_cookies,
            )
            if forbidden_action.status_code != 403:
                raise ContractFailure("Charity-Admin durfte fremde Aktion filtern")
            if concealed_member.status_code != 404:
                raise ContractFailure(
                    "fremdes Mitglied wurde nicht als unbekannt verborgen"
                )

            public_denied = await client.get("/api/v1/admin/members")
            if public_denied.status_code != 401:
                raise ContractFailure(
                    "öffentliche Persona erhielt Mitgliederlisten-Zugriff"
                )

            for persona, token in (
                ("Akquisiteur", tokens["ANNA_OLD_SESSION"]),
                ("Finanzen", tokens["FINN_SESSION"]),
            ):
                denied = await client.get(
                    "/api/v1/admin/members",
                    cookies={"__Host-leonaid_session": token},
                )
                if (
                    denied.status_code != 403
                    or denied.json().get("error", {}).get("code")
                    != "member_directory_forbidden"
                ):
                    raise ContractFailure(f"{persona} erhielt Mitgliederlisten-Zugriff")

        membership_revoke = await administration.add_action_membership(
            system,
            KLARA_ID,
            FOREIGN_ACTION_ID,
            ActionRole.FINANCE_READER,
            enabled=False,
            expected_revision=membership_grant.revision,
            idempotency_key="poc040:membership:revoke",
            request_id="poc040:membership:revoke",
        )
        if membership_revoke.enabled:
            raise ContractFailure("temporäre Aktionsrolle wurde nicht entfernt")
        global_revoke = await administration.add_global_role(
            system,
            KLARA_ID,
            GlobalRole.FINANCE_READER,
            enabled=False,
            expected_revision=membership_revoke.revision,
            idempotency_key="poc040:global-role:revoke",
            request_id="poc040:global-role:revoke",
        )
        if global_revoke.enabled:
            raise ContractFailure("temporäre globale Rolle wurde nicht entfernt")

        await prove_role_administration(pool, base_url=base_url, tokens=tokens)

        async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
            system_cookies = {
                "__Host-leonaid_session": tokens["SYSTEM_SESSION"],
            }
            stale_system_cookies = {
                "__Host-leonaid_session": tokens["SYSTEM_STALE_SESSION"],
            }
            klara_cookies = {
                "__Host-leonaid_session": tokens["KLARA_SESSION"],
            }
            anna_detail = await client.get(
                f"/api/v1/admin/members/{ANNA_ID}",
                cookies=system_cookies,
            )
            if anna_detail.status_code != 200:
                raise ContractFailure(
                    "Anna konnte nicht für Statusänderung geladen werden"
                )
            anna_payload = anna_detail.json()
            anna_revision = int(anna_payload["revision"])
            if int(anna_payload["activeSessionCount"]) != 2:
                raise ContractFailure(
                    "Integrationstest besitzt nicht exakt zwei aktive Anna-Sitzungen"
                )

            stale_change = await client.patch(
                f"/api/v1/admin/members/{ANNA_ID}/status",
                cookies=stale_system_cookies,
                headers={
                    "Idempotency-Key": "pilot011:stale:suspend",
                    "X-Request-ID": "pilot011:stale:suspend",
                },
                json={
                    "status": "suspended",
                    "expectedRevision": anna_revision,
                },
            )
            if (
                stale_change.status_code != 401
                or stale_change.json().get("error", {}).get("code")
                != "fresh_login_required"
            ):
                raise ContractFailure(
                    "Statusänderung akzeptierte veraltetes Fresh Login nicht "
                    f"korrekt: HTTP {stale_change.status_code} "
                    f"{stale_change.text[:300]}"
                )

            forbidden_change = await client.patch(
                f"/api/v1/admin/members/{ANNA_ID}/status",
                cookies=klara_cookies,
                headers={
                    "Idempotency-Key": "pilot011:charity-admin:suspend",
                    "X-Request-ID": "pilot011:charity-admin:suspend",
                },
                json={
                    "status": "suspended",
                    "expectedRevision": anna_revision,
                },
            )
            if forbidden_change.status_code != 403:
                raise ContractFailure("Charity-Admin durfte Kontostatus ändern")

            self_change = await client.patch(
                f"/api/v1/admin/members/{SYSTEM_ID}/status",
                cookies=system_cookies,
                headers={
                    "Idempotency-Key": "pilot011:self:suspend",
                    "X-Request-ID": "pilot011:self:suspend",
                },
                json={"status": "suspended", "expectedRevision": 1},
            )
            if (
                self_change.status_code != 409
                or self_change.json().get("error", {}).get("code")
                != "account_self_status_change_forbidden"
            ):
                raise ContractFailure("System-Admin konnte sich selbst sperren")

            suspend_body = {
                "status": "suspended",
                "expectedRevision": anna_revision,
            }
            suspend_headers = {
                "Idempotency-Key": "pilot011:anna:suspend",
                "X-Request-ID": "pilot011:anna:suspend",
            }
            suspended = await client.patch(
                f"/api/v1/admin/members/{ANNA_ID}/status",
                cookies=system_cookies,
                headers=suspend_headers,
                json=suspend_body,
            )
            if suspended.status_code != 200:
                raise ContractFailure(
                    f"Sperren lieferte HTTP {suspended.status_code}: "
                    f"{suspended.text[:300]}"
                )
            suspended_payload = suspended.json()
            if (
                suspended_payload.get("status") != "suspended"
                or suspended_payload.get("revokedSessionCount") != 2
                or suspended_payload.get("revision") != anna_revision + 1
                or suspended_payload.get("replayed") is not False
            ):
                raise ContractFailure("Sperrantwort besitzt falschen atomaren Beleg")

            replay = await client.patch(
                f"/api/v1/admin/members/{ANNA_ID}/status",
                cookies=system_cookies,
                headers=suspend_headers,
                json=suspend_body,
            )
            if replay.status_code != 200 or replay.json().get("replayed") is not True:
                raise ContractFailure(
                    "Statusänderung ist nicht idempotent wiederholbar"
                )

            for token in (
                tokens["ANNA_OLD_SESSION"],
                tokens["ANNA_SECOND_SESSION"],
            ):
                denied = await identity_response(client, token)
                if denied.status_code != 401:
                    raise ContractFailure(
                        "bestehende Sitzung blieb nach Suspendierung wirksam"
                    )

            async with pool.acquire() as status_connection:
                active_sessions = int(
                    await status_connection.fetchval(
                        """
                        SELECT count(*)
                        FROM user_session
                        WHERE user_id = $1
                          AND revoked_at IS NULL
                        """,
                        ANNA_ID,
                    )
                )
                challenges_before = int(
                    await status_connection.fetchval(
                        "SELECT count(*) FROM login_challenge WHERE user_id = $1",
                        ANNA_ID,
                    )
                )
            if active_sessions != 0:
                raise ContractFailure("PostgreSQL enthält aktive Anna-Sitzungen")

            login_request = await client.post(
                "/api/v1/auth/login",
                headers={"X-Request-ID": "pilot011:anna:login-blocked"},
                json={"email": "anna.akquise@leonaid.invalid"},
            )
            if login_request.status_code != 202:
                raise ContractFailure("Login-Anfrage verrät den gesperrten Kontostatus")
            async with pool.acquire() as status_connection:
                challenges_after = int(
                    await status_connection.fetchval(
                        "SELECT count(*) FROM login_challenge WHERE user_id = $1",
                        ANNA_ID,
                    )
                )
            if challenges_after != challenges_before:
                raise ContractFailure("Gesperrtes Konto erhielt eine Login-Challenge")

            reactivated = await client.patch(
                f"/api/v1/admin/members/{ANNA_ID}/status",
                cookies=system_cookies,
                headers={
                    "Idempotency-Key": "pilot011:anna:reactivate",
                    "X-Request-ID": "pilot011:anna:reactivate",
                },
                json={
                    "status": "active",
                    "expectedRevision": suspended_payload["revision"],
                },
            )
            if (
                reactivated.status_code != 200
                or reactivated.json().get("status") != "active"
                or reactivated.json().get("revokedSessionCount") != 0
            ):
                raise ContractFailure("Reaktivierung wurde nicht persistiert")
            for token in (
                tokens["ANNA_OLD_SESSION"],
                tokens["ANNA_SECOND_SESSION"],
            ):
                still_denied = await identity_response(client, token)
                if still_denied.status_code != 401:
                    raise ContractFailure(
                        "widerrufene alte Sitzung lebte nach Reaktivierung wieder auf"
                    )

            bernd_detail = await client.get(
                f"/api/v1/admin/members/{BERND_ID}",
                cookies=system_cookies,
            )
            if bernd_detail.status_code != 200:
                raise ContractFailure("Concurrency-Konto konnte nicht geladen werden")
            bernd_revision = int(bernd_detail.json()["revision"])

            async def conflicting_status(
                target: str,
                command_id: str,
            ) -> httpx.Response:
                return await client.patch(
                    f"/api/v1/admin/members/{BERND_ID}/status",
                    cookies=system_cookies,
                    headers={
                        "Idempotency-Key": command_id,
                        "X-Request-ID": command_id,
                    },
                    json={
                        "status": target,
                        "expectedRevision": bernd_revision,
                    },
                )

            conflicts = await asyncio.gather(
                conflicting_status(
                    "suspended",
                    "pilot011:concurrency:suspend",
                ),
                conflicting_status(
                    "archived",
                    "pilot011:concurrency:archive",
                ),
            )
            if sorted(response.status_code for response in conflicts) != [200, 409]:
                raise ContractFailure(
                    "Widersprüchliche Statusänderungen gewannen nicht exakt einmal"
                )
            winning_response = next(
                response for response in conflicts if response.status_code == 200
            )
            winning_payload = winning_response.json()
            if winning_payload.get("revision") != bernd_revision + 1:
                raise ContractFailure("Concurrency-Sieger erhöhte Revision nicht exakt")
            if winning_payload.get("status") == "suspended":
                restored = await client.patch(
                    f"/api/v1/admin/members/{BERND_ID}/status",
                    cookies=system_cookies,
                    headers={
                        "Idempotency-Key": "pilot011:concurrency:restore",
                        "X-Request-ID": "pilot011:concurrency:restore",
                    },
                    json={
                        "status": "active",
                        "expectedRevision": winning_payload["revision"],
                    },
                )
                if restored.status_code != 200:
                    raise ContractFailure(
                        "Concurrency-Test konnte Bernd nicht reaktivieren"
                    )

            async with pool.acquire() as archive_connection:
                archive_before = {
                    "memberships": int(
                        await archive_connection.fetchval(
                            "SELECT count(*) FROM action_membership WHERE user_id = $1",
                            CARLA_ID,
                        )
                    ),
                    "activities": int(
                        await archive_connection.fetchval(
                            "SELECT count(*) FROM acquisition_activity "
                            "WHERE actor_user_id = $1",
                            CARLA_ID,
                        )
                    ),
                    "actorAudit": int(
                        await archive_connection.fetchval(
                            "SELECT count(*) FROM audit_event WHERE actor_user_id = $1",
                            CARLA_ID,
                        )
                    ),
                    "invoices": int(
                        await archive_connection.fetchval(
                            "SELECT count(*) FROM invoice"
                        )
                    ),
                    "documents": int(
                        await archive_connection.fetchval(
                            "SELECT count(*) FROM generated_document"
                        )
                    ),
                }
            carla_detail = await client.get(
                f"/api/v1/admin/members/{CARLA_ID}",
                cookies=system_cookies,
            )
            carla_revision = int(carla_detail.json()["revision"])
            archived = await client.patch(
                f"/api/v1/admin/members/{CARLA_ID}/status",
                cookies=system_cookies,
                headers={
                    "Idempotency-Key": "pilot011:carla:archive",
                    "X-Request-ID": "pilot011:carla:archive",
                },
                json={
                    "status": "archived",
                    "expectedRevision": carla_revision,
                },
            )
            if (
                archived.status_code != 200
                or archived.json().get("status") != "archived"
            ):
                raise ContractFailure("Archivierung wurde nicht persistiert")
            async with pool.acquire() as archive_connection:
                archive_after = {
                    "memberships": int(
                        await archive_connection.fetchval(
                            "SELECT count(*) FROM action_membership WHERE user_id = $1",
                            CARLA_ID,
                        )
                    ),
                    "activities": int(
                        await archive_connection.fetchval(
                            "SELECT count(*) FROM acquisition_activity "
                            "WHERE actor_user_id = $1",
                            CARLA_ID,
                        )
                    ),
                    "actorAudit": int(
                        await archive_connection.fetchval(
                            "SELECT count(*) FROM audit_event WHERE actor_user_id = $1",
                            CARLA_ID,
                        )
                    ),
                    "invoices": int(
                        await archive_connection.fetchval(
                            "SELECT count(*) FROM invoice"
                        )
                    ),
                    "documents": int(
                        await archive_connection.fetchval(
                            "SELECT count(*) FROM generated_document"
                        )
                    ),
                }
            if archive_after != archive_before:
                raise ContractFailure(
                    "Archivierung veränderte historische Fachzuordnungen"
                )

        async with pool.acquire() as status_connection:
            system_revision = int(
                await status_connection.fetchval(
                    "SELECT revision FROM user_account WHERE id = $1",
                    SYSTEM_ID,
                )
            )
        try:
            await repository.transition_account_status(
                SYSTEM_ID,
                AccountStatus.ARCHIVED,
                actor_user_id=KLARA_ID,
                expected_revision=system_revision,
                idempotency_key="pilot011:last-system-admin:archive",
                request_hash=hashlib.sha256(
                    b"pilot011:last-system-admin:archive"
                ).hexdigest(),
                request_id="pilot011:last-system-admin:archive",
                occurred_at=datetime.now(timezone.utc),
            )
        except Conflict as error:
            if error.code != "last_system_admin_archival_forbidden":
                raise ContractFailure(
                    f"Letzter System-Admin lieferte falschen Konflikt: {error.code}"
                ) from error
        else:
            raise ContractFailure("Letzter aktiver System-Admin wurde archiviert")

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
            pilot_status_audit_rows = await connection.fetch(
                """
                SELECT entity_id, payload::text AS payload
                FROM audit_event
                WHERE request_id LIKE 'pilot011:%'
                  AND event_type = 'identity.account.status_changed'
                ORDER BY occurred_at, entity_id
                """
            )
            pilot_status_receipts = int(
                await connection.fetchval(
                    """
                    SELECT count(*)
                    FROM command_receipt
                    WHERE command_type = 'identity.account.status.change'
                      AND idempotency_key LIKE 'pilot011:%'
                      AND result IS NOT NULL
                    """
                )
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
            ]
        ):
            raise ContractFailure(f"AuditEvents sind unvollständig: {event_types}")
        if any("email" in str(row["payload"]).casefold() for row in audit_rows):
            raise ContractFailure("AuditEvent enthält unerwartet eine E-Mail")
        expected_status_events = (
            5 if winning_payload.get("status") == "suspended" else 4
        )
        if (
            len(pilot_status_audit_rows) != expected_status_events
            or pilot_status_receipts != expected_status_events
        ):
            raise ContractFailure(
                "Statusänderungen besitzen nicht je einen Audit- und Idempotenzbeleg"
            )
        for row in pilot_status_audit_rows:
            payload = str(row["payload"])
            if (
                "idempotencyKey" not in payload
                or "previousRevision" not in payload
                or "revision" not in payload
                or "email" in payload.casefold()
            ):
                raise ContractFailure("Status-Audit ist unvollständig oder enthält PII")

        output = arguments.session_output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "\n".join(
                f"{name}={value}"
                for name, value in tokens.items()
                if name
                in {
                    "SYSTEM_SESSION",
                    "SYSTEM_STALE_SESSION",
                    "SYSTEM_ROLE_STALE_SESSION",
                    "KLARA_SESSION",
                    "ANNA_SESSION",
                    "FINN_SESSION",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        output.chmod(0o600)
    finally:
        await pool.close()

    print(
        "identity-contract: Rollen, Statusrevision, Idempotenz, Konkurrenz, "
        "Archivtreue und sofortiger Sitzungsentzug real bewiesen"
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
