"""Failure diagnostics and deadline-based polling for real-system tests."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


class TestkitFailure(AssertionError):
    """A real system violated a PoC acceptance contract."""


@dataclass(frozen=True, slots=True)
class TestContext:
    """Stable diagnostic context propagated through every testkit client."""

    request_id: str
    persona: str
    charity_action: str
    golden_dataset: str

    def failure(self, step: str, detail: str) -> TestkitFailure:
        return TestkitFailure(
            f"{detail} "
            f"[request-id={self.request_id} persona={self.persona} "
            f"charity-action={self.charity_action} "
            f"golden-dataset={self.golden_dataset} step={step}]"
        )


async def poll_until(
    *,
    context: TestContext,
    step: str,
    probe: Callable[[], Awaitable[T]],
    ready: Callable[[T], bool],
    timeout_seconds: float = 30.0,
    interval_seconds: float = 0.2,
) -> T:
    """Poll a semantic target state until a monotonic deadline is reached."""

    if timeout_seconds <= 0 or interval_seconds <= 0:
        raise context.failure(step, "Polling benötigt positive Zeitgrenzen.")
    deadline = time.monotonic() + timeout_seconds
    last_value: T | None = None
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            last_value = await probe()
            last_error = None
            if ready(last_value):
                return last_value
        except Exception as error:  # noqa: BLE001 - diagnose transient dependency
            last_error = error
        remaining = deadline - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(min(interval_seconds, remaining))
    diagnostic = (
        f"letzter Fehler: {last_error}"
        if last_error is not None
        else f"letzter Zustand: {last_value!r}"
    )
    raise context.failure(
        step,
        f"Fachlicher Zielzustand wurde vor der Deadline nicht erreicht; {diagnostic}.",
    )
