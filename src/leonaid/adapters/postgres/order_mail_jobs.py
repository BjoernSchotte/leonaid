"""Writes of the buyer's order mail jobs, shared by the order transactions.

Kept apart from ``adapters.postgres.order_mails`` (the worker's reader), which
imports the commitment repository that itself queues the confirmation.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from leonaid.domain.outbox import PendingOutboxEvent


async def internal_order_mails_enabled(
    connection: asyncpg.Connection[Any], action_id: UUID
) -> bool:
    """The action's switch; an action without a settings row has it off."""

    return bool(
        await connection.fetchval(
            "SELECT internal_order_mails FROM action_buyer_mail_configuration "
            "WHERE action_id = $1",
            action_id,
        )
    )


async def insert_order_mail_event(
    connection: asyncpg.Connection[Any],
    event: PendingOutboxEvent,
    occurred_at: datetime,
) -> None:
    """Write the mail job in the caller's transaction, at most once per key."""

    await connection.execute(
        """
        INSERT INTO outbox_event (
            id, aggregate_type, aggregate_id, event_type,
            idempotency_key, payload, available_at, created_at
        )
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $7)
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        event.id,
        event.aggregate_type,
        event.aggregate_id,
        event.event_type,
        event.idempotency_key,
        json.dumps(event.payload, separators=(",", ":")),
        occurred_at,
    )
