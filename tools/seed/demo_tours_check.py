"""Proof helper of tools/seed/demo_tours_test.sh.

``fingerprint`` prints a digest of every row the demo seed may touch;
``drivers`` reads the delivery board as Dora and as Emil, the way the app
does for their session, and checks they see exactly their own stops.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any

import asyncpg

from tools.seed.demo_tours import (
    ACTION_ID,
    DELIVERY_DAY,
    DORA,
    DRIVERS,
    ORDERS,
    load_principal,
)
from leonaid.adapters.postgres.delivery_board import AsyncpgDeliveryBoardRepository
from leonaid.application.delivery_board import DeliveryBoardService

FINGERPRINT = """
SELECT md5(concat_ws('|',
    (SELECT count(*) FROM audit_event),
    (SELECT count(*) FROM command_receipt),
    (SELECT string_agg(concat_ws(',', id, status, updated_at,
        delivery_window_id), ';' ORDER BY id) FROM commitment),
    (SELECT string_agg(concat_ws(',', commitment_id, driver_user_id,
        driver_assigned_at, state, state_changed_at, revision), ';'
        ORDER BY commitment_id) FROM commitment_delivery),
    (SELECT string_agg(concat_ws(',', id, starts_at, ends_at, retired),
        ';' ORDER BY id) FROM action_delivery_window),
    (SELECT string_agg(concat_ws(',', action_id, enabled, revision),
        ';' ORDER BY action_id) FROM action_delivery_configuration),
    (SELECT string_agg(concat_ws(',', id, status, updated_at), ';'
        ORDER BY id) FROM offering),
    (SELECT string_agg(concat_ws(',', id, email, status, updated_at), ';'
        ORDER BY id) FROM user_account),
    (SELECT string_agg(concat_ws(',', id, user_id, role), ';'
        ORDER BY id) FROM action_membership)
))
"""


async def fingerprint(pool: asyncpg.Pool[Any]) -> None:
    print(await pool.fetchval(FINGERPRINT))


async def drivers(pool: asyncpg.Pool[Any]) -> None:
    service = DeliveryBoardService(AsyncpgDeliveryBoardRepository(pool))
    keys = {
        str(row["idempotency_key"]): str(row["commitment_id"])
        for row in await pool.fetch(
            "SELECT idempotency_key, result->>'commitmentId' AS commitment_id"
            " FROM command_receipt WHERE idempotency_key = ANY($1::text[])",
            [order.idempotency_key for order in ORDERS],
        )
    }
    for driver in DRIVERS:
        board = await service.board(
            await load_principal(pool, driver.id),
            ACTION_ID,
            day=DELIVERY_DAY,
            viewed_at=datetime.now(timezone.utc),
        )
        assert board.day == DELIVERY_DAY and not board.manager, board
        seen = {
            str(drop.commitment_id) for window in board.windows for drop in window.drops
        }
        wanted = {
            keys[order.idempotency_key] for order in ORDERS if order.driver == driver
        }
        assert seen == wanted, (driver.key, sorted(seen), sorted(wanted))
        delivered = sum(
            drop.state.value == "delivered"
            for window in board.windows
            for drop in window.drops
        )
        assert delivered == (2 if driver == DORA else 0), (driver.key, delivered)
        assert all(
            drop.order_status is None and drop.driver_name is None
            for window in board.windows
            for drop in window.drops
        ), "drivers see no order status or driver names"
        print(
            f"demo-tours-test: {driver.display_name} sees exactly their"
            f" {len(seen)} stops ({delivered} delivered)"
        )


async def main(command: str) -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=2
    )
    try:
        await (fingerprint if command == "fingerprint" else drivers)(pool)
    finally:
        await pool.close()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"fingerprint", "drivers"}:
        raise SystemExit("usage: demo_tours_check.py fingerprint|drivers")
    asyncio.run(main(sys.argv[1]))
