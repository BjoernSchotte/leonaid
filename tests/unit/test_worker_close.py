"""The outbox worker closes what it opened (CRM client, Web Push client).

Also when one closer fails, and when building the worker fails half way.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest

from leonaid.application.outbox import OutboxWorker
from leonaid.bootstrap import worker as bootstrap
from leonaid.bootstrap.worker import build_worker, close_all
from leonaid.domain.outbox import ClaimedOutboxEvent, RetryPolicy


class Closable:
    def __init__(self, name: str, log: list[str], *, fails: bool = False) -> None:
        self._name = name
        self._log = log
        self._fails = fails

    async def close(self) -> None:
        self._log.append(self._name)
        if self._fails:
            raise RuntimeError(f"{self._name} cannot close")


@pytest.mark.asyncio
async def test_every_closer_runs_also_after_one_failed() -> None:
    log: list[str] = []
    closers = [
        Closable("crm", log, fails=True).close,
        Closable("push", log).close,
        Closable("pool", log, fails=True).close,
    ]

    with pytest.raises(RuntimeError, match="crm cannot close"):
        await close_all(closers)

    assert log == ["crm", "push", "pool"]
    await close_all([])


class IdleQueue:
    async def claim_next(
        self, *, worker_id: str, now: datetime
    ) -> ClaimedOutboxEvent | None:
        return None

    async def complete(
        self, *, event_id: UUID, claim_token: UUID, completed_at: datetime
    ) -> None:
        raise AssertionError("nothing was claimed")

    async def fail(self, **_: Any) -> None:
        raise AssertionError("nothing was claimed")


class Idle:
    async def handle(self, event: ClaimedOutboxEvent) -> None:
        raise AssertionError("nothing was claimed")


@pytest.mark.asyncio
async def test_the_worker_closes_its_handlers_clients() -> None:
    log: list[str] = []
    worker = OutboxWorker(
        worker_id="close-proof",
        queue=IdleQueue(),
        handlers={"proof.v1": Idle()},
        retry_policy=RetryPolicy(),
        clock=lambda: datetime(2026, 11, 10, tzinfo=timezone.utc),
        on_close=lambda: close_all(
            [Closable("crm", log).close, Closable("push", log).close]
        ),
    )

    assert await worker.run_once() is False
    await worker.close()

    assert log == ["crm", "push"]
    # A worker without clients closes without doing anything.
    await OutboxWorker(
        worker_id="close-proof",
        queue=IdleQueue(),
        handlers={"proof.v1": Idle()},
        retry_policy=RetryPolicy(),
    ).close()


@pytest.mark.asyncio
async def test_a_worker_that_cannot_be_built_leaves_nothing_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pool, the CRM client and the push client exist before the modules
    are built. If that step fails, the caller gets no worker to close."""
    log: list[str] = []
    pool = Closable("pool", log)
    crm = Closable("crm", log)
    push_client = Closable("push", log)

    async def create_pool(database_url: str, *, maximum_size: int) -> Closable:
        return pool

    def broken_modules(*_: Any, **__: Any) -> Any:
        raise RuntimeError("module table is broken")

    class PushSettingsStub:
        def signer(self) -> None:
            return None

    monkeypatch.setattr(bootstrap, "create_pool", create_pool)
    monkeypatch.setattr(bootstrap, "crm_gateway_from_environment", lambda: crm)
    monkeypatch.setattr(bootstrap, "load_push_settings", PushSettingsStub)
    monkeypatch.setattr(
        bootstrap,
        "push_sender",
        lambda settings: (
            object(),
            type("Client", (), {"aclose": push_client.close})(),
        ),
    )
    monkeypatch.setattr(bootstrap, "worker_modules", broken_modules)
    monkeypatch.setattr(bootstrap, "object_storage_from_environment", lambda: object())
    monkeypatch.setattr(bootstrap, "mail_transport_from_environment", lambda: object())
    monkeypatch.setenv("LEONAID_SESSION_ENCRYPTION_KEY", "x" * 40)

    with pytest.raises(RuntimeError, match="module table is broken"):
        await build_worker(
            database_url="postgresql://unused",
            worker_id="close-proof",
            max_attempts=5,
            base_backoff_seconds=5,
            claim_lease_seconds=300,
            disabled=frozenset(),
        )

    assert log == ["crm", "push", "pool"]
