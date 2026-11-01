"""Health bookkeeping for the worker's long-running background loops.

A loop is healthy only while it keeps completing iterations. Readiness must
not stay green while a loop is stuck in a retry cycle or hangs, because the
outbox then silently stops sending mail and rendering documents.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from pathlib import Path


class LoopHealth:
    """Tracks successes and failures of one background loop."""

    def __init__(
        self,
        name: str,
        *,
        stall_after_seconds: float,
        failure_threshold: int = 3,
        maximum_backoff_seconds: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if stall_after_seconds <= 0:
            raise ValueError("stall_after_seconds must be positive.")
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1.")
        self.name = name
        self.stall_after_seconds = stall_after_seconds
        self.failure_threshold = failure_threshold
        self.maximum_backoff_seconds = maximum_backoff_seconds
        self._clock = clock
        self.last_success: float | None = None
        self.consecutive_failures = 0
        self.total_failures = 0
        self.last_error_type: str | None = None

    def succeeded(self) -> bool:
        """Record a completed iteration; return True if this ends a failure streak."""

        recovered = self.consecutive_failures > 0
        self.last_success = self._clock()
        self.consecutive_failures = 0
        return recovered

    def failed(self, error: BaseException) -> float:
        """Record a failed iteration and return the delay before the next attempt."""

        self.consecutive_failures += 1
        self.total_failures += 1
        self.last_error_type = type(error).__name__
        return self.backoff_seconds()

    def backoff_seconds(self) -> float:
        if self.consecutive_failures == 0:
            return 0.0
        exponent = min(self.consecutive_failures - 1, 16)
        return float(min(2.0 * 2**exponent, self.maximum_backoff_seconds))

    def last_success_age(self) -> float | None:
        if self.last_success is None:
            return None
        return max(0.0, self._clock() - self.last_success)

    def healthy(self) -> bool:
        age = self.last_success_age()
        return (
            age is not None
            and age < self.stall_after_seconds
            and self.consecutive_failures < self.failure_threshold
        )


PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def error_location(error: BaseException) -> str | None:
    """Return the innermost LeonAid frame as ``file.py:line``, without message.

    Exception messages can carry row values or credentials, so loop failures
    are logged by type and code location only. Library frames (socket,
    asyncpg) say little, so the innermost frame in LeonAid code wins.
    """

    frames = traceback.extract_tb(error.__traceback__)
    if not frames:
        return None
    own = [
        frame
        for frame in frames
        if Path(frame.filename).resolve().is_relative_to(PACKAGE_ROOT)
    ]
    frame = (own or frames)[-1]
    return f"{Path(frame.filename).name}:{frame.lineno}"
