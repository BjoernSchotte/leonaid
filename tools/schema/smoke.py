#!/usr/bin/env python3
"""Real PostgreSQL migration and constraint proof for POC-021."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

import asyncpg

EXPECTED_TABLES = {
    "acquisition_activity",
    "acquisition_assignment",
    "acquisition_assignment_history",
    "action_invitation",
    "action_membership",
    "activity_event",
    "activity_event_recipient",
    "alembic_version",
    "audit_event",
    "beneficiary",
    "charity_action",
    "charity_action_capability",
    "commitment",
    "commitment_line",
    "consent_record",
    "generated_document",
    "invoice",
    "offering",
    "outbox_event",
    "payment_record",
    "public_action_alias",
    "suppression_entry",
    "user_account",
    "user_global_role",
    "user_session",
}

USER_A = "10000000-0000-4000-8000-000000000004"
USER_B = "10000000-0000-4000-8000-000000000005"
ACTION = "20000000-0000-4000-8000-000000000001"
COMPANY = "40000000-0000-4000-8000-000000000001"
ASSIGNMENT_A = "60000000-0000-4000-8000-000000000001"
ASSIGNMENT_B = "60000000-0000-4000-8000-000000000002"
AUDIT = "d0000000-0000-4000-8000-000000000001"
OUTBOX = "e0000000-0000-4000-8000-000000000001"


class SchemaError(RuntimeError):
    """The migrated schema did not enforce a required invariant."""


async def expect_database_error(
    operation: Callable[[], Awaitable[Any]],
    label: str,
) -> None:
    try:
        await operation()
    except asyncpg.PostgresError:
        return
    raise SchemaError(f"Constraint wurde nicht erzwungen: {label}")


async def verify_tables(connection: asyncpg.Connection[Any], legacy: bool) -> None:
    rows = await connection.fetch(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        """
    )
    tables = {str(row["table_name"]) for row in rows}
    missing = EXPECTED_TABLES - tables
    if missing:
        raise SchemaError(f"Core-Tabellen fehlen: {sorted(missing)}")
    revision = await connection.fetchval("SELECT version_num FROM alembic_version")
    if revision != "0001_core_schema":
        raise SchemaError(f"unerwarteter Alembic-Head: {revision}")
    if legacy:
        marker = await connection.fetchrow(
            "SELECT label, payload FROM previous_schema_snapshot WHERE id = 1"
        )
        if (
            marker is None
            or marker["label"] != "leonaid-core-v0"
            or marker["payload"]["amountMinor"] != 7200
            or marker["payload"]["actionId"] != ACTION
        ):
            raise SchemaError("Daten des Vorgänger-Snapshots gingen verloren")


async def insert_foundation(connection: asyncpg.Connection[Any]) -> None:
    await connection.executemany(
        """
        INSERT INTO user_account (id, email, display_name, status)
        VALUES ($1, $2, $3, 'active')
        """,
        [
            (USER_A, "anna.akquise@leonaid.invalid", "Anna Akquise"),
            (USER_B, "bernd.binder@leonaid.invalid", "Bernd Binder"),
        ],
    )
    await connection.execute(
        """
        INSERT INTO charity_action (
            id, carrier_name, name, purpose, status, starts_on, ends_on,
            archive_slug, goal_value, actual_value, goal_unit, currency
        )
        VALUES (
            $1, 'Lions Club Beispielstadt', 'Krapfentaxi 2026',
            'Synthetischer Golden-Data-Nachweis', 'active', $2, $3,
            'krapfentaxi-2026', 100000, 0, 'cent', 'EUR'
        )
        """,
        ACTION,
        date(2026, 9, 1),
        date(2026, 11, 15),
    )


async def verify_constraints(connection: asyncpg.Connection[Any]) -> None:
    await expect_database_error(
        lambda: connection.execute(
            """
            INSERT INTO offering (
                id, action_id, name, status, unit, pieces_per_unit,
                unit_price_minor, currency
            )
            VALUES (
                '70000000-0000-4000-8000-000000000099', $1, 'Ungültig',
                'active', 'box', 24, -1, 'EUR'
            )
            """,
            ACTION,
        ),
        "negative Minor Units",
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            INSERT INTO acquisition_assignment (
                id, action_id, twenty_company_id, twenty_person_id,
                acquirer_user_id
            )
            VALUES (
                '60000000-0000-4000-8000-000000000099', $1, $2,
                '50000000-0000-4000-8000-000000000001', $3
            )
            """,
            ACTION,
            COMPANY,
            USER_A,
        ),
        "mehr als eine CRM-Partei",
    )
    await connection.execute(
        """
        INSERT INTO acquisition_assignment (
            id, action_id, twenty_company_id, acquirer_user_id
        )
        VALUES ($1, $2, $3, $4)
        """,
        ASSIGNMENT_A,
        ACTION,
        COMPANY,
        USER_A,
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            INSERT INTO acquisition_assignment (
                id, action_id, twenty_company_id, acquirer_user_id
            )
            VALUES (
                '60000000-0000-4000-8000-000000000098', $1, $2, $3
            )
            """,
            ACTION,
            COMPANY,
            USER_A,
        ),
        "doppelte Akquisiteur-Zuordnung",
    )
    await connection.execute(
        """
        INSERT INTO acquisition_assignment (
            id, action_id, twenty_company_id, acquirer_user_id
        )
        VALUES ($1, $2, $3, $4)
        """,
        ASSIGNMENT_B,
        ACTION,
        COMPANY,
        USER_B,
    )
    await expect_database_error(
        lambda: connection.execute(
            "UPDATE charity_action SET status = 'draft' WHERE id = $1",
            ACTION,
        ),
        "rückwärts gerichteter Aktionsstatus",
    )


