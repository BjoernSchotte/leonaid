"""Worker diagnostics keep operational metadata and never payload content."""

from __future__ import annotations

import json
from uuid import UUID

import asyncpg
import pytest

from leonaid.adapters.postgres.activity_projection import (
    ActionProgressActivityHandler,
)
from leonaid.adapters.postgres.outbox import AsyncpgOutboxQueue
from leonaid.application.outbox import OutboxWorker
from leonaid.bootstrap.registry import (
    ModuleRegistration,
    RegistrationError,
    collect_handler_timeouts,
)
from leonaid.bootstrap.worker import effective_timeouts, observe_job
from leonaid.domain.outbox import ClaimedOutboxEvent, RetryPolicy

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
COMMAND_ID = UUID("f1000000-0000-4000-8000-000000000001")


def test_worker_error_code_never_uses_exception_message() -> None:
    error = ValueError("recipient@example.test token=private")
    assert OutboxWorker.error_code(error) == "valueerror"
    error.code = "recipient@example.test"  # type: ignore[attr-defined]
    assert OutboxWorker.error_code(error) == "valueerror"
    error.code = "invalid_job_payload"  # type: ignore[attr-defined]
    assert OutboxWorker.error_code(error) == "invalid_job_payload"


def test_unsafe_exception_class_names_fall_back_to_a_generic_code() -> None:
    unsafe = type("Ünsafe", (Exception,), {})
    assert OutboxWorker.error_code(unsafe("x")) == "job_failed"


def test_worker_observation_includes_duration_without_payload(
    capsys: pytest.CaptureFixture[str],
) -> None:
    event = ClaimedOutboxEvent(
        id=COMMAND_ID,
        aggregate_type="charity_action",
        aggregate_id=ACTION_ID,
        event_type="charity_action.progress.recorded.v1",
        idempotency_key="progress",
        payload={"actionId": str(ACTION_ID), "private": "recipient@example.test"},
        attempts=1,
        claim_token=COMMAND_ID,
        claimed_by="worker",
    )

    observe_job("outbox.job.completed", event, None, 12.5)

    output = capsys.readouterr().out
    document = json.loads(output)
    assert document["durationMs"] == 12.5
    assert document["actionId"] == str(ACTION_ID)
    assert "recipient@example.test" not in output
    assert "private" not in output


@pytest.mark.asyncio
async def test_invalid_handler_timeouts_are_rejected_before_worker_start() -> None:
    # An unopened pool performs no I/O; construction must fail before any.
    pool = asyncpg.create_pool(min_size=0, max_size=1)
    handler = ActionProgressActivityHandler(pool)
    for timeouts in (
        {"unknown": 1.0},
        {"progress": 0.0},
        {"progress": -1.0},
        {"progress": float("nan")},
        {"progress": float("inf")},
    ):
        with pytest.raises(ValueError, match="handler timeout"):
            OutboxWorker(
                worker_id="validation",
                queue=AsyncpgOutboxQueue(pool),
                handlers={"progress": handler},
                retry_policy=RetryPolicy(),
                handler_timeouts=timeouts,
            )


@pytest.mark.asyncio
async def test_modules_may_bound_only_their_own_handlers() -> None:
    pool = asyncpg.create_pool(min_size=0, max_size=1)
    handler = ActionProgressActivityHandler(pool)
    own = ModuleRegistration(
        "a", handlers={"a.job.v1": handler}, handler_timeouts={"a.job.v1": 30.0}
    )
    foreign = ModuleRegistration("b", handler_timeouts={"a.job.v1": 10.0})

    assert collect_handler_timeouts((own,)) == {"a.job.v1": 30.0}
    with pytest.raises(RegistrationError, match="foreign or unknown handler"):
        collect_handler_timeouts((own, foreign))
    with pytest.raises(RegistrationError, match="must be positive"):
        collect_handler_timeouts(
            (
                ModuleRegistration(
                    "a",
                    handlers={"a.job.v1": handler},
                    handler_timeouts={"a.job.v1": 0.0},
                ),
            )
        )


def test_timeouts_stay_inside_the_claim_lease() -> None:
    assert effective_timeouts({"survey.export.render.v1": 240.0}, 300.0) == {
        "survey.export.render.v1": 240.0
    }
    assert effective_timeouts({"survey.export.render.v1": 240.0}, 60.0) == {
        "survey.export.render.v1": 48.0
    }
