from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from leonaid.domain.action_progress import RecordActionProgressCommand
from leonaid.domain.outbox import RetryPolicy

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
ACTOR_ID = UUID("10000000-0000-4000-8000-000000000002")
COMMAND_ID = UUID("f1000000-0000-4000-8000-000000000001")


def test_action_progress_event_has_stable_ids_and_idempotency_key() -> None:
    command = RecordActionProgressCommand(
        command_id=COMMAND_ID,
        action_id=ACTION_ID,
        actor_user_id=ACTOR_ID,
        actual_value=Decimal("720.2500"),
        request_id="poc022:golden:v1",
    )

    first = command.outbox_event()
    second = command.outbox_event()

    assert first == second
    assert first.idempotency_key == f"action-progress:{ACTION_ID}:{COMMAND_ID}"
    assert first.payload["actualValue"] == "720.2500"
    assert command.request_hash == (
        "eabcbe7c6b22610f66f27ff5036a64a8c22a76f3ea39863267a212f062ba82d0"
    )


def test_action_progress_rejects_invalid_exact_value() -> None:
    with pytest.raises(ValueError, match="vier Nachkommastellen"):
        RecordActionProgressCommand(
            command_id=COMMAND_ID,
            action_id=ACTION_ID,
            actor_user_id=ACTOR_ID,
            actual_value=Decimal("1.00001"),
            request_id="poc022:invalid",
        )


def test_retry_policy_is_exponential_capped_and_dead_letters() -> None:
    now = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)
    policy = RetryPolicy(
        max_attempts=4,
        base_delay=timedelta(seconds=5),
        maximum_delay=timedelta(seconds=12),
    )

    assert policy.after_failure(1, now).available_at == now + timedelta(seconds=5)
    assert policy.after_failure(2, now).available_at == now + timedelta(seconds=10)
    assert policy.after_failure(3, now).available_at == now + timedelta(seconds=12)
    assert policy.after_failure(4, now).dead_letter is True
