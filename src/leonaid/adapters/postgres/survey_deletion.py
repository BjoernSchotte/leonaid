"""Retryable erasure: commit intent first, erase files before relational content."""

from __future__ import annotations

from typing import Any

import asyncpg

from leonaid.application.object_storage import (
    ObjectDeletionAuthorization,
    ObjectLocation,
    ObjectStorage,
)
from leonaid.application.surveys.export_rendering import export_filename
from leonaid.domain.outbox import ClaimedOutboxEvent


def deletion_payload(row: Any) -> dict[str, Any]:
    return {
        "surveyId": str(row["survey_id"]),
        "status": "completed" if row["completed_at"] else "pending",
        "requestedAt": row["requested_at"].isoformat(),
        "completedAt": row["completed_at"].isoformat() if row["completed_at"] else None,
    }


class SurveyDeletionError(RuntimeError):
    code = "survey_deletion_failed"

    def __init__(self) -> None:
        super().__init__("survey_deletion_failed")


class AsyncpgSurveyDeletion:
    def __init__(self, pool: asyncpg.Pool[Any], storage: ObjectStorage) -> None:
        self.pool = pool
        self.storage = storage

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        try:
            await self._erase(event)
        except Exception:
            # Provider errors can contain object paths and other private data.
            raise SurveyDeletionError() from None

    async def _erase(self, event: ClaimedOutboxEvent) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            sid = event.aggregate_id
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", str(sid)
            )
            await conn.fetchrow("SELECT id FROM survey WHERE id=$1 FOR UPDATE", sid)
            deletion = await conn.fetchrow(
                "SELECT * FROM survey_deletion WHERE survey_id=$1 AND event_id=$2 FOR UPDATE",
                sid,
                event.id,
            )
            if deletion is None or deletion["completed_at"]:
                return
            authorization = ObjectDeletionAuthorization(
                actor_user_id=deletion["requested_by"],
                reason="Permanent survey erasure",
            )
            jobs = await conn.fetch(
                "SELECT * FROM survey_export_job WHERE survey_id=$1 ORDER BY id FOR UPDATE",
                sid,
            )
            for job in jobs:
                # Exact committed versions, plus the deterministic location of
                # an upload whose process crashed before recording its version.
                if job["object_version"]:
                    await self.storage.delete(
                        ObjectLocation(
                            job["bucket"], job["object_key"], job["object_version"]
                        ),
                        authorization=authorization,
                    )
                location = ObjectLocation(
                    self.storage.bucket,
                    f"surveys/{sid}/exports/{job['id']}/{export_filename(job['product'], str(job['snapshot_id']))}",
                )
                stored = await self.storage.head(location)
                if stored is not None:
                    await self.storage.delete(
                        stored.location, authorization=authorization
                    )
            # Any storage failure leaves the committed ledger and all DB object
            # references intact. Repeating exact-version deletion is safe.
            await conn.execute("DELETE FROM survey_export_job WHERE survey_id=$1", sid)
            await conn.execute("DELETE FROM survey WHERE id=$1", sid)
            await conn.execute(
                "UPDATE survey_deletion SET completed_at=clock_timestamp() WHERE survey_id=$1",
                sid,
            )
