"""PostgreSQL durable queue using row locks and fenced claims."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.outbox import OutboxClaimLost
from leonaid.domain.outbox import (
    ClaimedOutboxEvent,
    OutboxState,
    json_payload,
)

# Every table that points at an outbox row, with or without a foreign key.
# A referenced row is evidence (sent mail, invoice delivery, survey export,
# survey erasure) and is never removed by retention. The outbox acceptance
# probe compares the foreign keys in this list against pg_constraint, so a
# new reference fails the proof until retention accounts for it.
OUTBOX_REFERENCES: tuple[tuple[str, str, bool], ...] = (
    # References that keep a completed job: (table, column, enforced by a
    # foreign key).
    ("invoice_delivery", "outbox_event_id", True),
    ("survey_export_job", "event_id", True),
    ("survey_deletion", "event_id", False),
)

# Foreign keys that retention detaches: the referencing row stays as evidence
# and its link becomes NULL when the job is deleted (ON DELETE SET NULL).
OUTBOX_DETACHED_REFERENCES: tuple[tuple[str, str], ...] = (
    ("mail_delivery", "outbox_event_id"),
    # The case keeps its contact state; the completed link job may go.
    ("inbox_case", "contact_job_id"),
)

_UNREFERENCED = "\n".join(
    f"  AND NOT EXISTS (SELECT 1 FROM {table} AS ref WHERE ref.{column} = event.id)"
    for table, column, _ in OUTBOX_REFERENCES
)

PURGE_COMPLETED_SQL = f"""
WITH doomed AS (
  SELECT event.id
  FROM outbox_event AS event
  WHERE event.status = 'completed'
    AND event.completed_at < $1
{_UNREFERENCED}
  ORDER BY event.completed_at, event.id
  LIMIT $2
  FOR UPDATE OF event SKIP LOCKED
)
DELETE FROM outbox_event AS event
USING doomed
WHERE event.id = doomed.id
  AND event.status = 'completed'
