#!/usr/bin/env python3
"""Today's tour for the offline tour browser proof (tests/e2e/pwa-offline-tour).

``setup``: Dora, who only drives, gets a session and three review-ready
orders in a window today, ranked by the planner; ``delivery.tours`` is on.
Repeatable: marks, driver order and reads go back to the start.
``teardown``: the orders and Dora's reads, sessions and membership go,
the window is retired, Dora's account suspended (the audit log keeps her
marks); the flag and delivery planning are off again, as the other
offline specs expect.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import asyncpg

from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
DORA_ID = UUID("10000000-0000-4000-8000-0000000000d1")
# The golden review-ready order the tour orders are copied from.
SOURCE_ORDER_ID = UUID("80000000-0000-4000-8000-000000000002")
ORDERS = (
    (UUID("80000000-0000-4000-8000-0000000000d1"), "Tour Eins KG", "Erster Weg 1"),
    (UUID("80000000-0000-4000-8000-0000000000d2"), "Tour Zwei KG", "Zweiter Weg 2"),
    (UUID("80000000-0000-4000-8000-0000000000d3"), "Tour Drei KG", "Dritter Weg 3"),
)
NAMESPACE = UUID("4f3c8d0e-5b7a-4a43-9a51-0c6f3e1d2b10")
ZONE = ZoneInfo("Europe/Berlin")


def token() -> str:
    # The same shape as tools/pwa/contract.py; the spec derives it too.
    return f"poc062-{DORA_ID}-server-session-token-value"


async def setup(connection: asyncpg.Connection[Any]) -> None:
    now = datetime.now(timezone.utc)
    await connection.execute(
        """
        INSERT INTO user_account (id, email, display_name, status)
        VALUES ($1, 'dora.fahrer@leonaid.invalid', 'Dora Fahrer', 'active')
        ON CONFLICT (id) DO UPDATE SET status = 'active'
        """,
        DORA_ID,
    )
    await connection.execute(
        """
        INSERT INTO action_membership (id, action_id, user_id, role)
        VALUES ($1, $2, $3, 'driver')
        ON CONFLICT ON CONSTRAINT uq_action_membership_role DO NOTHING
        """,
        uuid5(NAMESPACE, "dora-driver"),
        ACTION_ID,
        DORA_ID,
    )
    await connection.execute("DELETE FROM user_session WHERE user_id = $1", DORA_ID)
    await connection.execute(
        """
        INSERT INTO user_session (
            id, user_id, token_digest, expires_at, last_seen_at,
            fresh_login_at, created_at, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $5, $5, $5)
        """,
        uuid5(NAMESPACE, "dora-session"),
        DORA_ID,
        session_token_digest(token()),
        now + SESSION_LIFETIME,
        now,
    )
    # The golden action has the delivery capability; setup only relies on
    # it, so teardown has nothing of it to undo.
    if not await connection.fetchval(
        "SELECT true FROM charity_action_capability"
        " WHERE action_id = $1 AND capability = 'delivery'",
        ACTION_ID,
    ):
        raise RuntimeError("The golden action lacks the delivery capability.")
    await connection.execute(
        """
        INSERT INTO action_delivery_configuration (action_id, enabled)
        VALUES ($1, true)
        ON CONFLICT (action_id) DO UPDATE
        SET enabled = true,
            revision = action_delivery_configuration.revision + 1
        """,
        ACTION_ID,
    )
    window = await today_window(connection)
    window_id = window["id"]
    snapshot = json.dumps(
        {
            "windowId": str(window_id),
            "startsAt": window["starts_at"].astimezone(ZONE).isoformat(),
            "endsAt": window["ends_at"].astimezone(ZONE).isoformat(),
            "timezone": "Europe/Berlin",
        }
    )
    # An open window: a closure left by an earlier run goes.
    for position, (order_id, name, street) in enumerate(ORDERS, start=1):
        async with connection.transaction():
            if not await connection.fetchval(
                "SELECT true FROM commitment WHERE id = $1", order_id
            ):
                await copy_order(
                    connection, order_id, name, street, window_id, snapshot
                )
            else:
                await connection.execute(
                    """
                    UPDATE commitment
                    SET delivery_window_id = $2,
                        delivery_window_snapshot = $3::jsonb
                    WHERE id = $1
                    """,
                    order_id,
                    window_id,
                    snapshot,
                )
            await connection.execute(
                """
                INSERT INTO commitment_delivery (
                    commitment_id, action_id, driver_user_id,
                    driver_assigned_by_user_id, driver_assigned_at,
                    base_position
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (commitment_id) DO UPDATE SET
                    driver_user_id = EXCLUDED.driver_user_id,
                    driver_assigned_by_user_id = EXCLUDED.driver_assigned_by_user_id,
                    driver_assigned_at = EXCLUDED.driver_assigned_at,
                    base_position = EXCLUDED.base_position,
                    driver_position = NULL,
                    driver_ordered_at = NULL,
                    state = NULL,
                    state_changed_at = NULL,
                    state_changed_by_user_id = NULL,
                    missed_at_closure = false,
                    revision = commitment_delivery.revision + 1
                """,
                order_id,
                ACTION_ID,
                DORA_ID,
                KLARA_ID,
                now,
                position,
            )
    await connection.execute(
        "DELETE FROM delivery_read_audit WHERE driver_user_id = $1", DORA_ID
    )
    await set_tours_flag(connection, True)


async def today_window(connection: asyncpg.Connection[Any]) -> asyncpg.Record:
    """An open window over the whole local day (never across midnight).

    Windows are never deleted or reopened once retired (the database keeps
    them), so a run after a teardown on the same day takes the next one.
    """
    day = await connection.fetchval("SELECT (now() AT TIME ZONE 'Europe/Berlin')::date")
    for attempt in range(100):
        window_id = uuid5(NAMESPACE, f"tour-window-{day}-{attempt}")
        row = await connection.fetchrow(
            """
            INSERT INTO action_delivery_window (id, action_id, starts_at, ends_at)
            VALUES ($1, $2,
                ($3::date + time '00:00') AT TIME ZONE 'Europe/Berlin',
                ($3::date + time '23:59') AT TIME ZONE 'Europe/Berlin')
            ON CONFLICT (id) DO UPDATE SET retired = action_delivery_window.retired
            RETURNING id, starts_at, ends_at, retired
            """,
            window_id,
            ACTION_ID,
            day,
        )
        assert row is not None
        if row["retired"]:
            continue
        closed = await connection.fetchval(
            "SELECT true FROM delivery_window_closure WHERE window_id = $1",
            window_id,
        )
        if not closed:
            return row
    raise RuntimeError("No open tour window left for today.")


async def copy_order(
    connection: asyncpg.Connection[Any],
    order_id: UUID,
    name: str,
    street: str,
    window_id: UUID,
    snapshot: str,
) -> None:
    # CREATE TABLE AS takes no bind parameters; the id is a constant.
    await connection.execute(
        "CREATE TEMP TABLE tour_order_copy ON COMMIT DROP AS "
        f"SELECT * FROM commitment WHERE id = '{SOURCE_ORDER_ID}'::uuid"
    )
    await connection.execute(
        """
        UPDATE tour_order_copy SET
            id = $1,
            status = 'review_ready',
            customer_snapshot = jsonb_set(
                customer_snapshot::jsonb, '{displayName}', to_jsonb($2::text)
            )::json,
            invoice_recipient_snapshot = jsonb_set(
                invoice_recipient_snapshot::jsonb,
                '{recipientName}',
                to_jsonb($2::text)
            )::json,
            delivery_recipient_snapshot = jsonb_build_object(
                'recipientName', $2::text,
                'streetLine1', $3::text,
                'postalCode', '10243',
                'city', 'Beispielstadt',
                'countryCode', 'DE'
            ),
            delivery_window_id = $4,
            delivery_window_snapshot = $5::jsonb,
            delivery_contact_snapshot = NULL,
            -- Every order has an order number, derived from its id.
            public_reference = 'LA-' || upper(replace($1::uuid::text, '-', '')),
            created_at = now(),
            updated_at = now()
        """,
        order_id,
        name,
        street,
        window_id,
        snapshot,
    )
    await connection.execute("INSERT INTO commitment SELECT * FROM tour_order_copy")
    await connection.execute(
        """
        INSERT INTO commitment_line (
            id, commitment_id, offering_id, description_snapshot,
            quantity, unit_snapshot, pieces_per_unit_snapshot,
            unit_price_minor, line_total_minor
        )
        SELECT
            gen_random_uuid(), $1, offering_id, description_snapshot,
            quantity, unit_snapshot, pieces_per_unit_snapshot,
            unit_price_minor, line_total_minor
        FROM commitment_line
        WHERE commitment_id = $2
        """,
        order_id,
        SOURCE_ORDER_ID,
    )


async def set_tours_flag(connection: asyncpg.Connection[Any], enabled: bool) -> None:
    await connection.execute(
        """
        UPDATE feature_flag SET enabled = $1, revision = revision + 1
        WHERE key = 'delivery.tours' AND enabled IS DISTINCT FROM $1
        """,
        enabled,
    )


async def teardown(connection: asyncpg.Connection[Any]) -> None:
    ids = [order_id for order_id, _name, _street in ORDERS]
    windows = [
        row["delivery_window_id"]
        for row in await connection.fetch(
            "SELECT DISTINCT delivery_window_id FROM commitment"
            " WHERE id = ANY($1::uuid[]) AND delivery_window_id IS NOT NULL",
            ids,
        )
    ]
    async with connection.transaction():
        await set_tours_flag(connection, False)
        await connection.execute(
            "DELETE FROM delivery_read_audit WHERE window_id = ANY($1::uuid[])",
            windows,
        )
        await connection.execute(
            "DELETE FROM commitment_line WHERE commitment_id = ANY($1::uuid[])", ids
        )
        await connection.execute(
            "DELETE FROM commitment WHERE id = ANY($1::uuid[])", ids
        )
        # Windows are retired, never deleted (protect_delivery_window).
        await connection.execute(
            "UPDATE action_delivery_window SET retired = true"
            " WHERE id = ANY($1::uuid[]) AND NOT retired",
            windows,
        )
        await connection.execute(
            """
            UPDATE action_delivery_configuration
            SET enabled = false, revision = revision + 1
            WHERE action_id = $1 AND enabled
            """,
            ACTION_ID,
        )
        await connection.execute(
            "DELETE FROM delivery_read_audit WHERE driver_user_id = $1", DORA_ID
        )
        await connection.execute("DELETE FROM user_session WHERE user_id = $1", DORA_ID)
        await connection.execute(
            "DELETE FROM action_membership WHERE user_id = $1", DORA_ID
        )
        # Her marks stay in the append-only audit log (audit_event refers
        # to her account), so the account is suspended, not deleted; setup
        # makes it active again.
        await connection.execute(
            "UPDATE user_account SET status = 'suspended' WHERE id = $1"
            " AND status = 'active'",
            DORA_ID,
        )


async def main(mode: str) -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=10)
    try:
        if mode == "setup":
            await setup(connection)
        elif mode == "teardown":
            await teardown(connection)
        else:
            raise SystemExit(f"tour-setup: unknown mode {mode}")
    finally:
        await connection.close()
    print(f"pwa-tour-setup: OK: {mode}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "setup"))
