"""Retry pacing for SERIALIZABLE command transactions."""

from __future__ import annotations

import asyncio

import pytest

from leonaid.adapters.postgres import retry


@pytest.mark.parametrize("attempt", range(retry.SERIALIZABLE_ATTEMPTS - 1))
def test_pause_grows_exponentially_with_bounded_jitter(
    attempt: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []

    async def record(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(retry.asyncio, "sleep", record)
    asyncio.run(retry.serialization_pause(attempt))
    base = 0.025 * 2**attempt
    assert len(slept) == 1 and base <= slept[0] <= 2 * base
