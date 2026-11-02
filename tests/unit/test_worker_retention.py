from __future__ import annotations

from datetime import timedelta

import pytest

from leonaid.adapters.postgres.security import RATE_ATTEMPT_RETENTION
from leonaid.configuration import ConfigurationError, load_retention_settings
from leonaid.entrypoints.fastapi.security import RATE_LIMITS
from leonaid.entrypoints.worker import platform
from leonaid.entrypoints.worker.outbox import configuration_problems
from leonaid.entrypoints.worker.retention import RetentionResult

RETENTION_VARIABLES = (
    "OUTBOX_RETENTION_DAYS",
    "OUTBOX_RETENTION_INTERVAL_SECONDS",
    "OUTBOX_RETENTION_BATCH_SIZE",
    "OUTBOX_RETENTION_MAX_BATCHES",
)


@pytest.fixture(autouse=True)
def clean_retention_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in RETENTION_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_retention_defaults_are_thirty_days_hourly_in_bounded_batches() -> None:
    settings = load_retention_settings()

    assert settings.outbox_days == 30
    assert settings.interval_seconds == 3600
    assert settings.batch_size == 500
    assert settings.max_batches == 20


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OUTBOX_RETENTION_DAYS", "0"),
        ("OUTBOX_RETENTION_DAYS", "thirty"),
        ("OUTBOX_RETENTION_INTERVAL_SECONDS", "0"),
        ("OUTBOX_RETENTION_BATCH_SIZE", "100000"),
        ("OUTBOX_RETENTION_MAX_BATCHES", "0"),
    ],
)
def test_invalid_retention_settings_stop_the_worker_at_startup(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError, match=name):
        load_retention_settings()
    assert any(name in problem for problem in configuration_problems())


def test_rate_attempt_retention_outlives_every_rate_limit_window() -> None:
    windows = [policy.window for policy in RATE_LIMITS.values()]
    # Path-pattern policies are built per request; the longest is one hour.
    windows.append(timedelta(hours=1))

    assert all(window < RATE_ATTEMPT_RETENTION for window in windows)


def test_retention_loop_reports_health_and_deleted_counts() -> None:
    before = dict(platform.RETENTION_DELETED)

    platform.record_retention(
        RetentionResult(outbox_events_deleted=3, rate_attempts_deleted=2, complete=True)
    )
    document = platform.metrics_document()

    assert platform.retention_health in platform.LOOPS
    assert 'leonaid_worker_loop_healthy{loop="retention"}' in document
    assert (
        'leonaid_worker_retention_deleted_total{table="outbox_event"} '
        f"{before['outbox_event'] + 3}"
    ) in document
    assert (
        'leonaid_worker_retention_deleted_total{table="security_rate_attempt"} '
        f"{before['security_rate_attempt'] + 2}"
    ) in document


def test_retention_loop_stalls_only_after_missing_a_sweep() -> None:
    assert platform.retention_health.stall_after_seconds > 3600
