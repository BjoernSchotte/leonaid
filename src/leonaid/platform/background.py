"""Contract for long-running worker loops that modules contribute.

The worker process owns health bookkeeping. A loop reports each completed
iteration and each failure; the reporter returns the delay before the loop
retries, so backoff and readiness stay in one place.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


class LoopReporter(Protocol):
    def succeeded(self) -> None: ...

    def failed(self, error: Exception) -> float: ...


@dataclass(frozen=True, slots=True)
class BackgroundLoop:
    """One named loop; the name is the readiness check and metrics label."""

    name: str
    stall_after_seconds: float
    run: Callable[[LoopReporter], Awaitable[None]]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Background loop name must not be empty.")
        if self.stall_after_seconds <= 0:
            raise ValueError("stall_after_seconds must be positive.")
