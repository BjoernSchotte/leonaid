#!/usr/bin/env python3
"""Undo the browser spec's delivery windows on the golden action.

Delivery planning cannot be switched off through the API once it was on
(delivery_disable_forbidden: windows are retired instead). The spec's last
case turns it on for the shared stack, so this restores the golden state:
the two proof windows (12 Nov 2026, 08–10 and 10–12 Berlin time) are
retired unless an order booked them (windows are never deleted), and planning
is off again when no open window is left. Runs after the browser step, whatever its outcome.
"""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

import asyncpg

from tools.identity.contract import ACTIVE_ACTION_ID


async def main(action_id: UUID) -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=10)
    try:
        async with connection.transaction():
            # Windows are never deleted (a trigger forbids it); retire them.
            retired = await connection.execute(
                """
                UPDATE action_delivery_window AS window_row
                SET retired = true
                WHERE window_row.action_id = $1
                  AND NOT window_row.retired
                  AND (window_row.starts_at AT TIME ZONE 'Europe/Berlin')::date
                      = DATE '2026-11-12'
                  AND NOT EXISTS (
                    SELECT 1 FROM commitment
                    WHERE commitment.delivery_window_id = window_row.id
                  )
                """,
                action_id,
            )
            await connection.execute(
                """
                UPDATE action_delivery_configuration
                SET enabled = false, revision = revision + 1
                WHERE action_id = $1
                  AND enabled
                  AND NOT EXISTS (
                    SELECT 1 FROM action_delivery_window
                    WHERE action_id = $1 AND NOT retired
                  )
                """,
                action_id,
            )
    finally:
        await connection.close()
    print(f"public-orders-delivery-cleanup: OK: {retired}")


if __name__ == "__main__":
    asyncio.run(main(ACTIVE_ACTION_ID))