async def verify_transactionality(connection: asyncpg.Connection[Any]) -> None:
    transaction = connection.transaction()
    await transaction.start()
    await connection.execute(
        "UPDATE charity_action SET actual_value = 7200 WHERE id = $1",
        ACTION,
    )
    await connection.execute(
        """
        INSERT INTO audit_event (
            id, action_id, actor_user_id, event_type, entity_type,
            entity_id, request_id, payload
        )
        VALUES ($1, $2, $3, 'goal.updated', 'charity_action', $2, $4, $5::jsonb)
        """,
        AUDIT,
        ACTION,
        USER_A,
        "poc021:system-admin:golden-v1",
        '{"actualValueMinor":7200}',
    )
    await connection.execute(
        """
        INSERT INTO outbox_event (
            id, aggregate_type, aggregate_id, event_type,
            idempotency_key, payload
        )
        VALUES ($1, 'charity_action', $2, 'goal.updated', $3, $4::jsonb)
        """,
        OUTBOX,
        ACTION,
        "poc021:goal:20000000-0000-4000-8000-000000000001:7200",
        '{"actualValueMinor":7200}',
    )
    await transaction.rollback()
    rolled_back = await connection.fetchrow(
        """
        SELECT
          (SELECT actual_value FROM charity_action WHERE id = $1) AS value,
          (SELECT count(*) FROM audit_event WHERE id = $2) AS audits,
          (SELECT count(*) FROM outbox_event WHERE id = $3) AS outbox
        """,
        ACTION,
        AUDIT,
        OUTBOX,
    )
    if rolled_back != {"value": 0, "audits": 0, "outbox": 0}:
        raise SchemaError(f"Rollback war nicht atomar: {dict(rolled_back or {})}")

    async with connection.transaction():
        await connection.execute(
            "UPDATE charity_action SET actual_value = 7200 WHERE id = $1",
            ACTION,
        )
        await connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type, entity_type,
                entity_id, request_id, payload
            )
            VALUES ($1, $2, $3, 'goal.updated', 'charity_action', $2, $4, $5::jsonb)
            """,
            AUDIT,
            ACTION,
            USER_A,
            "poc021:system-admin:golden-v1",
            '{"actualValueMinor":7200}',
        )
        await connection.execute(
            """
            INSERT INTO outbox_event (
                id, aggregate_type, aggregate_id, event_type,
                idempotency_key, payload
            )
            VALUES ($1, 'charity_action', $2, 'goal.updated', $3, $4::jsonb)
            """,
            OUTBOX,
            ACTION,
            "poc021:goal:20000000-0000-4000-8000-000000000001:7200",
            '{"actualValueMinor":7200}',
        )
    committed = await connection.fetchrow(
        """
        SELECT
          (SELECT actual_value FROM charity_action WHERE id = $1) AS value,
          (SELECT count(*) FROM audit_event WHERE id = $2) AS audits,
          (SELECT count(*) FROM outbox_event WHERE id = $3) AS outbox
        """,
        ACTION,
        AUDIT,
        OUTBOX,
    )
    if committed != {"value": 7200, "audits": 1, "outbox": 1}:
        raise SchemaError(f"Commit war nicht atomar: {dict(committed or {})}")

    occurred_at = await connection.fetchval(
        "SELECT occurred_at FROM audit_event WHERE id = $1",
        AUDIT,
    )
    if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
        raise SchemaError("Audit-Zeitpunkt ist nicht timezone-aware")


async def run(legacy: bool) -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=10)
    try:
        await verify_tables(connection, legacy)
        await insert_foundation(connection)
        await verify_constraints(connection)
        await verify_transactionality(connection)
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", action="store_true")
    arguments = parser.parse_args()
    try:
        asyncio.run(run(arguments.legacy))
    except (KeyError, OSError, SchemaError, asyncpg.PostgresError) as error:
        print(
            "poc021-schema: ERROR: "
            "requestId=poc021:system-admin:golden-v1 "
            f"type={type(error).__name__}",
            file=sys.stderr,
        )
        return 1
    mode = "Vorgänger-Upgrade" if arguments.legacy else "Leeraufbau"
    print(
        f"poc021-schema: OK: {mode}, Constraints, timezone-aware Daten "
        "und transaktionales Audit/Outbox"
    )
    return 0
