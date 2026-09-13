#!/usr/bin/env python3
"""Exercise the production timing query against PostgreSQL temporary rows only."""

import asyncio
import os
from datetime import timedelta

import asyncpg

from leonaid.adapters.operations import pending_queue_timing


async def main() -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        async with connection.transaction():
            await connection.execute(
                "CREATE TEMP TABLE outbox_event (status text, available_at timestamptz)"
            )
            now = await connection.fetchval("SELECT now()")
            assert await pending_queue_timing(connection) == (None, None)
            future = now + timedelta(hours=1)
            await connection.execute(
                "INSERT INTO outbox_event VALUES ('pending', $1)", future
            )
            assert await pending_queue_timing(connection) == (future, None)
            for status in ("completed", "processing", "dead_letter"):
                await connection.execute(
                    "INSERT INTO outbox_event VALUES ($1, $2)",
                    status,
                    now - timedelta(days=7),
                )
            assert await pending_queue_timing(connection) == (future, None)
            due = now - timedelta(seconds=120)
            await connection.execute(
                "INSERT INTO outbox_event VALUES ('pending', $1), ('pending', $2)",
                due,
                now,
            )
            assert await pending_queue_timing(connection) == (due, 120.0)
            await connection.execute(
                "UPDATE outbox_event SET status = 'completed' WHERE available_at = $1",
                due,
            )
            assert await pending_queue_timing(connection) == (now, 0.0)
        print("PASS: empty, future, ignored states, oldest due and due boundary")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
