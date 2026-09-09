"""Live processing-deadline and retry proof using an actual PostgreSQL lock."""

from __future__ import annotations

import asyncio
import os
import time
from uuid import uuid4

import asyncpg
import httpx

from tools.emdash_spike.valid_order_ingress_proof import snapshot
from tools.public_orders.contract import assert_commitment, error_code, order_body


async def main() -> None:
    assert os.environ["LEONAID_ENV"] == "test"
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=5)
    try:
        async with (
            httpx.AsyncClient(
                base_url="http://api:8000",
                timeout=12,
                headers={
                    "X-LeonAid-Order-Key": os.environ["LEONAID_ORDER_SUBMISSION_KEY"],
                    "User-Agent": "LeonAidOrderDeadlineProof",
                },
            ) as core,
            httpx.AsyncClient(
                base_url="http://twenty-server:3000",
                timeout=15,
                headers={
                    "Authorization": f"Bearer {os.environ['TWENTY_INTEGRATION_API_KEY']}"
                },
            ) as twenty,
        ):
            context = await core.get("/api/v1/public/actions/alias/krapfentaxi")
            assert context.status_code == 200
            body = order_body(
                token=context.json()["action"]["orderForm"]["accessToken"],
                command=uuid4(),
                given_name="Synthetic",
                family_name="DeadlineProbe",
                email="deadline-probe@leonaid.invalid",
                company_name=None,
                quantity=1,
            )
            path = "/api/v1/public/actions/krapfentaxi/orders"
            # Match the real party-scoped command lock. Observe PostgreSQL's
            # blocker relation below so a wrong key cannot produce a false pass.
            lock_key = (
                "public.order.party:20000000-0000-4000-8000-000000000001:"
                "person:synthetic deadlineprobe"
            )
            blocker = await connection.fetchval("SELECT pg_backend_pid()")
            blocked_query = (
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE $1 = ANY(pg_blocking_pids(pid))"
            )
            before = await snapshot(connection, twenty)
            await connection.execute(
                "SELECT pg_advisory_lock(hashtextextended($1, 0))", lock_key
            )
            pending = None
            try:
                started = time.monotonic()
                pending = asyncio.create_task(core.post(path, json=body))
                async with asyncio.timeout(3):
                    while not await connection.fetchval(blocked_query, blocker):
                        assert not pending.done(), "Order never waited on the real lock"
                        await asyncio.sleep(0.05)
                rejected = await pending
                elapsed = time.monotonic() - started
                assert rejected.status_code == 503
                assert error_code(rejected) == "public_order_processing_timeout"
                assert rejected.headers["cache-control"] == "no-store"
                assert "set-cookie" not in rejected.headers
                assert 7.5 <= elapsed < 11, "Core did not finish before Astro's timeout"
                assert await connection.fetchval(blocked_query, blocker) == 0
                assert await snapshot(connection, twenty) == before, (
                    "Timed-out locked order changed Core or CRM state"
                )
            finally:
                if pending is not None and not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                await connection.execute(
                    "SELECT pg_advisory_unlock(hashtextextended($1, 0))", lock_key
                )
            accepted = await core.post(path, json=body)
            assert accepted.status_code == 201
            await assert_commitment(
                connection,
                accepted.json(),
                expected_company_id=None,
                expected_person=True,
                expected_quantity=1,
            )
            after = await snapshot(connection, twenty)
            replayed = await core.post(path, json=body)
            assert replayed.status_code == 200
            assert replayed.json()["replayed"] is True
            assert (
                replayed.json()["publicReference"] == accepted.json()["publicReference"]
            )
            assert replayed.json()["quantities"] == accepted.json()["quantities"]
            assert await snapshot(connection, twenty) == after, (
                "Exact retry duplicated or mutated Core/CRM state"
            )
            print(
                "order-deadline: observed real PostgreSQL lock wait; Core returned "
                "no-store 503 within 11s and released its wait with seven Core "
                "tables and real Twenty unchanged; same command accepted after "
                "unlock and replayed without any further state change"
            )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
