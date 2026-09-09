"""PostgreSQL implementation of the application readiness port."""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg

from leonaid.application.platform import ProbeValue


class PostgresReadinessProbe:
    name = "postgres"

    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def check(self) -> dict[str, ProbeValue]:
        # Readiness shares the application connection budget. A busy pool must
        # fail readiness within the same deadline, not create extra connections.
        async with asyncio.timeout(3):
            async with self._pool.acquire(timeout=3) as connection:
                value = await connection.fetchval("SELECT 1", timeout=3)
        return {"probe": int(value)}
