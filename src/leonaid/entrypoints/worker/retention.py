"""Bounded retention sweep for finished technical rows.

Deletes successfully completed, unreferenced outbox jobs older than the
configured retention, expired rate-limit attempts and drivers' delivery-board
read audits older than 90 days. Every batch is its own
short transaction with ``FOR UPDATE SKIP LOCKED``, so the sweep never holds
long locks and never waits for a worker claim.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import asyncpg

from leonaid.adapters.postgres.delivery_board import purge_read_audits
from leonaid.adapters.postgres.outbox import AsyncpgOutboxQueue
from leonaid.adapters.postgres.security import (
    RATE_ATTEMPT_RETENTION,
    AsyncpgSecurityRateLimitRepository,
)
from leonaid.configuration import RetentionSettings


@dataclass(frozen=True)
class RetentionResult:
    outbox_events_deleted: int
    rate_attempts_deleted: int
    # False when the batch cap stopped the sweep before the backlog was gone.
    complete: bool
    read_audits_deleted: int = 0


async def _drain(
    purge: Callable[[int], Awaitable[int]],
    *,
    batch_size: int,
    max_batches: int,
) -> tuple[int, bool]:
    deleted = 0
    for _ in range(max_batches):
        count = await purge(batch_size)
        deleted += count
        if count < batch_size:
            return deleted, True
    return deleted, False


async def sweep_operational_retention(
    *,
    queue: AsyncpgOutboxQueue,
    rate_limits: AsyncpgSecurityRateLimitRepository,
    settings: RetentionSettings,
    now: datetime,
    read_audits: Callable[[datetime, int], Awaitable[int]] | None = None,
) -> RetentionResult:
    completed_before = now - timedelta(days=settings.outbox_days)
    attempted_before = now - RATE_ATTEMPT_RETENTION

    async def purge_outbox(limit: int) -> int:
        return await queue.purge_completed(
            completed_before=completed_before, limit=limit
        )

    async def purge_attempts(limit: int) -> int:
        return await rate_limits.purge_expired(
            attempted_before=attempted_before, limit=limit
        )

    outbox_deleted, outbox_complete = await _drain(
        purge_outbox,
        batch_size=settings.batch_size,
        max_batches=settings.max_batches,
    )
    attempts_deleted, attempts_complete = await _drain(
        purge_attempts,
        batch_size=settings.batch_size,
        max_batches=settings.max_batches,
    )
    audits_deleted, audits_complete = 0, True
    if read_audits is not None:
        purge = read_audits

        async def purge_read_audits(limit: int) -> int:
            return await purge(now, limit)

        audits_deleted, audits_complete = await _drain(
            purge_read_audits,
            batch_size=settings.batch_size,
            max_batches=settings.max_batches,
        )
    return RetentionResult(
        outbox_events_deleted=outbox_deleted,
        rate_attempts_deleted=attempts_deleted,
        complete=outbox_complete and attempts_complete and audits_complete,
        read_audits_deleted=audits_deleted,
    )


def delivery_read_audits(
    pool: asyncpg.Pool[Any],
) -> Callable[[datetime, int], Awaitable[int]]:
    """The read-audit purge of the delivery board, bound to a pool."""

    async def purge(now: datetime, limit: int) -> int:
        return await purge_read_audits(pool, now=now, limit=limit)

    return purge
