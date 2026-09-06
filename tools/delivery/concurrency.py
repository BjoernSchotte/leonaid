"""Deterministic live booking/retirement races with real repository transactions."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any, AsyncIterator, cast
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery import AsyncpgDeliveryRepository
from leonaid.application.commitments import CommitmentDraft
from leonaid.domain.commitments import Commitment, CommitmentSource, CommitmentStatus
from leonaid.domain.errors import DomainInvariantError


class LockGate:
    """Pause once after a real action lock; all other SQL delegates unchanged."""

    def __init__(self, pool: asyncpg.Pool[Any], clause: str) -> None:
        self.pool = pool
        self.clause = clause
        self.locked = asyncio.Event()
        self.release = asyncio.Event()
        self.pid: int | None = None

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        async with self.pool.acquire() as connection:
            gate = self

            class Connection:
                def __getattr__(self, name: str) -> Any:
                    return getattr(connection, name)

                async def fetchrow(self, sql: str, *args: Any) -> Any:
                    row = await connection.fetchrow(sql, *args)
                    if (
                        "FROM charity_action" in sql
                        and gate.clause in sql
                        and not gate.locked.is_set()
                    ):
                        gate.pid = connection.get_server_pid()
                        gate.locked.set()
                        await asyncio.wait_for(gate.release.wait(), 10)
                    return row

            yield Connection()


async def wait_for_blocked(pool: asyncpg.Pool[Any], gate: LockGate) -> None:
    async with asyncio.timeout(10):
        async with pool.acquire() as observer:
            while not await observer.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                "WHERE $1 = ANY(pg_blocking_pids(pid)))",
                gate.pid,
            ):
                await asyncio.sleep(0.01)


async def prove_booking_races(
    pool: asyncpg.Pool[Any], action_id: UUID, actor: UUID, draft: CommitmentDraft
) -> None:
    schedules = AsyncpgDeliveryRepository(pool)
    current = await schedules.get(action_id)
    prototype = current.windows[-1]
    windows = tuple(
        replace(prototype, id=uuid4(), delivery_on=date(2027, 2, day), retired=False)
        for day in (10, 11)
    )
    await schedules.save(replace(current, windows=(*current.windows, *windows)))

    async def create(
        repository: AsyncpgCommitmentRepository, value: CommitmentDraft, key: str
    ) -> Commitment:
        return await repository.create(
            action_id=action_id,
            actor_user_id=actor,
            source=CommitmentSource.ACQUISITION,
            status=CommitmentStatus.REVIEW_READY,
            draft=value,
            idempotency_key=key,
            request_hash=value.fingerprint(
                action_id=action_id,
                source=CommitmentSource.ACQUISITION,
                status=CommitmentStatus.REVIEW_READY,
            ),
            request_id="delivery-race",
            occurred_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        )

    for retire_first, window in zip((True, False), windows, strict=True):
        current = await schedules.get(action_id)
        retired = replace(
            current,
            windows=tuple(
                replace(item, retired=True) if item.id == window.id else item
                for item in current.windows
            ),
        )
        value = replace(draft, delivery_window_id=window.id)
        key = str(uuid4())
        gate = LockGate(pool, "FOR UPDATE" if retire_first else "FOR SHARE")
        wrapped = cast("asyncpg.Pool[Any]", gate)
        booking_repository = AsyncpgCommitmentRepository(
            pool if retire_first else wrapped
        )
        schedule_repository = AsyncpgDeliveryRepository(
            wrapped if retire_first else pool
        )
        booking: asyncio.Task[Commitment] | None = None
        retirement: asyncio.Task[Any] | None = None
        try:
            if retire_first:
                retirement = asyncio.create_task(schedule_repository.save(retired))
            else:
                booking = asyncio.create_task(create(booking_repository, value, key))
            await asyncio.wait_for(gate.locked.wait(), 10)
            if retire_first:
                booking = asyncio.create_task(create(booking_repository, value, key))
            else:
                retirement = asyncio.create_task(schedule_repository.save(retired))
            await wait_for_blocked(pool, gate)
            gate.release.set()
            assert booking is not None and retirement is not None
            result, saved = await asyncio.wait_for(
                asyncio.gather(booking, retirement, return_exceptions=True), 10
            )
            if isinstance(saved, BaseException):
                raise saved
            async with pool.acquire() as observer:
                count = await observer.fetchval(
                    "SELECT count(*) FROM commitment WHERE idempotency_key = $1", key
                )
            if retire_first:
                assert isinstance(result, DomainInvariantError), result
                assert result.code == "delivery_window_unavailable"
                assert count == 0, "Retirement-first race persisted an invalid booking"
            else:
                assert isinstance(result, Commitment), result
                assert count == 1
                assert result.delivery_window_snapshot == window.snapshot(
                    current.timezone
                )
                replay = await create(AsyncpgCommitmentRepository(pool), value, key)
                assert replay.id == result.id and replay.replayed
                assert (
                    replay.delivery_window_snapshot == result.delivery_window_snapshot
                )
        finally:
            gate.release.set()
            tasks = [task for task in (booking, retirement) if task is not None]
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    print(
        "delivery-races: PASS: observed real blocking in both orders; retirement rejects fresh booking; booking preserves history and replay"
    )
