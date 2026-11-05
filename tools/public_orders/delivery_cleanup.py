#!/usr/bin/env python3
"""Undo the browser spec's delivery windows on the golden action.

Delivery planning cannot be switched off through the API once it was on
(delivery_disable_forbidden: windows are retired instead). The spec's
delivery cases turn it on for the shared stack, so this restores the golden
state from the spec's state file (LEONAID_E2E_DELIVERY_STATE):

- the proof windows it lists are retired unless an order booked them
  (windows are never deleted);
- an action period the spec extended is set back, once no open window lies
  outside it;
- planning is off again when no open window is left.

Runs before the browser step (a leftover of an interrupted run) and after
it, whatever its outcome. No dates are hard-coded: the spec computes its
delivery day from today.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

from tools.identity.contract import ACTIVE_ACTION_ID


def load_state(path: Path) -> dict[str, list[Any]]:
    if not path.exists():
        return {"windowIds": [], "periods": []}
    state = json.loads(path.read_text(encoding="utf-8"))
    window_ids = state.get("windowIds") if isinstance(state, dict) else None
    periods = state.get("periods") if isinstance(state, dict) else None
    if not isinstance(window_ids, list) or not isinstance(periods, list):
        raise ValueError(f"{path}: unexpected delivery state")
    return {"windowIds": window_ids, "periods": periods}


async def main(action_id: UUID, state_path: Path) -> None:
    state = load_state(state_path)
    window_ids = [UUID(value) for value in state["windowIds"]]
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
            restored = "period unchanged"
            periods = [p for p in state["periods"] if UUID(p["actionId"]) == action_id]
            if periods:
                # The first record holds the period before any extension.
                starts_on = date.fromisoformat(periods[0]["startsOn"])
                ends_on = date.fromisoformat(periods[0]["endsOn"])
                outside = await connection.fetchval(
                    """
                    SELECT count(*) FROM action_delivery_window
                    WHERE action_id = $1 AND NOT retired
                      AND NOT (
                        (starts_at AT TIME ZONE 'Europe/Berlin')::date
                        BETWEEN $2 AND $3
                      )
                    """,
                    action_id,
                    starts_on,
                    ends_on,
                )
                if outside:
                    raise RuntimeError(
                        f"{outside} open window(s) outside the original period"
                    )
                restored = await connection.execute(
                    """
                    UPDATE charity_action
                    SET starts_on = $2, ends_on = $3,
                        revision = revision + 1, updated_at = $4
                    WHERE id = $1 AND (starts_on, ends_on) <> ($2, $3)
                    """,
                    action_id,
                    starts_on,
                    ends_on,
                    datetime.now(timezone.utc),
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
    print(f"public-orders-delivery-cleanup: OK: {retired}; {restored}")


if __name__ == "__main__":
    asyncio.run(main(ACTIVE_ACTION_ID, Path(sys.argv[1])))
