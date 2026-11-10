"""The worker's loop and operator command for the delivery-day mail sweep."""

from __future__ import annotations

from datetime import datetime

import pytest

from leonaid.application.delivery_day_mails import (
    SWEEP_BATCH,
    SWEEP_BUSY_RETRY_SECONDS,
    SWEEP_INTERVAL_SECONDS,
)
from leonaid.entrypoints.worker import outbox, platform
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


class StopLoop(BaseException):
    """Ends the endless loop from inside the patched sleep."""


class FakePool:
    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_a_sweep_that_was_kept_out_is_no_pass_and_asks_again_soon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Another worker holds the sweep twice, then this one runs and queues 2.
    results: list[int | None] = [None, None, 2]
    delays: list[float] = []
    successes: list[int] = []

    class Sweep:
        async def run_once(self, *, now: datetime) -> int | None:
            assert now.tzinfo is not None
            return results.pop(0)

    async def pool(*_: object, **__: object) -> FakePool:
        return FakePool()

    async def sleep(delay: float) -> None:
        delays.append(delay)
        if not results:
            raise StopLoop

    monkeypatch.setenv("LEONAID_PUBLIC_BASE_URL", "https://app.leonaid.org")
    monkeypatch.setenv("CORE_DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(platform, "create_pool", pool)
    monkeypatch.setattr(platform, "build_delivery_day_mail_sweep", lambda *_: Sweep())
    monkeypatch.setattr(platform.asyncio, "sleep", sleep)
    monkeypatch.setattr(
        platform, "record_success", lambda health: successes.append(len(delays))
    )
    before = platform.DELIVERY_DAY_MAILS_QUEUED["total"]

    try:
        with pytest.raises(StopLoop):
            await platform.delivery_day_mail_loop()
        queued = platform.DELIVERY_DAY_MAILS_QUEUED["total"] - before
    finally:
        platform.DELIVERY_DAY_MAILS_QUEUED["total"] = before

    # No success before the run that happened; a short wait after each
    # skipped one, the interval after the real one.
    assert successes == [2]
    assert delays == [
        SWEEP_BUSY_RETRY_SECONDS,
        SWEEP_BUSY_RETRY_SECONDS,
        SWEEP_INTERVAL_SECONDS,
    ]
    assert SWEEP_BUSY_RETRY_SECONDS < SWEEP_INTERVAL_SECONDS / 2
    assert queued == 2


@pytest.mark.parametrize(
    ("result", "printed", "code"),
    [
        (3, '{"queued":3,"busy":false}', 0),
        (0, '{"queued":0,"busy":false}', 0),
        # Kept out by another worker's sweep: the command says so.
        (None, '{"queued":0,"busy":true}', 75),
    ],
)
@pytest.mark.asyncio
async def test_the_operator_command_tells_a_run_from_a_skipped_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    result: int | None,
    printed: str,
    code: int,
) -> None:
    async def sweep() -> int | None:
        return result

    monkeypatch.setattr(outbox, "delivery_day_mail_sweep", sweep)

    assert await outbox.execute(parser().parse_args(["delivery-day-mail-sweep"])) == (
        code
    )
    assert capsys.readouterr().out.strip() == printed
