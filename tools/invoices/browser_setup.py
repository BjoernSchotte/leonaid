#!/usr/bin/env python3
"""Prepare ignored real sessions for the POC-090 browser proof."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import asyncpg

from leonaid.domain.sessions import (
    SESSION_LIFETIME,
    session_token_digest,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
DELIVERY_WINDOW_ID = UUID("98000000-0000-4000-8000-000000000002")
# System admin: switches the delivery.tours flag for the tours proof.
SIMONE_ID = UUID("10000000-0000-4000-8000-000000000001")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
FINN_ID = UUID("10000000-0000-4000-8000-000000000007")
# Anna (acquirer) also drives for the delivery board proof.
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
SESSION_NAMESPACE = UUID("ab77cb61-0df1-4df7-a3fb-fbf8bddf58b4")
# Review-ready golden order the bulk-release orders are copied from.
SOURCE_ORDER_ID = UUID("80000000-0000-4000-8000-000000000002")
# Complete, review-ready orders for the bulk invoice release proof.
BULK_ORDERS = (
    (UUID("80000000-0000-4000-8000-0000000000b1"), "Sammel Eins KG"),
    (UUID("80000000-0000-4000-8000-0000000000b2"), "Sammel Zwei KG"),
    (UUID("80000000-0000-4000-8000-0000000000b3"), "Sammel Drei KG"),
    # For tests/e2e/invoices-bulk-faults.spec.mjs.
    (UUID("80000000-0000-4000-8000-0000000000b4"), "Sammel Vier KG"),
    (UUID("80000000-0000-4000-8000-0000000000b5"), "Sammel Fünf KG"),
    (UUID("80000000-0000-4000-8000-0000000000b6"), "Sammel Sechs KG"),
    (UUID("80000000-0000-4000-8000-0000000000b7"), "Sammel Sieben KG"),
)


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


async def seed_bulk_orders(connection: asyncpg.Connection[Any]) -> None:
    """Copies the golden review-ready order into complete bulk-release orders.

    Same customer, lines and invoice recipient, plus a delivery address and
    the past window, so the single and the bulk review let them through.
    """
    window = await connection.fetchrow(
        "SELECT starts_at, ends_at FROM action_delivery_window WHERE id = $1",
        DELIVERY_WINDOW_ID,
    )
    if window is None:
        raise RuntimeError("The browser delivery window is missing.")
    zone = ZoneInfo("Europe/Berlin")
    snapshot = json.dumps(
        {
            "windowId": str(DELIVERY_WINDOW_ID),
            "startsAt": window["starts_at"].astimezone(zone).isoformat(),
            "endsAt": window["ends_at"].astimezone(zone).isoformat(),
            "timezone": "Europe/Berlin",
        }
    )
    for index, (order_id, name) in enumerate(BULK_ORDERS):
        if await connection.fetchval(
            "SELECT true FROM commitment WHERE id = $1", order_id
        ):
            continue
        async with connection.transaction():
            # CREATE TABLE AS takes no bind parameters; the id is a constant.
            await connection.execute(
                "CREATE TEMP TABLE bulk_order_copy ON COMMIT DROP AS "
                f"SELECT * FROM commitment WHERE id = '{SOURCE_ORDER_ID}'::uuid"
            )
            await connection.execute(
                """
                UPDATE bulk_order_copy SET
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
                        'streetLine1', 'Lagerweg 4',
                        'postalCode', '10243',
                        'city', 'Beispielstadt',
                        'countryCode', 'DE'
                    ),
                    delivery_window_id = $3,
                    delivery_window_snapshot = $4::jsonb,
                    delivery_contact_snapshot = NULL,
                    -- Every order has an order number, derived from its id.
                    public_reference = 'LA-' || upper(replace($1::uuid::text, '-', '')),
                    created_at = now() + make_interval(secs => $5),
                    updated_at = now() + make_interval(secs => $5)
                """,
                order_id,
                name,
                DELIVERY_WINDOW_ID,
                snapshot,
                index,
            )
            await connection.execute(
                "INSERT INTO commitment SELECT * FROM bulk_order_copy"
            )
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


async def main() -> None:
    output = Path(require_env("SESSION_OUTPUT"))
    now = datetime.now(timezone.utc)
    stale_at = now - timedelta(days=1)
    sessions = (
        (
            "KLARA_STALE_SESSION",
            KLARA_ID,
            "poc090-browser-klara-stale-session-token-value",
            stale_at,
            stale_at,
        ),
        (
            # A separate stale session: the bulk release proves its own
            # fresh sign-in round trip, whatever the single proof did.
            "KLARA_BULK_SESSION",
            KLARA_ID,
            "poc090-browser-klara-bulk-stale-session-token-value",
            stale_at,
            stale_at,
        ),
        (
            # The bulk fault proof signs in freshly on its own.
            "KLARA_FAULT_SESSION",
            KLARA_ID,
            "poc090-browser-klara-fault-stale-session-token-value",
            stale_at,
            stale_at,
        ),
        (
            # The delivery board proof; earlier proofs end Klara's other
            # sessions.
            "KLARA_BOARD_SESSION",
            KLARA_ID,
            "poc090-browser-klara-board-session-token-value",
            now,
            now,
        ),
        (
            "ANNA_DRIVER_SESSION",
            ANNA_ID,
            "poc090-browser-anna-driver-session-token-value",
            now,
            now,
        ),
        (
            "SIMONE_FLAG_SESSION",
            SIMONE_ID,
            "poc090-browser-simone-flag-session-token-value",
            now,
            now,
        ),
        (
            "FINN_SESSION",
            FINN_ID,
            "poc090-browser-finn-finance-session-token-value",
            now,
            now,
        ),
    )
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        await connection.execute(
            "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
            [KLARA_ID, FINN_ID, ANNA_ID, SIMONE_ID],
        )
        await connection.execute(
            """
            INSERT INTO action_membership (id, action_id, user_id, role)
            VALUES ($1, $2, $3, 'driver')
            ON CONFLICT ON CONSTRAINT uq_action_membership_role DO NOTHING
            """,
            uuid5(SESSION_NAMESPACE, "anna-driver"),
            ACTION_ID,
            ANNA_ID,
        )
        for name, user_id, token, created_at, fresh_login_at in sessions:
            await connection.execute(
                """
                INSERT INTO user_session (
                    id, user_id, token_digest, expires_at,
                    last_seen_at, fresh_login_at, device_hint,
                    created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, 'POC-090 Browser',
                        $7, $5)
                """,
                uuid5(SESSION_NAMESPACE, name),
                user_id,
                session_token_digest(token),
                created_at + SESSION_LIFETIME,
                now,
                fresh_login_at,
                created_at,
            )
        # Delivery planning was enabled after the golden orders were captured
        # and its only window has already passed: the browser proof records the
        # delivery historically before issuing.
        await connection.execute(
            """
            INSERT INTO charity_action_capability (action_id, capability)
            VALUES ($1, 'delivery') ON CONFLICT DO NOTHING
            """,
            ACTION_ID,
        )
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
        await connection.execute(
            """
            INSERT INTO action_delivery_window (id, action_id, starts_at, ends_at)
            -- A fixed local day time in the past: a window may not cross local
            -- midnight. Windows survive the golden reset, so this day differs
            -- from the server contract window to avoid an overlap.
            VALUES ($1, $2,
                ((now() AT TIME ZONE 'Europe/Berlin')::date - 3 + time '10:00')
                    AT TIME ZONE 'Europe/Berlin',
                ((now() AT TIME ZONE 'Europe/Berlin')::date - 3 + time '12:00')
                    AT TIME ZONE 'Europe/Berlin')
            ON CONFLICT (id) DO NOTHING
            """,
            DELIVERY_WINDOW_ID,
            ACTION_ID,
        )
        await seed_bulk_orders(connection)
    finally:
        await connection.close()

    output.write_text(
        "".join(
            f"{name}={token}\n" for name, _user_id, token, _created, _fresh in sessions
        ),
        encoding="utf-8",
    )
    output.chmod(0o600)
    print(
        "invoice-browser-setup: OK: stale admin and finance reader sessions, "
        "delivery planning enabled after capture, its window already past, "
        "complete review-ready orders for the bulk release"
    )


if __name__ == "__main__":
    asyncio.run(main())
