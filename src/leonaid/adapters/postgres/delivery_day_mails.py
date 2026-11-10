"""PostgreSQL side of the delivery-day mail sweep."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg

from leonaid.adapters.postgres.order_mail_jobs import insert_order_mail_event
from leonaid.application.delivery_day_mails import (
    DeliveryDayMailRepository,
    DueDeliveryDayMail,
    delivery_day_event,
)
from leonaid.application.order_mails import KEY_PREFIXES, OrderMailKind, OrderMailLinks

# One worker at a time runs the sweep. The key is this sweep's alone: every
# integer advisory lock of Core has its own
# (``tests/unit/test_advisory_locks.py``).
DELIVERY_DAY_SWEEP_LOCK = 527065

# ``order_mails.delivery_day_not_due_reason`` in SQL, plus "no job and no
# ledger row for this order and window". $1 = now, $2 = key prefix, $3 = limit.
DUE_SQL = """
SELECT commitment.action_id, commitment.id AS commitment_id,
    delivery_window.id AS window_id
FROM action_buyer_mail_configuration AS mails
JOIN charity_action AS action
  ON action.id = mails.action_id
JOIN action_delivery_configuration AS settings
  ON settings.action_id = mails.action_id
JOIN action_delivery_window AS delivery_window
  ON delivery_window.action_id = mails.action_id
JOIN commitment
  ON commitment.delivery_window_id = delivery_window.id
LEFT JOIN commitment_delivery AS delivery
  ON delivery.commitment_id = commitment.id
WHERE mails.delivery_day_mail
  AND action.status NOT IN ('completed', 'archived')
  AND EXISTS (
    SELECT 1 FROM charity_action_capability AS capability
    WHERE capability.action_id = mails.action_id
      AND capability.capability = 'delivery'
  )
  AND (delivery_window.starts_at AT TIME ZONE settings.timezone)::date
      = ($1::timestamptz AT TIME ZONE settings.timezone)::date
  AND ($1::timestamptz AT TIME ZONE settings.timezone)::time
      >= mails.delivery_day_send_time
  AND $1::timestamptz < delivery_window.ends_at
  AND commitment.status IN ('review_ready', 'confirmed', 'invoiced')
  AND delivery.state IS NULL
  AND btrim(COALESCE(commitment.customer_snapshot ->> 'email', '')) <> ''
  AND NOT EXISTS (
    SELECT 1 FROM outbox_event AS job
    WHERE job.idempotency_key
        = $2 || commitment.id::text || ':' || delivery_window.id::text
  )
  AND NOT EXISTS (
    SELECT 1 FROM mail_delivery AS sent
    WHERE sent.idempotency_key
        = $2 || commitment.id::text || ':' || delivery_window.id::text
  )
ORDER BY delivery_window.starts_at, commitment.id
LIMIT $3
"""


class AsyncpgDeliveryDayMailRepository(DeliveryDayMailRepository):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def queue_due(
        self, *, now: datetime, limit: int, links: OrderMailLinks
    ) -> int | None:
        async with self._pool.acquire() as connection, connection.transaction():
            # Held until the transaction ends: a second worker skips the run.
            if not await connection.fetchval(
                "SELECT pg_try_advisory_xact_lock($1)", DELIVERY_DAY_SWEEP_LOCK
            ):
                return None
            rows = await connection.fetch(
                DUE_SQL, now, KEY_PREFIXES[OrderMailKind.DELIVERY_DAY], limit
            )
            for row in rows:
                await insert_order_mail_event(
                    connection,
                    delivery_day_event(
                        DueDeliveryDayMail(
                            action_id=row["action_id"],
                            commitment_id=row["commitment_id"],
                            window_id=row["window_id"],
                        ),
                        links,
                    ),
                    now,
                )
            return len(rows)
