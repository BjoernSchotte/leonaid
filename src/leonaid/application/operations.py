"""Ports and response values for operational administration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ApiMetricSnapshot:
    requests: int
    errors: int
    average_latency_ms: float


@dataclass(frozen=True, slots=True)
class DependencySignal:
    dependency: str
    status: str
    latency_ms: float
    request_id: str
    error_code: str | None


@dataclass(frozen=True, slots=True)
class FailedJob:
    id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    attempts: int
    last_error_code: str
    failed_at: datetime
    manual_retry_count: int


@dataclass(frozen=True, slots=True)
class OperationsSnapshot:
    generated_at: datetime
    request_id: str
    api: ApiMetricSnapshot
    dependencies: tuple[DependencySignal, ...]
    outbox: dict[str, int]
    mail: dict[str, int]
    login: dict[str, int]
    failed_jobs: tuple[FailedJob, ...]


class OperationsService(Protocol):
    async def snapshot(self, *, request_id: str) -> OperationsSnapshot: ...

    async def retry(
        self,
        *,
        event_id: UUID,
        operator_user_id: UUID,
        request_id: str,
    ) -> FailedJob: ...
