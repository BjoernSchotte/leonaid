"""PostgreSQL implementation of the application readiness port."""

from __future__ import annotations

import asyncpg

from leonaid.application.platform import ProbeValue


class PostgresReadinessProbe:
    name = "postgres"

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def check(self) -> dict[str, ProbeValue]:
        connection = await asyncpg.connect(self._database_url, timeout=3)
        try:
            value = await connection.fetchval("SELECT 1")
        finally:
            await connection.close()
        return {"probe": int(value)}
