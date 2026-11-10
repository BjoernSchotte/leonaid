"""Allocation of the order number of a new order."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from leonaid.domain.commitments import order_number

ORDER_NUMBER_CONSTRAINT = "uq_commitment_public_reference"
ORDER_NUMBER_ATTEMPTS = 8


def order_number_taken(error: BaseException) -> bool:
    """The unique constraint refused a number that another order took.

    Only two writers that derive the same number at the same moment get
    here; the caller runs its transaction again, which asks for a new one.
    """

    return (
        isinstance(error, asyncpg.UniqueViolationError)
        and error.constraint_name == ORDER_NUMBER_CONSTRAINT
    )


async def free_order_number(
    connection: asyncpg.Connection[Any], commitment_id: UUID
) -> str:
    """The first number derived from the order id that no order has yet.

    A transaction lock on the candidate makes two writers with the same
    candidate take turns; the unique constraint stays the last word.
    """

    number, _ = await free_order_number_from(connection, commitment_id, 0)
    return number


async def free_order_number_from(
    connection: asyncpg.Connection[Any], commitment_id: UUID, first_attempt: int
) -> tuple[str, int]:
    """Like ``free_order_number``, starting at ``first_attempt``; also says
    which attempt the number comes from.

    A writer whose transaction cannot see the order that took its number
    (repeatable read) would be handed the same number again. It passes the
    attempt after the refused one instead.
    """

    for attempt in range(first_attempt, first_attempt + ORDER_NUMBER_ATTEMPTS):
        candidate = order_number(commitment_id, attempt)
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"order-number:{candidate}",
        )
        if not await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM commitment WHERE public_reference = $1)",
            candidate,
        ):
            return candidate, attempt
    raise RuntimeError("No free order number was found.")
