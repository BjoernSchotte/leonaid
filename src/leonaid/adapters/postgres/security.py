"""Durable transport-boundary rate limiting backed by PostgreSQL."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import asyncpg


class AsyncpgSecurityRateLimitRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def consume(
        self,
        *,
        scope: str,
        fingerprint_hash: str,
        attempted_at: datetime,
        window: timedelta,
        limit: int,
    ) -> bool:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    f"security.rate:{scope}:{fingerprint_hash}",
                )
                count = await connection.fetchval(
                    """
                    SELECT count(*)
                    FROM security_rate_attempt
                    WHERE scope = $1
                      AND fingerprint_hash = $2
                      AND attempted_at >= $3
                    """,
                    scope,
                    fingerprint_hash,
                    attempted_at - window,
                )
                if int(count) >= limit:
                    return False
                await connection.execute(
                    """
                    INSERT INTO security_rate_attempt (
                        id, scope, fingerprint_hash, attempted_at
                    )
                    VALUES ($1, $2, $3, $4)
                    """,
                    uuid4(),
                    scope,
                    fingerprint_hash,
                    attempted_at,
                )
                await connection.execute(
                    """
                    DELETE FROM security_rate_attempt
                    WHERE attempted_at < $1
                    """,
                    attempted_at - timedelta(days=2),
                )
                return True
