"""The worker's loop and operator command for the delivery-day mail sweep."""

from __future__ import annotations

import pytest

from leonaid.application.delivery_day_mails import SWEEP_BATCH, SWEEP_INTERVAL_SECONDS
from leonaid.entrypoints.worker import platform
from leonaid.entrypoints.worker.outbox import configuration_problems, parser


def test_the_sweep_is_a_worker_loop_with_health_and_a_counter() -> None:
    before = platform.DELIVERY_DAY_MAILS_QUEUED["total"]
    platform.DELIVERY_DAY_MAILS_QUEUED["total"] += 4
    try:
        document = platform.metrics_document()
    finally:
        platform.DELIVERY_DAY_MAILS_QUEUED["total"] = before

    assert platform.delivery_day_mail_health in platform.LOOPS
    assert platform.delivery_day_mail_health.name == "delivery_day_mail"
    assert 'leonaid_worker_loop_healthy{loop="delivery_day_mail"}' in document
    assert f"leonaid_worker_delivery_day_mails_queued_total {before + 4}" in document


def test_the_sweep_runs_every_five_minutes_and_stalls_after_a_missed_run() -> None:
    assert SWEEP_INTERVAL_SECONDS == 300
    assert SWEEP_BATCH == 200
    assert platform.delivery_day_mail_health.stall_after_seconds > (
        SWEEP_INTERVAL_SECONDS
    )
    assert platform.delivery_day_mail_health.stall_after_seconds < (
        2 * SWEEP_INTERVAL_SECONDS
    )


def test_an_operator_can_run_one_sweep_by_hand() -> None:
    arguments = parser().parse_args(["delivery-day-mail-sweep"])

    assert arguments.command == "delivery-day-mail-sweep"


def test_a_worker_without_its_base_url_stops_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEONAID_PUBLIC_BASE_URL", "https://app.leonaid.org")
    monkeypatch.setenv("LEONAID_SITE_BASE_URL", "")
    assert not any("link configuration" in item for item in configuration_problems())

    monkeypatch.setenv("LEONAID_SITE_BASE_URL", "no-url")
    assert any(
        "link configuration" in item and "LEONAID_SITE_BASE_URL" in item
        for item in configuration_problems()
    )
    monkeypatch.delenv("LEONAID_SITE_BASE_URL")
    monkeypatch.delenv("LEONAID_PUBLIC_BASE_URL")
    assert any(
        "LEONAID_PUBLIC_BASE_URL:missing" in item for item in configuration_problems()
    )
