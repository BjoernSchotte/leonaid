#!/usr/bin/env python3
"""Real FastAPI/PostgreSQL aggregate contract for POC-101."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import httpx

from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
EMPTY_ACTION_ID = UUID("20000000-0000-4000-8000-000000000003")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
FELIX_ID = UUID("10000000-0000-4000-8000-000000000003")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
SESSION_NAMESPACE = UUID("fc6f4986-ff43-4fd3-b4aa-92a6cead8141")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(user_id: UUID) -> str:
    return f"poc101-{user_id}-server-session-token-value"


async def seed_sessions(connection: asyncpg.Connection[Any]) -> None:
    now = datetime.now(timezone.utc)
    users = (KLARA_ID, FELIX_ID, ANNA_ID)
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        list(users),
    )
    for user_id in users:
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at,
                last_seen_at, fresh_login_at, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $5, $5, $5)
            """,
            uuid5(SESSION_NAMESPACE, str(user_id)),
            user_id,
            session_token_digest(token_for(user_id)),
            now + SESSION_LIFETIME,
            now,
        )


async def dashboard(
    api: httpx.AsyncClient,
    *,
    action_id: UUID,
    user_id: UUID,
    label: str,
) -> httpx.Response:
    return await api.get(
        f"/api/v1/actions/{action_id}/dashboard",
        headers={
            "Cookie": f"{SESSION_COOKIE_NAME}={token_for(user_id)}",
            "X-Request-ID": f"poc101:{label}",
        },
    )


def as_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractFailure(f"{label} ist kein Objekt")
    return value


def integer(row: asyncpg.Record, key: str) -> int:
    return int(row[key] or 0)


