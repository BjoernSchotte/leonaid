"""PostgreSQL reads for the buyer's order mails (``application.order_mails``)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import asyncpg

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.order_mail_jobs import (
    SENT_KEY_RANGE,
    insert_order_mail_event,
    internal_order_mails_enabled,
)
from leonaid.application.order_mails import (
    ORDER_MAIL_KEY_PREFIXES,
    OrderCancellationFacts,
    OrderMailFacts,
    OrderMailKind,
    mailbox_key,
)
from leonaid.domain.calendar import INSTALLATION_TIME_ZONE
from leonaid.domain.commitments import CommitmentStatus

__all__ = [
    "AsyncpgOrderMailReader",
    "insert_order_mail_event",
    "internal_order_mails_enabled",
]


async def count_recent_order_mails(
    connection: asyncpg.Connection[Any],
    *,
    recipient_sha256: str,
    mailbox: str,
    since: datetime,
) -> int:
    """Order mails sent since the moment to the address or its mailbox.

    The ledger keeps only a digest of the exact address, so the mailbox
    comparison (``+tag``, Gmail dots) needs the address of the mail's order.
    """

    rows = await connection.fetch(
        """
        SELECT mail.recipient_sha256,
            commitment.customer_snapshot->>'email' AS email
        FROM mail_delivery AS mail
        LEFT JOIN commitment
          ON commitment.id::text = split_part(mail.idempotency_key, ':', 2)
        WHERE mail.sent_at >= $1
          AND mail.status = 'sent'
          AND mail.idempotency_key LIKE ANY($2::text[])
        """,
        since,
        [f"{prefix}%" for prefix in ORDER_MAIL_KEY_PREFIXES],
    )
    return sum(
        1
        for row in rows
        if row["recipient_sha256"] == recipient_sha256
        or (row["email"] is not None and mailbox_key(str(row["email"])) == mailbox)
    )


class AsyncpgOrderMailReader:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def facts(
        self, commitment_id: UUID, kind: OrderMailKind
    ) -> OrderMailFacts | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT commitment.created_at, action.name AS action_name,
                    action.status AS action_status,
                    EXISTS (
                        SELECT 1 FROM charity_action_capability AS capability
                        WHERE capability.action_id = action.id
                          AND capability.capability = 'invoicing'
                    ) AS invoicing,
                    COALESCE(mails.internal_order_mails, false)
                        AS internal_order_mails,
                    COALESCE(mails.delivery_day_mail, false) AS delivery_day_mail,
                    EXISTS (
                        SELECT 1 FROM charity_action_capability AS capability
                        WHERE capability.action_id = commitment.action_id
                          AND capability.capability = 'delivery'
                    ) AS delivery_capability,
                    delivery_settings.timezone AS delivery_zone,
                    delivery.state AS drop_state
                FROM commitment
                JOIN charity_action AS action ON action.id = commitment.action_id
                LEFT JOIN action_buyer_mail_configuration AS mails
                  ON mails.action_id = commitment.action_id
                LEFT JOIN action_delivery_configuration AS delivery_settings
                  ON delivery_settings.action_id = commitment.action_id
                LEFT JOIN commitment_delivery AS delivery
                  ON delivery.commitment_id = commitment.id
                WHERE commitment.id = $1
                """,
                commitment_id,
            )
            if row is None:
                return None
            commitment = await AsyncpgCommitmentRepository._get(
                connection, commitment_id, replayed=False
            )
            cancellation: OrderCancellationFacts | None = None
            if kind is OrderMailKind.CANCELLATION:
                cancelled = await connection.fetchrow(
                    """
                    SELECT cancellation.requested_at, invoice.number,
                        cancellation.previous_status
                    FROM commitment_cancellation AS cancellation
                    LEFT JOIN invoice_cancellation
                      ON invoice_cancellation.id
                         = cancellation.invoice_cancellation_id
                    LEFT JOIN invoice
                      ON invoice.id = invoice_cancellation.invoice_id
                    WHERE cancellation.commitment_id = $1
                    """,
                    commitment_id,
                )
                if cancelled is None:
                    return None
                cancellation = OrderCancellationFacts(
                    cancelled_at=cancelled["requested_at"],
                    invoice_number=(
                        str(cancelled["number"])
                        if cancelled["number"] is not None
                        else None
                    ),
                    previous_status=CommitmentStatus(str(cancelled["previous_status"])),
                )
        return OrderMailFacts(
            action_name=str(row["action_name"]),
            commitment=commitment,
            ordered_at=row["created_at"],
            cancellation=cancellation,
            internal_order_mails=bool(row["internal_order_mails"]),
            action_status=str(row["action_status"]),
            invoicing=bool(row["invoicing"]),
            drop_state=(
                str(row["drop_state"]) if row["drop_state"] is not None else None
            ),
            delivery_day_mail=bool(row["delivery_day_mail"]),
            delivery_capability=bool(row["delivery_capability"]),
            delivery_zone=(
                ZoneInfo(str(row["delivery_zone"]))
                if row["delivery_zone"] is not None
                else INSTALLATION_TIME_ZONE
            ),
        )

    async def was_sent(self, idempotency_key: str) -> bool:
        async with self._pool.acquire() as connection:
            return bool(
                await connection.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM mail_delivery "
                    "WHERE idempotency_key = $1 AND status = 'sent')",
                    idempotency_key,
                )
            )

    async def sent_keys(self, first_key: str) -> tuple[str, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT idempotency_key FROM mail_delivery "
                f"WHERE status = 'sent' AND {SENT_KEY_RANGE}",
                first_key,
            )
        return tuple(str(row["idempotency_key"]) for row in rows)

    async def recent_order_mails(
        self, *, recipient_sha256: str, mailbox: str, since: datetime
    ) -> int:
        async with self._pool.acquire() as connection:
            return await count_recent_order_mails(
                connection,
                recipient_sha256=recipient_sha256,
                mailbox=mailbox,
                since=since,
            )

    @asynccontextmanager
    async def recipient_lock(self, digest: str) -> AsyncIterator[None]:
        # A session lock on its own connection, held across the count and
        # the SMTP send; released even when the send fails.
        async with self._pool.acquire() as connection:
            key = f"order-mail-recipient:{digest}"
            await connection.execute(
                "SELECT pg_advisory_lock(hashtextextended($1, 0))", key
            )
            try:
                yield
            finally:
                await connection.execute(
                    "SELECT pg_advisory_unlock(hashtextextended($1, 0))", key
                )
