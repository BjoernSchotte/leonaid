"""Retry pacing and the global lock order of order, delivery and invoice commands.

An immediate retry usually runs into the same still-open competing
transaction and fails again. A short, jittered exponential pause lets the
competitor commit, so the retry sees its result (for example a replay).

Lock order. Every command that touches delivery windows, orders or invoices
takes its locks in this order and skips the levels it does not need:

1. its idempotency-key advisory lock;
2. the ``charity_action`` row (FOR SHARE);
3. the action's ``action_delivery_configuration`` row;
4. invoice advisory locks: ``invoice-payment:{id}``, then
   ``invoice-cancellation:{id}``;
5. ``action_delivery_window`` rows (the order's booked window and a window
   it is about to book);
6. the ``commitment`` row;
7. its ``commitment_delivery`` row;
8. its ``invoice`` row;
9. the ``document_series`` row a new document number comes from (ADR-0015);
10. task lists and tasks (the "Nachliefern" follow-up).

Commands following it cannot deadlock with each other. A command that still
loses a deadlock or a serialization check (SERIALIZABLE transactions, other
callers) retries on ``RETRYABLE_ERRORS`` instead of answering 500.
"""

from __future__ import annotations

import asyncio
import random

import asyncpg

SERIALIZABLE_ATTEMPTS = 5

RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    asyncpg.SerializationError,
    asyncpg.DeadlockDetectedError,
)


async def serialization_pause(attempt: int) -> None:
    """Wait before retry `attempt + 1`; about 25, 50, 100 and 200 ms plus jitter."""
    base = 0.025 * 2**attempt
    await asyncio.sleep(base + random.uniform(0, base))
