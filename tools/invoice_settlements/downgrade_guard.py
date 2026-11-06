#!/usr/bin/env python3
"""Seeds payment states for the 0050 downgrade guard proof (tools/schema).

`seed <case>` replaces the payments of the legacy invoice LEGACY-0001
(7 200 cents) with one case. `tools/schema/test.sh` then expects
`alembic downgrade 0049_window_fully_booked` to fail for every case except
`exact`, and `verify-exact` to find the exact payment intact after the
round trip down and up again.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

import asyncpg

INVOICE_ID = UUID("99000000-0000-4000-8000-000000000001")
USER_ID = UUID("10000000-0000-4000-8000-000000000001")
FIRST = UUID("97500000-0000-4000-8000-000000000001")
SECOND = UUID("97500000-0000-4000-8000-000000000002")
REVERSAL = UUID("97600000-0000-4000-8000-000000000001")
GROSS = 7_200

# Each refused case: (amount, note) entries and whether the first is reversed.
CASES: dict[str, tuple[tuple[tuple[int, str | None], ...], bool]] = {
    "several": (((3_600, None), (3_600, None)), False),
    "reversal": (((GROSS, None),), True),
    "note": (((GROSS, "Rest folgt"),), False),
    "partial": (((3_600, None),), False),
    "overpaid": (((9_000, None),), False),
    "exact": (((GROSS, None),), False),
}


class GuardFailure(RuntimeError):
    pass


async def seed(connection: asyncpg.Connection[Any], case: str) -> None:
    entries, reversed_ = CASES[case]
    async with connection.transaction():
        await connection.execute(
            "DELETE FROM payment_reversal WHERE invoice_id = $1", INVOICE_ID
        )
        await connection.execute(
            "DELETE FROM payment_record WHERE invoice_id = $1", INVOICE_ID
        )
        for payment_id, (amount, note) in zip((FIRST, SECOND), entries, strict=False):
            await connection.execute(
                """
                INSERT INTO payment_record (
                    id, invoice_id, amount_minor, currency, received_on,
                    recorded_by_user_id, reference, note, created_at
                )
                VALUES ($1, $2, $3, 'EUR', $4, $5, 'LEGACY-0001', $6, $7)
                """,
                payment_id,
                INVOICE_ID,
                amount,
                date(2026, 11, 20),
                USER_ID,
                note,
                datetime(2026, 11, 20, 10, tzinfo=timezone.utc),
            )
        if reversed_:
            await connection.execute(
                """
                INSERT INTO payment_reversal (
                    id, payment_id, invoice_id, reason_snapshot,
                    reversed_by_user_id, reversed_at, created_at
                )
                VALUES ($1, $2, $3, 'Lastschrift zurückgegeben', $4, $5, $5)
                """,
                REVERSAL,
                FIRST,
                INVOICE_ID,
                USER_ID,
                datetime(2026, 11, 21, 10, tzinfo=timezone.utc),
            )
    print(f"downgrade-guard: seeded case {case}")


async def verify_exact(connection: asyncpg.Connection[Any]) -> None:
    rows = await connection.fetch(
        "SELECT id, amount_minor FROM payment_record WHERE invoice_id = $1",
        INVOICE_ID,
    )
    if [(row["id"], row["amount_minor"]) for row in rows] != [(FIRST, GROSS)]:
        raise GuardFailure(f"Exact payment did not survive the round trip: {rows}")
    print("downgrade-guard: exact full payment kept through downgrade and upgrade")


async def run(arguments: argparse.Namespace) -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=10)
    try:
        if arguments.command == "seed":
            await seed(connection, arguments.case)
        else:
            await verify_exact(connection)
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    seed_parser = commands.add_parser("seed")
    seed_parser.add_argument("case", choices=sorted(CASES))
    commands.add_parser("verify-exact")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
