"""Waiting after a Twenty 429: Retry-After alone hides the per-minute bucket."""

from __future__ import annotations

import pytest

from leonaid.adapters.twenty.gateway import rate_limit_wait_seconds

NOW = 1_793_770_600.0


def test_short_bucket_uses_retry_after() -> None:
    headers = {"Retry-After": "1", "X-RateLimit-Remaining": "40"}
    assert rate_limit_wait_seconds(headers, now=NOW, cap=60) == 1.0


def test_spent_minute_bucket_waits_until_reset() -> None:
    # Real Twenty 2.54 answer when the 100/min bucket is spent.
    headers = {
        "Retry-After": "1",
        "X-RateLimit-Limit": "100",
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": str(int(NOW) + 24),
    }
    assert rate_limit_wait_seconds(headers, now=NOW, cap=60) == pytest.approx(24)


def test_wait_is_capped() -> None:
    headers = {
        "Retry-After": "1",
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": str(int(NOW) + 600),
    }
    assert rate_limit_wait_seconds(headers, now=NOW, cap=60) == 60


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Retry-After": "soon"},
        {"Retry-After": "1", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "x"},
        {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(NOW) - 5)},
    ],
)
def test_missing_or_odd_headers_fall_back_to_one_second(
    headers: dict[str, str],
) -> None:
    assert rate_limit_wait_seconds(headers, now=NOW, cap=60) == 1.0
