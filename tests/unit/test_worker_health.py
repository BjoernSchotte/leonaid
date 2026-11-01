from __future__ import annotations

import pytest

from leonaid.entrypoints.worker.health import LoopHealth, error_location


class ManualClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def loop(clock: ManualClock) -> LoopHealth:
    return LoopHealth("outbox", stall_after_seconds=30, clock=clock)


def test_loop_is_not_healthy_before_its_first_completed_iteration() -> None:
    health = loop(ManualClock())

    assert health.healthy() is False
    assert health.last_success_age() is None


def test_loop_is_healthy_after_success_and_stalls_without_progress() -> None:
    clock = ManualClock()
    health = loop(clock)

    health.succeeded()
    clock.now += 29.9
    assert health.healthy() is True

    clock.now += 0.2
    assert health.healthy() is False


def test_repeated_failures_mark_loop_unhealthy_even_after_recent_success() -> None:
    clock = ManualClock()
    health = loop(clock)
    health.succeeded()

    health.failed(RuntimeError("first"))
    health.failed(RuntimeError("second"))
    assert health.healthy() is True

    health.failed(KeyError("third"))
    assert health.healthy() is False
    assert health.last_error_type == "KeyError"
    assert health.total_failures == 3


def test_success_ends_failure_streak_and_reports_recovery() -> None:
    health = loop(ManualClock())

    assert health.succeeded() is False
    health.failed(RuntimeError("down"))
    assert health.succeeded() is True
    assert health.consecutive_failures == 0
    assert health.total_failures == 1
    assert health.healthy() is True


def test_backoff_grows_exponentially_and_is_capped() -> None:
    health = LoopHealth(
        "survey_sweep",
        stall_after_seconds=60,
        maximum_backoff_seconds=15,
        clock=ManualClock(),
    )

    delays = [health.failed(RuntimeError("down")) for _ in range(6)]

    assert delays == [2.0, 4.0, 8.0, 15.0, 15.0, 15.0]


@pytest.mark.parametrize(
    ("stall_after_seconds", "failure_threshold"),
    [(0, 3), (-1, 3), (10, 0)],
)
def test_invalid_thresholds_are_rejected(
    stall_after_seconds: float, failure_threshold: int
) -> None:
    with pytest.raises(ValueError):
        LoopHealth(
            "outbox",
            stall_after_seconds=stall_after_seconds,
            failure_threshold=failure_threshold,
        )


def test_error_location_names_innermost_frame_without_message() -> None:
    def explode() -> None:
        raise RuntimeError("secret row value")

    try:
        explode()
    except RuntimeError as error:
        location = error_location(error)

    assert location is not None
    assert location.startswith("test_worker_health.py:")
    assert "secret" not in location


def test_error_location_prefers_innermost_leonaid_frame() -> None:
    try:
        LoopHealth("outbox", stall_after_seconds=0)
    except ValueError as error:
        location = error_location(error)

    assert location is not None
    assert location.startswith("health.py:")


def test_error_location_is_none_for_unraised_error() -> None:
    assert error_location(RuntimeError("never raised")) is None