"""


async def complete_resolved_event(
    connection: asyncpg.Connection[Any], event_id: UUID
) -> None:
    """Complete a resting job whose outcome was verified by its owning module."""
    status = await connection.execute(
        """
        UPDATE outbox_event
        SET status='completed', completed_at=now(), dead_lettered_at=NULL,
            claim_token=NULL, claimed_by=NULL, last_error_code=NULL,
            last_error_detail=NULL
        WHERE id=$1 AND status IN ('pending','dead_letter')
        """,
        event_id,
    )
    if status != "UPDATE 1":
        raise ValueError("Only a resting job can be completed by its module.")


class AsyncpgOutboxQueue:
    def __init__(
        self,
        pool: asyncpg.Pool[Any],
        *,
        claim_lease: timedelta = timedelta(minutes=5),
        excluded_event_types: frozenset[str] = frozenset(),
    ) -> None:
        if claim_lease <= timedelta(0):
            raise ValueError("claim_lease must be positive.")
        self._pool = pool
        self._claim_lease = claim_lease
        # Event types of switched-off modules; their jobs are never claimed.
        self._excluded_event_types = sorted(excluded_event_types)

    async def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime,
    ) -> ClaimedOutboxEvent | None:
        claim_token = uuid4()
        stale_before = now - self._claim_lease
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    WITH candidate AS (
                        SELECT id
                        FROM outbox_event
                        WHERE
                            (
                                (status = 'pending' AND available_at <= $1)
                                OR (
                                    status = 'processing'
                                    AND claimed_at <= $2
                                )
                            )
                            AND NOT (event_type = ANY($5::text[]))
                        ORDER BY available_at, created_at, id
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE outbox_event AS event
                    SET status = 'processing',
                        attempts = event.attempts + 1,
                        claimed_at = $1,
                        claimed_by = $3,
                        last_worker_id = $3,
                        claim_token = $4,
                        last_attempt_at = $1,
                        completed_at = NULL
                    FROM candidate
                    WHERE event.id = candidate.id
                    RETURNING
                        event.id,
                        event.aggregate_type,
                        event.aggregate_id,
                        event.event_type,
                        event.idempotency_key,
                        event.payload,
                        event.attempts,
                        event.claim_token,
                        event.claimed_by
                    """,
                    now,
                    stale_before,
                    worker_id,
                    claim_token,
                    self._excluded_event_types,
                )
        if row is None:
            return None
        return ClaimedOutboxEvent(
            id=row["id"],
            aggregate_type=str(row["aggregate_type"]),
            aggregate_id=row["aggregate_id"],
            event_type=str(row["event_type"]),
            idempotency_key=str(row["idempotency_key"]),
            payload=json_payload(row["payload"]),
            attempts=int(row["attempts"]),
            claim_token=row["claim_token"],
            claimed_by=str(row["claimed_by"]),
        )

    async def complete(
        self,
        *,
        event_id: UUID,
        claim_token: UUID,
        completed_at: datetime,
    ) -> None:
        async with self._pool.acquire() as connection:
            status = await connection.execute(
                """
                UPDATE outbox_event
                SET status = 'completed',
                    completed_at = $3,
                    claim_token = NULL,
                    claimed_by = NULL,
                    last_error_code = NULL,
                    last_error_detail = NULL
                WHERE id = $1
                  AND status = 'processing'
                  AND claim_token = $2
                """,
                event_id,
                claim_token,
                completed_at,
            )
        self._require_fenced_update(status, "abschließen")

    async def fail(
        self,
        *,
        event_id: UUID,
        claim_token: UUID,
        error_code: str,
        error_detail: str,
        failed_at: datetime,
        available_at: datetime,
        dead_letter: bool,
    ) -> None:
        async with self._pool.acquire() as connection:
            status = await connection.execute(
                """
                UPDATE outbox_event
                SET status = CASE
                        WHEN $6::boolean THEN 'dead_letter'
                        ELSE 'pending'
                    END,
                    available_at = $5,
                    dead_lettered_at = CASE
                        WHEN $6::boolean THEN $4::timestamptz
                        ELSE NULL::timestamptz
                    END,
                    claim_token = NULL,
                    claimed_by = NULL,
                    last_error_code = $3,
                    last_error_detail = $7
                WHERE id = $1
                  AND status = 'processing'
                  AND claim_token = $2
                """,
                event_id,
                claim_token,
                error_code,
                failed_at,
                available_at,
                dead_letter,
                error_detail,
            )
        self._require_fenced_update(status, "als fehlgeschlagen markieren")

    async def defer(
        self,
        *,
        event_id: UUID,
        claim_token: UUID,
        available_at: datetime,
    ) -> None:
        """Back to pending without counting the attempt (``OutboxDeferred``)."""

        async with self._pool.acquire() as connection:
            status = await connection.execute(
                """
                UPDATE outbox_event
                SET status = 'pending',
                    available_at = $3,
                    attempts = greatest(attempts - 1, 0),
                    claim_token = NULL,
                    claimed_by = NULL
                WHERE id = $1
                  AND status = 'processing'
                  AND claim_token = $2
                """,
                event_id,
                claim_token,
                available_at,
            )
        self._require_fenced_update(status, "zurückstellen")

    async def purge_completed(
        self,
        *,
        completed_before: datetime,
        limit: int,
    ) -> int:
        """Delete at most ``limit`` completed, unreferenced jobs; return the count.

        One short transaction per batch. Rows locked by another session are
        skipped instead of waited for, so neither a worker claim nor an
        operator update ever blocks on retention.
        """

        if limit < 1:
            raise ValueError("limit must be at least 1.")
        async with self._pool.acquire() as connection:
            status = await connection.execute(
                PURGE_COMPLETED_SQL, completed_before, limit
            )
        return int(status.rsplit(" ", 1)[-1])

    async def manual_retry(
        self,
        *,
        event_id: UUID,
        operator: str,
        now: datetime,
    ) -> OutboxState:
        if not operator.strip():
            raise ValueError("operator darf nicht leer sein.")
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE outbox_event
                SET status = 'pending',
                    available_at = $2,
                    dead_lettered_at = NULL,
                    claim_token = NULL,
                    claimed_by = NULL,
                    completed_at = NULL,
                    manual_retry_count = manual_retry_count + 1,
                    last_manual_retry_at = $2,
                    last_manual_retry_by = $3
                WHERE id = $1 AND status = 'dead_letter'
                RETURNING *
                """,
                event_id,
                now,
                operator,
            )
        if row is None:
            raise ValueError("Nur ein Dead-Letter-Job kann manuell gestartet werden.")
        return self._state(row)

    async def state(self, event_id: UUID) -> OutboxState | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM outbox_event WHERE id = $1",
                event_id,
            )
        return None if row is None else self._state(row)

    @staticmethod
    def _state(row: asyncpg.Record) -> OutboxState:
        return OutboxState(
            id=row["id"],
            status=str(row["status"]),
            attempts=int(row["attempts"]),
            available_at=row["available_at"],
            claimed_at=row["claimed_at"],
            claimed_by=row["claimed_by"],
            last_worker_id=row["last_worker_id"],
            completed_at=row["completed_at"],
            dead_lettered_at=row["dead_lettered_at"],
            last_error_code=row["last_error_code"],
            last_error_detail=row["last_error_detail"],
            manual_retry_count=int(row["manual_retry_count"]),
            last_manual_retry_at=row["last_manual_retry_at"],
            last_manual_retry_by=row["last_manual_retry_by"],
        )

    @staticmethod
    def _require_fenced_update(status: str, action: str) -> None:
        if status != "UPDATE 1":
            raise OutboxClaimLost(
                f"Outbox-Claim konnte nicht sicher {action} werden; "
                "der Claim ist abgelaufen oder wurde übernommen."
            )
