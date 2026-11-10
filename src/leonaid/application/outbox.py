"""Infrastructure-neutral durable-worker orchestration."""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Protocol
from uuid import UUID

from leonaid.domain.outbox import ClaimedOutboxEvent, RetryDecision, RetryPolicy

# (event name, job, safe error code, duration in milliseconds or None)
OutboxObserver = Callable[[str, ClaimedOutboxEvent, str | None, float | None], None]
SAFE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,119}\Z")


class OutboxClaimLost(RuntimeError):
    """The claim expired or another worker took it over; its result is void."""


class OutboxDeferred(Exception):
    """The job cannot run yet and waits; this is not a failure.

    A handler raises it when it depends on another job that is still on its
    way (a mail whose PDF is being rendered). The job goes back to pending
    for ``delay`` and the attempt does not count, so waiting never
    dead-letters. The handler must bound the wait itself: when the thing it
    waits for has failed, it raises a real error.
    """

    def __init__(self, code: str, delay: timedelta) -> None:
        super().__init__(code)
        self.code = code
        self.delay = delay


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

    async def defer(
        self,
        *,
        event_id: UUID,
        claim_token: UUID,
        available_at: datetime,
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
        observer: OutboxObserver | None = None,
        handler_timeouts: Mapping[str, float] | None = None,
        on_close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty.")
        if not handlers:
            raise ValueError("At least one outbox handler is required.")
        timeouts = dict(handler_timeouts or {})
        for event_type, seconds in timeouts.items():
            if event_type not in handlers or not math.isfinite(seconds) or seconds <= 0:
                raise ValueError(
                    "A handler timeout needs a registered handler and finite "
                    f"positive seconds: {event_type}"
                )
        self._handler_timeouts = timeouts
        self._on_close = on_close
        self._worker_id = worker_id
        self._queue = queue
        self._handlers = dict(handlers)
        self._retry_policy = retry_policy
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._observer = observer

    async def close(self) -> None:
        """Release resources that handlers share, such as HTTP clients."""
        if self._on_close is not None:
            await self._on_close()

    async def run_once(self) -> bool:
        event = await self._queue.claim_next(
            worker_id=self._worker_id,
            now=self._clock(),
        )
        if event is None:
            return False
        started = perf_counter()
        self._observe("outbox.job.claimed", event)
        try:
            await self._process(event, started)
        except OutboxClaimLost:
            # The lease expired while the handler ran; the current claim owner
            # records the outcome. This worker keeps running.
            self._observe(
                "outbox.job.claim_lost",
                event,
                "outbox_claim_lost",
                self._elapsed_ms(started),
            )
        return True

    async def _process(self, event: ClaimedOutboxEvent, started: float) -> None:
        try:
            handler = self._handlers[event.event_type]
        except KeyError:
            await self._record_failure(
                event, code="handler_not_registered", started=started
            )
            return
        deadline = asyncio.timeout(self._handler_timeouts.get(event.event_type))
        try:
            async with deadline:
                await handler.handle(event)
        except OutboxClaimLost:
            raise
        except OutboxDeferred as waiting:
            await self._queue.defer(
                event_id=event.id,
                claim_token=event.claim_token,
                available_at=self._clock() + waiting.delay,
            )
            self._observe(
                "outbox.job.deferred",
                event,
                waiting.code
                if SAFE_ERROR_CODE.fullmatch(waiting.code)
                else "job_deferred",
                self._elapsed_ms(started),
            )
            return
        except Exception as error:
            # A timeout leaves the outcome open; handlers with a timeout must
            # be safe to repeat, so the job is retried like any failure.
            await self._record_failure(
                event,
                code="job_timeout" if deadline.expired() else self.error_code(error),
                started=started,
                retryable=deadline.expired()
                or getattr(error, "retryable", True) is not False,
            )
            return
        await self._queue.complete(
            event_id=event.id,
            claim_token=event.claim_token,
            completed_at=self._clock(),
        )
        self._observe("outbox.job.completed", event, None, self._elapsed_ms(started))

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
        started: float,
        retryable: bool = True,
    ) -> None:
        failed_at = self._clock()
        decision = (
            self._retry_policy.after_failure(event.attempts, failed_at)
            if retryable
            else RetryDecision(dead_letter=True, available_at=failed_at)
        )
        await self._queue.fail(
            event_id=event.id,
            claim_token=event.claim_token,
            error_code=code[:120],
            # Exception text can contain credentials, recipients or payload
            # data, so only the safe code is stored.
            error_detail=code[:120],
            failed_at=failed_at,
            available_at=decision.available_at,
            dead_letter=decision.dead_letter,
        )
        self._observe(
            "outbox.job.dead_lettered"
            if decision.dead_letter
            else "outbox.job.retry_scheduled",
            event,
            code,
            self._elapsed_ms(started),
        )

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((perf_counter() - started) * 1000, 2)

    @staticmethod
    def error_code(error: Exception) -> str:
        explicit = getattr(error, "code", None)
        if isinstance(explicit, str) and SAFE_ERROR_CODE.fullmatch(explicit):
            return explicit
        fallback = type(error).__name__.lower()
        return fallback if SAFE_ERROR_CODE.fullmatch(fallback) else "job_failed"

    def _observe(
        self,
        name: str,
        event: ClaimedOutboxEvent,
        error_code: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        if self._observer is not None:
            self._observer(name, event, error_code, duration_ms)
