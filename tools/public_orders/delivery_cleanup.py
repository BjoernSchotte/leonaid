#!/usr/bin/env python3
"""Undo the browser spec's delivery windows on the golden action.

Delivery planning cannot be switched off through the API once it was on
(delivery_disable_forbidden: windows are retired instead). The spec's
delivery cases turn it on for the shared stack, so this restores the golden
state from the spec's state file (LEONAID_E2E_DELIVERY_STATE):

- the proof windows it lists are retired unless an order booked them
  (windows are never deleted);
- planning is off again when no open window is left.

Runs before the browser step (a leftover of an interrupted run) and after
it, whatever its outcome. No dates are hard-coded: the spec computes its
delivery day from today, inside the seeded period (tools/seed/golden.py).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

from tools.identity.contract import ACTIVE_ACTION_ID


def load_window_ids(path: Path) -> list[UUID]:
    if not path.exists():
        return []
    state: Any = json.loads(path.read_text(encoding="utf-8"))
    window_ids = state.get("windowIds") if isinstance(state, dict) else None
    if not isinstance(window_ids, list):
        raise ValueError(f"{path}: unexpected delivery state")
    return [UUID(str(value)) for value in window_ids]


async def main(action_id: UUID, state_path: Path) -> None:
    window_ids = load_window_ids(state_path)
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=10)
    try:
        async with connection.transaction():
            # Windows are never deleted (a trigger forbids it); retire them.
            retired = await connection.execute(
                """
                UPDATE action_delivery_window AS window_row
                -- Retiring clears "ausgebucht" (a retired window is never
                -- full), as AsyncpgDeliveryRepository.save does.
                SET retired = true, fully_booked = false
                WHERE window_row.action_id = $1
                  AND window_row.id = ANY($2::uuid[])
                  AND NOT window_row.retired
                  AND NOT EXISTS (
                    SELECT 1 FROM commitment
                    WHERE commitment.delivery_window_id = window_row.id
                  )
                """,
                action_id,
                window_ids,
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
    # Everything in the state file is undone; a later run starts clean.
    state_path.unlink(missing_ok=True)
    print(f"public-orders-delivery-cleanup: OK: {retired}")


if __name__ == "__main__":
    asyncio.run(main(ACTIVE_ACTION_ID, Path(sys.argv[1])))
