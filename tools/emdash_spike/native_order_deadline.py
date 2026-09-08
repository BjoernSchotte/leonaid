"""Coordinate real PostgreSQL blocking with native browser retry acceptance."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx

from leonaid.application.sponsor_matching import normalize_match_name
from tools.emdash_spike.valid_order_ingress_proof import snapshot
from tools.public_orders.contract import assert_commitment

ROOT = Path("/proof")
ACTION = "20000000-0000-4000-8000-000000000001"


async def wait_file(name: str) -> str:
    async with asyncio.timeout(180):
        while not (ROOT / name).is_file():
            await asyncio.sleep(0.05)
    return (ROOT / name).read_text()


def signal(name: str) -> None:
    with (ROOT / name).open("x") as output:
        output.write("ready")


async def main() -> None:
    assert os.environ["LEONAID_ENV"] == "test"
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=5)
    try:
        async with httpx.AsyncClient(
            base_url="http://twenty-server:3000",
            timeout=15,
            headers={
                "Authorization": f"Bearer {os.environ['TWENTY_INTEGRATION_API_KEY']}"
            },
        ) as twenty:
            for engine in ("chromium", "firefox", "webkit"):
                label = f"deadline-{engine}-native-person"
                party_key = normalize_match_name(f"Synthetic {label}")
                assert party_key == f"synthetic deadline {engine} native person"
                lock_key = f"public.order.party:{ACTION}:person:{party_key}"
                before = await snapshot(connection, twenty)
                blocker = await connection.fetchval("SELECT pg_backend_pid()")
                blocked = (
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE $1 = ANY(pg_blocking_pids(pid))"
                )
                await connection.execute(
                    "SELECT pg_advisory_lock(hashtextextended($1, 0))", lock_key
                )
                try:
                    signal(f"{label}-locked")
                    # Observe the real blocker relation, not merely a timer or
                    # an error page that might have failed for another reason.
                    async with asyncio.timeout(180):
                        while not await connection.fetchval(blocked, blocker):
                            assert not (ROOT / f"{label}-timeout").exists(), (
                                "Browser timed out without waiting on the lock"
                            )
                            await asyncio.sleep(0.02)
                    await wait_file(f"{label}-timeout")
                    assert await connection.fetchval(blocked, blocker) == 0
                    assert await snapshot(connection, twenty) == before, (
                        "Cancelled native order changed Core or Twenty"
                    )
                finally:
                    await connection.execute(
                        "SELECT pg_advisory_unlock(hashtextextended($1, 0))", lock_key
                    )
                signal(f"{label}-released")
                receipt = json.loads(await wait_file(f"{label}-accepted"))
                UUID(receipt["commandId"])
                rows = await connection.fetch(
                    "SELECT id FROM commitment WHERE public_reference=$1",
                    receipt["reference"],
                )
                assert len(rows) == 1
                row = await assert_commitment(
                    connection,
                    {
                        "commitmentId": str(rows[0]["id"]),
                        "publicReference": receipt["reference"],
                    },
                    expected_company_id=None,
                    expected_person=True,
                    expected_quantity=3,
                )
                command = await connection.fetchrow(
                    "SELECT result, completed_at FROM command_receipt WHERE idempotency_key=$1",
                    f"public.order:{ACTION}:{receipt['commandId']}",
                )
                assert command is not None and command["completed_at"] is not None
                result = json.loads(command["result"])
                assert result["commitmentId"] == str(row["id"])
                after = await snapshot(connection, twenty)
                people = json.loads(after[1][1])
                matches = [
                    person
                    for person in people
                    if person["name"] == {"firstName": "Synthetic", "lastName": label}
                ]
                assert len(matches) == 1
                assert matches[0]["id"] == str(row["twenty_person_id"])
                assert matches[0].get("companyId") in {None, ""}
                assert after[1][0] == before[1][0], "Person order changed companies"
                assert len(people) == len(json.loads(before[1][1])) + 1
                signal(f"{label}-replay-ready")
                await wait_file(f"{label}-replayed")
                assert await snapshot(connection, twenty) == after, (
                    "Native exact POST replay mutated Core or Twenty"
                )
                signal(f"{label}-verified")
                print(
                    f"native-order-deadline: {engine} actual blocker, cancelled wait, "
                    "unchanged timeout state, accepted same command, Core/Twenty person "
                    "and exact replay verified",
                    flush=True,
                )
    finally:
        await connection.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(f"native-order-deadline: failed; type={type(error).__name__}", flush=True)
        raise SystemExit(1) from None