async def assert_acquirer_aggregate(
    connection: asyncpg.Connection[Any],
    payload: dict[str, Any],
) -> None:
    acquirer = as_object(payload.get("acquirer"), "Akquisiteur-Dashboard")
    if payload.get("charityAdmin") is not None:
        raise ContractFailure("Akquisiteur erhält aktionsweite Admin-Kennzahlen")
    pipeline = await connection.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE status = 'open') AS open,
            count(*) FILTER (WHERE status = 'contacted') AS contacted,
            count(*) FILTER (WHERE status = 'committed') AS committed,
            count(*) FILTER (WHERE status = 'declined') AS declined,
            count(*) FILTER (WHERE status = 'handed_over') AS handed_over,
            count(*) AS total
        FROM acquisition_assignment
        WHERE action_id = $1 AND acquirer_user_id = $2
        """,
        ACTION_ID,
        ANNA_ID,
    )
    api_pipeline = as_object(acquirer.get("pipeline"), "Persönliche Pipeline")
    pipeline_mapping = {
        "open": "open",
        "contacted": "contacted",
        "committed": "committed",
        "declined": "declined",
        "handedOver": "handed_over",
        "total": "total",
    }
    if pipeline is None or any(
        int(api_pipeline[api_key]) != integer(pipeline, sql_key)
        for api_key, sql_key in pipeline_mapping.items()
    ):
        raise ContractFailure("Persönliche API-Pipeline weicht von SQL ab")

    activity_count = await connection.fetchval(
        """
        SELECT count(*) FROM acquisition_activity
        WHERE action_id = $1 AND actor_user_id = $2
        """,
        ACTION_ID,
        ANNA_ID,
    )
    if int(acquirer["activityCount"]) != int(activity_count or 0):
        raise ContractFailure("Persönliche Aktivitätszahl weicht von SQL ab")
    reminders = as_object(acquirer.get("reminders"), "Wiedervorlagen")
    if (
        int(reminders["unscheduled"]) != 2
        or int(reminders["overdue"]) != 0
        or int(reminders["today"]) != 0
        or int(reminders["upcoming"]) != 0
        or int(reminders["total"]) != 2
    ):
        raise ContractFailure("Persönliche Wiedervorlagen sind nicht exakt")


async def assert_admin_aggregate(
    connection: asyncpg.Connection[Any],
    payload: dict[str, Any],
) -> None:
    admin = as_object(payload.get("charityAdmin"), "Charity-Admin-Dashboard")
    if payload.get("acquirer") is not None:
        raise ContractFailure("Charity-Admin erhält fremde persönliche Kennzahlen")
    pipeline = await connection.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE status = 'open') AS open,
            count(*) FILTER (WHERE status = 'contacted') AS contacted,
            count(*) FILTER (WHERE status = 'committed') AS committed,
            count(*) FILTER (WHERE status = 'declined') AS declined,
            count(*) FILTER (WHERE status = 'handed_over') AS handed_over,
            count(*) AS total
        FROM acquisition_assignment
        WHERE action_id = $1
        """,
        ACTION_ID,
    )
    api_pipeline = as_object(admin.get("pipeline"), "Aktionsweite Pipeline")
    pipeline_mapping = {
        "open": "open",
        "contacted": "contacted",
        "committed": "committed",
        "declined": "declined",
        "handedOver": "handed_over",
        "total": "total",
    }
    if pipeline is None or any(
        int(api_pipeline[api_key]) != integer(pipeline, sql_key)
        for api_key, sql_key in pipeline_mapping.items()
    ):
        raise ContractFailure("Aktionsweite API-Pipeline weicht von SQL ab")

    commitment_sql = await connection.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE status = 'draft') AS draft,
            count(*) FILTER (WHERE status = 'review_ready') AS review_ready,
            count(*) FILTER (WHERE status = 'confirmed') AS confirmed,
            count(*) FILTER (WHERE status = 'invoiced') AS invoiced,
            count(*) FILTER (WHERE status = 'cancelled') AS cancelled,
            count(*) AS total,
            count(*) FILTER (WHERE status <> 'cancelled') AS active_total,
            coalesce(sum(total_minor) FILTER (
                WHERE status <> 'cancelled'
            ), 0) AS active_total_minor
        FROM commitment
        WHERE action_id = $1
        """,
        ACTION_ID,
    )
    line_sql = await connection.fetchrow(
        """
        SELECT
            coalesce(sum(line.quantity) FILTER (
                WHERE commitment.status <> 'cancelled'
                  AND line.unit_snapshot = 'box'
            ), 0) AS total_boxes,
            coalesce(sum(
                CASE
                    WHEN commitment.status <> 'cancelled'
                    THEN line.quantity * coalesce(
                        line.pieces_per_unit_snapshot,
                        CASE WHEN line.unit_snapshot = 'piece' THEN 1 ELSE 0 END
                    )
                    ELSE 0
                END
            ), 0) AS total_pieces
        FROM commitment
        JOIN commitment_line AS line ON line.commitment_id = commitment.id
        WHERE commitment.action_id = $1
        """,
        ACTION_ID,
    )
    api_commitments = as_object(admin.get("commitments"), "Bestellungen")
    if commitment_sql is None or line_sql is None:
        raise ContractFailure("SQL-Bestellaggregate fehlen")
    commitment_mapping = {
        "draft": "draft",
        "reviewReady": "review_ready",
        "confirmed": "confirmed",
        "invoiced": "invoiced",
        "cancelled": "cancelled",
        "total": "total",
        "activeTotal": "active_total",
        "activeTotalMinor": "active_total_minor",
    }
    if any(
        int(api_commitments[api_key]) != integer(commitment_sql, sql_key)
        for api_key, sql_key in commitment_mapping.items()
    ) or any(
        int(api_commitments[api_key]) != integer(line_sql, sql_key)
        for api_key, sql_key in (
            ("totalBoxes", "total_boxes"),
            ("totalPieces", "total_pieces"),
        )
    ):
        raise ContractFailure("API-Bestellaggregate weichen von SQL ab")

    invoice_sql = await connection.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE status = 'issued') AS issued,
            count(*) FILTER (WHERE status = 'sent') AS sent,
            count(*) FILTER (
                WHERE status IN ('issued', 'sent')
            ) AS open,
            count(*) FILTER (WHERE status = 'paid') AS paid,
            count(*) FILTER (WHERE status = 'cancelled') AS cancelled,
            count(*) AS total,
            coalesce(sum(gross_minor) FILTER (
                WHERE status IN ('issued', 'sent', 'paid')
            ), 0) AS invoiced_amount_minor,
            coalesce(sum(gross_minor) FILTER (
                WHERE status IN ('issued', 'sent')
            ), 0) AS open_amount_minor
        FROM invoice
        WHERE action_id = $1
        """,
        ACTION_ID,
    )
    api_invoices = as_object(admin.get("invoices"), "Rechnungen")
    if invoice_sql is None:
        raise ContractFailure("SQL-Rechnungsaggregate fehlen")
    invoice_mapping = {
        "issued": "issued",
        "sent": "sent",
        "open": "open",
        "paid": "paid",
        "cancelled": "cancelled",
        "total": "total",
        "invoicedAmountMinor": "invoiced_amount_minor",
        "openAmountMinor": "open_amount_minor",
    }
    if any(
        int(api_invoices[api_key]) != integer(invoice_sql, sql_key)
        for api_key, sql_key in invoice_mapping.items()
    ):
        raise ContractFailure("API-Rechnungsaggregate weichen von SQL ab")


