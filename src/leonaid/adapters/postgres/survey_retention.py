"""Bounded retention sweep, separate from participation inactivity classification."""

from __future__ import annotations

from typing import Any

import asyncpg

from leonaid.adapters.postgres.survey_deletion import request_deletion


async def sweep_retention(pool: asyncpg.Pool[Any], limit: int = 100) -> int:
    if not 1 <= limit <= 100:
        raise ValueError("Retention batch size must be between 1 and 100")
    changed = 0
    async with pool.acquire() as conn, conn.transaction():
        # Serialize against policy changes. Never wait on a survey's advisory
        # lock while holding this row: a busy survey is retried next sweep.
        policy = await conn.fetchrow(
            "SELECT * FROM survey_settings WHERE singleton FOR UPDATE"
        )
        candidates = await conn.fetch(
            """SELECT id FROM survey s WHERE NOT EXISTS (
              SELECT 1 FROM survey_deletion d WHERE d.survey_id=s.id
            ) AND (
              (status IN ('ended','archived') AND retention_started_at
                + make_interval(secs => $1::integer) <= clock_timestamp())
              OR (status='deleted' AND deleted_at
                + make_interval(secs => $2::integer) <= clock_timestamp())
            ) ORDER BY id LIMIT $3""",
            policy["ended_retention_seconds"],
            policy["trash_retention_seconds"],
            limit,
        )
        for candidate in candidates:
            sid = candidate["id"]
            if not await conn.fetchval(
                "SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))", str(sid)
            ):
                continue
            survey = await conn.fetchrow(
                "SELECT * FROM survey WHERE id=$1 FOR UPDATE SKIP LOCKED", sid
            )
            if survey is None or await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM survey_deletion WHERE survey_id=$1)", sid
            ):
                continue
            # Candidate reads can become stale while acquiring row locks. Both
            # eligibility and the lifecycle timestamp are checked again here.
            if survey["status"] in {"ended", "archived"}:
                result = await conn.execute(
                    """UPDATE survey SET status='deleted',deleted_at=clock_timestamp(),
                    updated_at=clock_timestamp(),revision=revision+1 WHERE id=$1
                    AND retention_started_at + make_interval(secs => $2::integer) <= clock_timestamp()""",
                    sid,
                    policy["ended_retention_seconds"],
                )
                changed += result == "UPDATE 1"
            elif survey["status"] == "deleted" and await conn.fetchval(
                "SELECT $1::timestamptz + make_interval(secs => $2::integer) <= clock_timestamp()",
                survey["deleted_at"],
                policy["trash_retention_seconds"],
            ):
                await request_deletion(
                    conn,
                    survey,
                    policy["retention_configured_by"],
                    f"retention:{policy['revision']}:{sid}",
                )
                changed += 1
    return changed
