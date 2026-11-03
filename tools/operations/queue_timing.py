#!/usr/bin/env python3
"""Exercise the production queue-timing query on PostgreSQL temporary rows only."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import asyncpg

from leonaid.adapters.operations import pending_queue_timing


async def main() -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        # The temporary table shadows the real one inside this session only and
        # is dropped with the rolled-back transaction.
        transaction = connection.transaction()
        await transaction.start()
        try:
            await connection.execute(
                "CREATE TEMP TABLE outbox_event "
                "(status text, available_at timestamptz, event_type text)"
            )
            now = await connection.fetchval("SELECT now()")
            assert await pending_queue_timing(connection) == (None, None)
            future = now + timedelta(hours=1)
            await connection.execute(
                "INSERT INTO outbox_event VALUES ('pending', $1, 'mail.send.v1')",
                future,
            )
            assert await pending_queue_timing(connection) == (future, None)
            for status in ("completed", "processing", "dead_letter"):
                await connection.execute(
                    "INSERT INTO outbox_event VALUES ($1, $2, 'mail.send.v1')",
                    status,
                    now - timedelta(days=7),
                )
            assert await pending_queue_timing(connection) == (future, None)
            parked = now - timedelta(days=3)
            await connection.execute(
                "INSERT INTO outbox_event VALUES ('pending', $1, 'survey.delete.v1')",
                parked,
            )
            assert await pending_queue_timing(
                connection, frozenset({"survey.delete.v1"})
            ) == (future, None)
            assert await pending_queue_timing(connection) == (
                parked,
                3 * 24 * 3600.0,
            )
            due = now - timedelta(seconds=120)
            await connection.execute(
                "INSERT INTO outbox_event VALUES "
                "('pending', $1, 'mail.send.v1'), ('pending', $2, 'mail.send.v1')",
                due,
                now,
            )
            excluded = frozenset({"survey.delete.v1"})
            assert await pending_queue_timing(connection, excluded) == (due, 120.0)
            await connection.execute(
                "UPDATE outbox_event SET status = 'completed' WHERE available_at = $1",
                due,
            )
            assert await pending_queue_timing(connection, excluded) == (now, 0.0)
        finally:
            await transaction.rollback()
        print(
            "PASS: queue timing for empty, future, ignored states, parked "
            "module jobs, oldest due job and the due boundary"
        )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