def assert_definitions(payload: dict[str, Any], expected_keys: set[str]) -> None:
    definitions = payload.get("metricDefinitions")
    if not isinstance(definitions, list):
        raise ContractFailure("Kennzahl-Definitionen fehlen")
    actual_keys = {
        str(item.get("key"))
        for item in definitions
        if isinstance(item, dict)
        and str(item.get("label", "")).strip()
        and str(item.get("description", "")).strip()
        and str(item.get("href", "")).startswith("/")
    }
    if actual_keys != expected_keys:
        raise ContractFailure("Kennzahl-Definitionen sind unvollständig")


async def run() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"))
    try:
        await seed_sessions(connection)
        await connection.execute(
            """
            UPDATE charity_action
            SET goal_value = NULL,
                goal_unit = NULL,
                actual_value = 125,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            EMPTY_ACTION_ID,
        )

        async with httpx.AsyncClient(
            base_url=require_env("API_BASE_URL"),
            timeout=30,
        ) as api:
            anna_response = await dashboard(
                api,
                action_id=ACTION_ID,
                user_id=ANNA_ID,
                label="anna",
            )
            anna_response.raise_for_status()
            if anna_response.headers.get("cache-control") != "private, no-store":
                raise ContractFailure("Dashboard-Antwort ist cachebar")
            anna = as_object(anna_response.json(), "Anna-Dashboard")
            goal = as_object(anna.get("goal"), "Aktionsziel")
            if (
                goal.get("actualValue") != "900"
                or goal.get("targetValue") != "1000"
                or goal.get("unit") != "EUR"
                or goal.get("progressBasisPoints") != 9000
                or goal.get("configured") is not True
            ):
                raise ContractFailure("Golden-Aktionsziel ist nicht exakt")
            await assert_acquirer_aggregate(connection, anna)
            assert_definitions(
                anna,
                {
                    "acquirer.pipeline",
                    "acquirer.reminders",
                    "acquirer.activities",
                },
            )

            klara_response = await dashboard(
                api,
                action_id=ACTION_ID,
                user_id=KLARA_ID,
                label="klara",
            )
            klara_response.raise_for_status()
            klara = as_object(klara_response.json(), "Klara-Dashboard")
            await assert_admin_aggregate(connection, klara)
            assert_definitions(
                klara,
                {
                    "admin.pipeline",
                    "admin.commitments",
                    "admin.invoiced",
                    "admin.open_receivables",
                },
            )

            concealed = await dashboard(
                api,
                action_id=ACTION_ID,
                user_id=FELIX_ID,
                label="concealed",
            )
            if concealed.status_code != 404:
                raise ContractFailure("Fremdes Dashboard wird nicht verborgen")

            empty_response = await dashboard(
                api,
                action_id=EMPTY_ACTION_ID,
                user_id=FELIX_ID,
                label="partial-empty",
            )
            empty_response.raise_for_status()
            empty = as_object(empty_response.json(), "Leeres Dashboard")
            empty_goal = as_object(empty.get("goal"), "Teilkonfiguriertes Ziel")
            empty_admin = as_object(empty.get("charityAdmin"), "Leere Admin-Sicht")
            if (
                empty_goal.get("configured") is not False
                or empty_goal.get("targetValue") is not None
                or empty_goal.get("progressBasisPoints") is not None
                or empty_goal.get("actualValue") != "125"
                or as_object(empty_admin["pipeline"], "Leere Pipeline").get("total")
                != 0
                or as_object(empty_admin["commitments"], "Leere Bestellungen").get(
                    "total"
                )
                != 0
                or as_object(empty_admin["invoices"], "Leere Rechnungen").get("total")
                != 0
            ):
                raise ContractFailure(
                    "Leere oder teilkonfigurierte Aktion ist nicht stabil"
                )
    finally:
        await connection.close()

    print("dashboard-contract: OK: Rollen, Golden-Kennzahlen, echte SQL-Aggregate,")
    print(
        "dashboard-contract:     Definitionen, Leersicht und Row-Level-Schutz bewiesen"
    )


if __name__ == "__main__":
    asyncio.run(run())
