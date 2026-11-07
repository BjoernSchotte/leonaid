"""PostgreSQL reads for the buyer's order mails (``application.order_mails``)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.application.links import LinkBuilder
from leonaid.application.order_mails import (
    ORDER_MAIL_KEY_PREFIXES,
    OrderCancellationFacts,
    OrderMailFacts,
    OrderMailKind,
    mailbox_key,
)
from leonaid.domain.outbox import PendingOutboxEvent


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


class AsyncpgOrderMailReader:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def facts(
        self, commitment_id: UUID, kind: OrderMailKind
    ) -> OrderMailFacts | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT commitment.created_at, action.name AS action_name
                FROM commitment
                JOIN charity_action AS action ON action.id = commitment.action_id
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
                    SELECT cancellation.requested_at, invoice.number
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
                )
        return OrderMailFacts(
            action_name=str(row["action_name"]),
            commitment=commitment,
            ordered_at=row["created_at"],
            cancellation=cancellation,
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

    async def recent_order_mails(
        self, *, recipient_sha256: str, mailbox: str, since: datetime
    ) -> int:
        # Order mails of the window with the address of their order; the
        # ledger keeps only a digest of the exact address, so the mailbox
        # comparison (``+tag``, Gmail dots) needs the order's address.
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT mail.recipient_sha256,
                    commitment.customer_snapshot->>'email' AS email
                FROM mail_delivery AS mail
                LEFT JOIN commitment
                  ON commitment.id::text = split_part(mail.idempotency_key, ':', 2)
                WHERE mail.sent_at >= $1
                  AND mail.status = 'sent'
                  AND (mail.idempotency_key LIKE $2 OR mail.idempotency_key LIKE $3)
                """,
                since,
                *(f"{prefix}%" for prefix in ORDER_MAIL_KEY_PREFIXES),
            )
        return sum(
            1
            for row in rows
            if row["recipient_sha256"] == recipient_sha256
            or (row["email"] is not None and mailbox_key(str(row["email"])) == mailbox)
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


class PublicCampaignLinks:
    """The action's page on the public host (single-host installations).

    Mirrors the public host rule of specs/multi-domain §7.7.3 for a running
    action: the campaign page when the primary alias forwards to it, else the
    alias page, else the archive page.

    Stage 2c replaces this with ``SiteDirectory.edition_link`` (decision D8):
    the permanent edition URL on the campaign host, with this path as its
    fallback.
    """

    def __init__(self, pool: asyncpg.Pool[Any], links: LinkBuilder) -> None:
        self._pool = pool
        self._links = links

    async def campaign_link(self, action_id: UUID) -> str | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT action.archive_slug, alias.alias,
                    COALESCE(alias.campaign_redirect, false) AS campaign_page
                FROM charity_action AS action
                LEFT JOIN public_action_alias AS alias
                  ON alias.action_id = action.id
                 AND alias.is_primary AND alias.enabled
                WHERE action.id = $1
                """,
                action_id,
            )
        if row is None:
            return None
        if row["campaign_page"]:
            return self._links.site_url(f"/campaigns/{row['archive_slug']}/")
        if row["alias"] is not None:
            return self._links.site_url(f"/{row['alias']}")
        return self._links.site_url(f"/archive/{row['archive_slug']}")
