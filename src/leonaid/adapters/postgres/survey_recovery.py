"""Erasure checkpoint export and offline reapplication after a consistent restore."""

from __future__ import annotations

from typing import Any

import asyncpg

from leonaid.adapters.postgres.survey_deletion import AsyncpgSurveyDeletion
from leonaid.application.object_storage import ObjectStorage
from leonaid.application.surveys.recovery import ErasureCheckpoint, ErasureRecord

RECORD_COLUMNS = (
    "survey_id,requested_by,operation_hash,expected_revision,event_id,requested_at"
)


async def export_checkpoint(pool: asyncpg.Pool[Any]) -> ErasureCheckpoint:
    async with pool.acquire() as conn, conn.transaction():
        return await export_checkpoint_in_transaction(conn)


async def export_checkpoint_in_transaction(conn: Any) -> ErasureCheckpoint:
    """Caller owns a transaction; keep the erasure lock through publication if needed."""
    await conn.execute("SELECT pg_advisory_xact_lock(1937076838,1)")
    identity = await conn.fetchval(
        "SELECT installation_id FROM survey_recovery_identity WHERE singleton"
    )
    records = await conn.fetch(
        f"SELECT {RECORD_COLUMNS} FROM survey_deletion ORDER BY survey_id"
    )
    cutoff = await conn.fetchval("SELECT clock_timestamp()")
    return ErasureCheckpoint(
        installation_id=identity,
        exported_at=cutoff,
        records=tuple(ErasureRecord.model_validate(dict(row)) for row in records),
    )


async def reapply_checkpoint(
    pool: asyncpg.Pool[Any], storage: ObjectStorage, checkpoint: ErasureCheckpoint
) -> int:
    """Caller has authenticated the checkpoint and keeps all app writers offline.

    Commit every revocation before deleting objects. Failure leaves a retryable
    ledger and must prevent the caller from starting application services.
    """
    async with pool.acquire() as conn, conn.transaction():
        identity = await conn.fetchval(
            "SELECT installation_id FROM survey_recovery_identity WHERE singleton"
        )
        if identity != checkpoint.installation_id:
            raise ValueError("Recovery installation mismatch")
        current = await conn.fetch(f"SELECT {RECORD_COLUMNS} FROM survey_deletion")
        known_ids = {row["survey_id"] for row in current}
        records = {record.survey_id: record for record in checkpoint.records}
        for row in current:
            existing = ErasureRecord.model_validate(dict(row))
            if records.get(existing.survey_id) != existing:
                raise ValueError("Checkpoint omits or changes a known erasure")
        for record in sorted(checkpoint.records, key=lambda value: value.survey_id):
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                str(record.survey_id),
            )
            survey = await conn.fetchrow(
                "SELECT * FROM survey WHERE id=$1 FOR UPDATE", record.survey_id
            )
            known = record.survey_id in known_ids
            if survey is not None and known and survey["status"] != "deleted":
                raise ValueError("Restored erasure state is inconsistent")
            if survey is not None and not known:
                await conn.execute(
                    """UPDATE survey SET status='deleted', deleted_at=clock_timestamp(),
                    updated_at=clock_timestamp(),revision=revision+1 WHERE id=$1""",
                    record.survey_id,
                )
            await conn.execute(
                """INSERT INTO survey_deletion(survey_id,requested_by,operation_hash,
                expected_revision,event_id,requested_at) VALUES($1,$2,$3,$4,$5,$6)
                ON CONFLICT(survey_id) DO UPDATE SET completed_at=NULL""",
                record.survey_id,
                record.requested_by,
                record.operation_hash,
                record.expected_revision,
                record.event_id,
                record.requested_at,
            )
            # Retain the original event identity. The normal worker can safely
            # acknowledge a pending restored event after the offline gate.
            await conn.execute(
                """INSERT INTO outbox_event(id,aggregate_type,aggregate_id,event_type,idempotency_key,payload)
                VALUES($1,'survey',$2,'survey.delete.v1',$3,'{}'::jsonb) ON CONFLICT(id) DO NOTHING""",
                record.event_id,
                record.survey_id,
                f"survey-delete:{record.survey_id}",
            )
            event = await conn.fetchrow(
                "SELECT aggregate_id,event_type FROM outbox_event WHERE id=$1",
                record.event_id,
            )
            if (
                event["aggregate_id"] != record.survey_id
                or event["event_type"] != "survey.delete.v1"
            ):
                raise ValueError("Recovery event identity mismatch")
    eraser = AsyncpgSurveyDeletion(pool, storage)
    for record in checkpoint.records:
        await eraser.erase(record.survey_id, record.event_id)
    return len(checkpoint.records)
