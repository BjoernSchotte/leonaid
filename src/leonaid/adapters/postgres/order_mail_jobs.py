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

from leonaid.application.order_mails import (
    OrderMailKind,
    OrderMailLinks,
    confirmation_not_due_reason,
    order_mail_event,
)
from leonaid.domain.commitments import Commitment
from leonaid.domain.outbox import PendingOutboxEvent

# Ledger rows of one mail: its first key and its ``:resend:{n}`` keys lie
# between the first key and the same text followed by ";" (the character
# after ":") in byte order. ``ix_mail_delivery_key_c`` serves it. $1 is the
# first key.
SENT_KEY_RANGE = (
    '(idempotency_key COLLATE "C" >= $1 AND idempotency_key COLLATE "C" < $1 || \';\')'
)


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


async def queue_confirmation(
    connection: asyncpg.Connection[Any],
    commitment: Commitment,
    *,
    mail_links: OrderMailLinks | None,
    occurred_at: datetime,
) -> None:
    """Queue the confirmation of an internal order that became review-ready.

    Called in the transaction that makes the order ``review_ready`` (its
    creation, the completion of its draft, the manager completion of a
    draft), once: a replay of each command returns before this point, and
    the job key is the order's. Nothing is queued when the confirmation is
    not due (``confirmation_not_due_reason``): switch off, no address, or
    an order that is recorded after its delivery or after the action closed.
    """

    if mail_links is None:
        return
    row = await connection.fetchrow(
        """
        SELECT action.status,
            COALESCE(mails.internal_order_mails, false) AS internal_order_mails,
            delivery.state AS drop_state
        FROM charity_action AS action
        LEFT JOIN action_buyer_mail_configuration AS mails
          ON mails.action_id = action.id
        LEFT JOIN commitment_delivery AS delivery
          ON delivery.commitment_id = $2
        WHERE action.id = $1
        """,
        commitment.action_id,
        commitment.id,
    )
    if row is None or (
        confirmation_not_due_reason(
            commitment,
            internal_order_mails=bool(row["internal_order_mails"]),
            drop_state=(
                str(row["drop_state"]) if row["drop_state"] is not None else None
            ),
            action_status=str(row["status"]),
            now=occurred_at,
        )
        is not None
    ):
        return
    await insert_order_mail_event(
        connection,
        order_mail_event(
            OrderMailKind.CONFIRMATION,
            action_id=commitment.action_id,
            commitment_id=commitment.id,
            links=mail_links,
        ),
        occurred_at,
    )
