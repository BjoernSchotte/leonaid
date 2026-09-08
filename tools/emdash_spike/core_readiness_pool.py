"""Small real-PostgreSQL readiness budget and production HTTP regression proof."""

from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx

from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.readiness import PostgresReadinessProbe


async def http_probe(database_down: bool) -> None:
    async with httpx.AsyncClient(base_url="http://api:8000", timeout=6) as client:
        assert (await client.get("/health/live")).status_code == 200
        started = time.monotonic()
        replies = await asyncio.gather(*(client.get("/health/ready") for _ in range(3)))
        assert time.monotonic() - started < 5
        for response in replies:
            # Twenty/RustFS are deliberately absent from this two-service proof.
            assert response.status_code == 503
            postgres = response.json()["checks"]["postgres"]
            assert postgres == (
                {
                    "status": "not-ready",
                    "details": {"errorCode": "dependency_unavailable"},
                }
                if database_down
                else {"status": "ready", "details": {"probe": 1}}
            )
        assert (await client.get("/health/live")).status_code == 200
    print(
        f"core-readiness-pool: three actual HTTP checks passed; databaseDown={database_down}"
    )


async def main() -> None:
    assert sys.argv[1:] in ([], ["--database-down"])
    if sys.argv[1:]:
        await http_probe(True)
        return
    # Two test connections and three ordinary checks, not a capacity benchmark.
    pool = await create_pool(os.environ["CORE_DATABASE_URL"], maximum_size=2)
    probe = PostgresReadinessProbe(pool)
    try:
        assert (
            await asyncio.gather(*(probe.check() for _ in range(3)))
            == [{"probe": 1}] * 3
        )
        assert pool.get_size() <= 2
        async with pool.acquire() as first, pool.acquire():
            count_query = (
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname=current_database() AND backend_type='client backend'"
            )
            before = await first.fetchval(count_query)
            started = time.monotonic()
            try:
                await probe.check()
            except TimeoutError:
                pass
            else:
                raise AssertionError("Readiness bypassed the occupied application pool")
            assert 2.8 <= time.monotonic() - started < 5
            assert pool.get_idle_size() == 0
            assert await first.fetchval(count_query) == before
            pending = asyncio.create_task(probe.check())
            await asyncio.sleep(0.05)
            assert not pending.done()
            pending.cancel()
            result = await asyncio.gather(pending, return_exceptions=True)
            assert isinstance(result[0], asyncio.CancelledError)
            assert await first.fetchval(count_query) == before
        # Both timed-out and cancelled waiters must leave the same pool usable.
        assert (
            await asyncio.gather(*(probe.check() for _ in range(3)))
            == [{"probe": 1}] * 3
        )
        assert pool.get_size() == pool.get_idle_size() == 2
        print(
            "core-readiness-pool: real shared pool, three normal checks, bounded "
            "wait without extra PostgreSQL clients, caller cancellation and recovery passed"
        )
    finally:
        await pool.close()
    await http_probe(False)


if __name__ == "__main__":
    asyncio.run(main())
