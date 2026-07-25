"""Durable domain events and retry rules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)


@dataclass(frozen=True, slots=True)
class PendingOutboxEvent:
    id: UUID
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    idempotency_key: str
    payload: dict[str, JsonValue]

    def __post_init__(self) -> None:
        for label, value in (
            ("aggregate_type", self.aggregate_type),
            ("event_type", self.event_type),
            ("idempotency_key", self.idempotency_key),
        ):
            if not value.strip():
                raise ValueError(f"{label} darf nicht leer sein.")
        if len(self.idempotency_key) > 240:
            raise ValueError("idempotency_key darf höchstens 240 Zeichen haben.")


@dataclass(frozen=True, slots=True)
class ClaimedOutboxEvent:
    id: UUID
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    idempotency_key: str
    payload: dict[str, JsonValue]
    attempts: int
    claim_token: UUID
    claimed_by: str


@dataclass(frozen=True, slots=True)
class OutboxState:
    id: UUID
    status: str
    attempts: int
    available_at: datetime
    claimed_at: datetime | None
    claimed_by: str | None
    last_worker_id: str | None
    completed_at: datetime | None
    dead_lettered_at: datetime | None
    last_error_code: str | None
    last_error_detail: str | None
    manual_retry_count: int
    last_manual_retry_at: datetime | None
    last_manual_retry_by: str | None


@dataclass(frozen=True, slots=True)
class RetryDecision:
    dead_letter: bool
    available_at: datetime


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay: timedelta = timedelta(seconds=5)
    maximum_delay: timedelta = timedelta(minutes=15)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts muss positiv sein.")
        if self.base_delay < timedelta(0):
            raise ValueError("base_delay darf nicht negativ sein.")
        if self.maximum_delay < self.base_delay:
            raise ValueError("maximum_delay darf nicht kleiner als base_delay sein.")

    def after_failure(self, attempts: int, now: datetime) -> RetryDecision:
        if attempts < 1:
            raise ValueError("attempts muss mindestens 1 sein.")
        if now.tzinfo is None:
            raise ValueError("now muss timezone-aware sein.")
        if attempts >= self.max_attempts:
            return RetryDecision(dead_letter=True, available_at=now)
        multiplier = 2 ** (attempts - 1)
        delay = min(self.base_delay * multiplier, self.maximum_delay)
        return RetryDecision(dead_letter=False, available_at=now + delay)


def json_payload(value: Any) -> dict[str, JsonValue]:
    """Narrow an adapter payload after its JSON contract has been validated."""

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("Outbox-Payload enthält ungültiges JSON.") from error
    if not isinstance(value, dict):
        raise ValueError("Outbox-Payload muss ein JSON-Objekt sein.")
    return cast(dict[str, JsonValue], value)
