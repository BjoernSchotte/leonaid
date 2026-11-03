"""Retry pacing for SERIALIZABLE command transactions.

An immediate retry usually runs into the same still-open competing
transaction and fails again. A short, jittered exponential pause lets the
competitor commit, so the retry sees its result (for example a replay).
"""

from __future__ import annotations

import asyncio
import random

SERIALIZABLE_ATTEMPTS = 5


async def serialization_pause(attempt: int) -> None:
    """Wait before retry `attempt + 1`; about 25, 50, 100 and 200 ms plus jitter."""
    base = 0.025 * 2**attempt
    await asyncio.sleep(base + random.uniform(0, base))
