"""Club-day instants for the live survey proofs (Europe/Berlin, not UTC).

An account without raw access may only select whole past days
(disclosure.whole_days): a start on the server's current club day or later is
refused with range_whole_days. "Some hours ago" is not such a start: between
00:00 and 03:00 Berlin, three hours ago is yesterday, a whole past day, and
the API rightly answers 200 (CI job 128557004516, 00:08 Berlin).

The proofs read the database clock, the clock the API compares with, and pass
a start a margin after it. The start then lies on the API's current day or a
later one, even when midnight passes before the request reaches the API.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# Longer than one API request of the proofs takes.
REFUSAL_MARGIN = timedelta(minutes=1)


def refused_start(database_now: datetime) -> datetime:
    """A start the API refuses until ``database_now + REFUSAL_MARGIN``."""

    return database_now + REFUSAL_MARGIN


async def database_now(connection: Any) -> datetime:
    """The database clock the API's whole-day rule reads (clock_timestamp)."""

    value = await connection.fetchval("SELECT clock_timestamp()")
    assert isinstance(value, datetime) and value.tzinfo is not None
    return value
