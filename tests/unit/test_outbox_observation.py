"""Worker diagnostics retain operational metadata without payload content."""

import json
from uuid import UUID
import pytest
import asyncpg
from leonaid.adapters.postgres.outbox import AsyncpgOutboxQueue
from leonaid.adapters.postgres.activity_projection import ActionProgressActivityHandler
from leonaid.domain.outbox import RetryPolicy
from leonaid.domain.outbox import ClaimedOutboxEvent
from leonaid.application.outbox import OutboxWorker
from leonaid.bootstrap.worker import observe_job

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
COMMAND_ID = UUID("f1000000-0000-4000-8000-000000000001")


def test_worker_error_code_never_uses_exception_message() -> None:
    error = ValueError("recipient@example.test token=private")
    assert OutboxWorker.error_code(error) == "valueerror"
    error.code = "recipient@example.test"  # type: ignore[attr-defined]
    assert OutboxWorker.error_code(error) == "valueerror"
    error.code = "invalid_job_payload"  # type: ignore[attr-defined]
    assert OutboxWorker.error_code(error) == "invalid_job_payload"


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
    assert json.loads(output)["durationMs"] == 12.5
    assert "recipient@example.test" not in output
    assert "private" not in output


@pytest.mark.asyncio
async def test_invalid_handler_timeout_rejected_before_worker_start() -> None:
    pool = asyncpg.create_pool(min_size=0, max_size=1)
    handler = ActionProgressActivityHandler(pool)
    for budgets in (
        {"unknown": 1.0},
        {"progress": 0.0},
        {"progress": float("nan")},
        {"progress": float("inf")},
    ):
        with pytest.raises(ValueError, match="Handler timeout"):
            OutboxWorker(
                worker_id="validation",
                queue=AsyncpgOutboxQueue(pool),
                handlers={"progress": handler},
                retry_policy=RetryPolicy(),
                handler_timeouts=budgets,
            )
