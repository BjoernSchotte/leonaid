"""Infrastructure-neutral durable-worker orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from leonaid.domain.outbox import ClaimedOutboxEvent, RetryPolicy


class OutboxQueue(Protocol):
    async def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime,
    ) -> ClaimedOutboxEvent | None: ...

    async def complete(
        self,
        *,
        event_id: UUID,
        claim_token: UUID,
        completed_at: datetime,
    ) -> None: ...

    async def fail(
        self,
        *,
        event_id: UUID,
        claim_token: UUID,
        error_code: str,
        error_detail: str,
        failed_at: datetime,
        available_at: datetime,
        dead_letter: bool,
    ) -> None: ...


class OutboxEventHandler(Protocol):
    async def handle(self, event: ClaimedOutboxEvent) -> None: ...


class OutboxWorker:
    def __init__(
        self,
        *,
        worker_id: str,
        queue: OutboxQueue,
        handlers: Mapping[str, OutboxEventHandler],
        retry_policy: RetryPolicy,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id darf nicht leer sein.")
        if not handlers:
            raise ValueError("Mindestens ein Outbox-Handler ist erforderlich.")
        self._worker_id = worker_id
        self._queue = queue
        self._handlers = dict(handlers)
        self._retry_policy = retry_policy
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def run_once(self) -> bool:
        event = await self._queue.claim_next(
            worker_id=self._worker_id,
            now=self._clock(),
        )
        if event is None:
            return False
        try:
            handler = self._handlers[event.event_type]
        except KeyError:
            await self._record_failure(
                event,
                code="handler_not_registered",
                detail=f"Kein Handler für {event.event_type}",
            )
            return True
        try:
            await handler.handle(event)
        except Exception as error:
            await self._record_failure(
                event,
                code=type(error).__name__.lower(),
                detail=str(error),
            )
            return True
        await self._queue.complete(
            event_id=event.id,
            claim_token=event.claim_token,
            completed_at=self._clock(),
        )
        return True

    async def run_until_idle(self, *, maximum_events: int = 10_000) -> int:
        handled = 0
        while handled < maximum_events and await self.run_once():
            handled += 1
        return handled

    async def _record_failure(
        self,
        event: ClaimedOutboxEvent,
        *,
        code: str,
        detail: str,
    ) -> None:
        failed_at = self._clock()
        decision = self._retry_policy.after_failure(event.attempts, failed_at)
        await self._queue.fail(
            event_id=event.id,
            claim_token=event.claim_token,
            error_code=code[:120],
            error_detail=detail[:2000],
            failed_at=failed_at,
            available_at=decision.available_at,
            dead_letter=decision.dead_letter,
        )
