"""Deterministic booking/retirement races through the real repository transactions.

Every case pauses one side directly after it holds the real action row lock,
starts the other side, waits until PostgreSQL reports the second side as
blocked by the first, and only then releases the first side. Both orders are
proven for every path that books a delivery window:

- acquisition capture (SERIALIZABLE),
- public order (READ COMMITTED command transaction),
- draft completion by the order owner or a manager (SERIALIZABLE),
- manager completion of delivery and billing details (SERIALIZABLE).

A negative control removes the configuration row lock from the acquisition
path and proves the race then persists a booking against a retired window.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, datetime, time, timezone
from typing import Any, cast
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres import commitments as commitment_adapter
from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery import (
    AsyncpgDeliveryRepository,
    read_configuration,
)
from leonaid.adapters.postgres.delivery_completion import (
    AsyncpgDeliveryCompletionRepository,
)
from leonaid.adapters.postgres.public_orders import AsyncpgPublicOrderRepository
from leonaid.application.commitments import CommitmentCompletion, CommitmentDraft
from leonaid.application.delivery_completion import (
    DeliveryCompletionDraft,
    delivery_completion_version,
)
from leonaid.application.public_orders import (
    PublicOrderCrmOutcome,
    PublicOrderDraft,
    PublicOrderPartyDraft,
    ResolvedPublicParty,
)
from leonaid.domain.commitments import (
    Commitment,
    CommitmentSource,
    CommitmentStatus,
)
from leonaid.domain.delivery import DeliveryWindow
from leonaid.domain.errors import DomainInvariantError

Booking = Callable[[Any, str], Coroutine[Any, Any, Commitment]]


class LockGate:
    """Pause once after a real action row lock; all other SQL is unchanged."""

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
                        await asyncio.wait_for(gate.release.wait(), 20)
                    return row

            yield Connection()


async def wait_for_blocked(pool: asyncpg.Pool[Any], gate: LockGate) -> None:
    async with asyncio.timeout(20):
        while not await pool.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
            "WHERE $1 = ANY(pg_blocking_pids(pid)))",
            gate.pid,
        ):
            await asyncio.sleep(0.01)


async def race(
    pool: asyncpg.Pool[Any],
    *,
    action_id: UUID,
    window: DeliveryWindow,
    booking: Booking,
    key: str,
    retire_first: bool,
) -> Commitment | BaseException:
    """Run one deterministic race and return the booking outcome."""
    schedules = AsyncpgDeliveryRepository(pool)
    current = await schedules.get(action_id)
    retired = replace(
        current,
        windows=tuple(
            replace(item, retired=True) if item.id == window.id else item
            for item in current.windows
        ),
    )
    gate = LockGate(pool, "FOR UPDATE" if retire_first else "FOR SHARE")
    gated = cast("asyncpg.Pool[Any]", gate)
    retirement_repository = AsyncpgDeliveryRepository(gated if retire_first else pool)
    first: asyncio.Task[Any]
    second: asyncio.Task[Any] | None = None
    if retire_first:
        first = asyncio.create_task(retirement_repository.save(retired))
    else:
        first = asyncio.create_task(booking(gated, key))
    try:
        await asyncio.wait_for(gate.locked.wait(), 20)
        if retire_first:
            second = asyncio.create_task(booking(pool, key))
        else:
            second = asyncio.create_task(retirement_repository.save(retired))
        await wait_for_blocked(pool, gate)
        gate.release.set()
        outcomes = await asyncio.wait_for(
            asyncio.gather(first, second, return_exceptions=True), 20
        )
    finally:
        gate.release.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (first, second) if task is not None),
            return_exceptions=True,
        )
    saved, booked = (outcomes[0], outcomes[1]) if retire_first else outcomes[::-1]
    if isinstance(saved, BaseException):
        raise saved
    after = await schedules.get(action_id)
    assert next(w for w in after.windows if w.id == window.id).retired
    return cast("Commitment | BaseException", booked)


async def prove_booking_races(
    pool: asyncpg.Pool[Any],
    *,
    action_id: UUID,
    admin_id: UUID,
    draft: CommitmentDraft,
    alias: str,
) -> None:
    # A separate customer keeps the privacy lookup proof of orders.py exact.
    assert draft.invoice_recipient is not None
    draft = replace(
        draft,
        buyer=replace(draft.buyer, email="race@example.invalid"),
        invoice_recipient=replace(
            draft.invoice_recipient, email="race@example.invalid"
        ),
    )
    schedules = AsyncpgDeliveryRepository(pool)
    current = await schedules.get(action_id)
    windows = tuple(
        DeliveryWindow(uuid4(), action_id, date(2037, 12, day), time(8), time(10))
        for day in range(10, 19)
    )
    await schedules.save(replace(current, windows=(*current.windows, *windows)))
    timezone_name = current.timezone
    buyer = draft.buyer
    await pool.execute(
        """INSERT INTO acquisition_assignment
        (id, action_id, twenty_company_id, twenty_person_id, acquirer_user_id)
        VALUES ($1, $2, $3, $4, $5)""",
        uuid4(),
        action_id,
        buyer.company_id,
        buyer.person_id,
        admin_id,
    )
    commitments = AsyncpgCommitmentRepository
    undelivered = replace(
        draft, delivery_recipient=None, delivery_window_id=None, delivery_contact=None
    )

    async def acquisition(
        using: asyncpg.Pool[Any], key: str, window: DeliveryWindow
    ) -> Commitment:
        value = replace(draft, delivery_window_id=window.id)
        return await commitments(using).create(
            action_id=action_id,
            actor_user_id=admin_id,
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
            occurred_at=datetime.now(timezone.utc),
        )

    async def public(
        using: asyncpg.Pool[Any], key: str, window: DeliveryWindow
    ) -> Commitment:
        assert draft.delivery_recipient is not None
        assert draft.invoice_recipient is not None
        value = PublicOrderDraft(
            PublicOrderPartyDraft(None, "Race", "Customer", "race@example.invalid"),
            draft.delivery_recipient,
            draft.invoice_recipient,
            draft.lines,
            None,
            True,
            True,
            "race-v1",
            delivery_window_id=window.id,
            delivery_contact=draft.delivery_contact,
        )
        request_hash = value.request_hash(action_id=action_id, public_alias=alias)
        async with AsyncpgPublicOrderRepository(using).order_command(
            lock_key=key, idempotency_key=key, request_hash=request_hash
        ) as command:
            if command.existing_result is not None:
                return replace(command.existing_result.commitment, replayed=True)
            result = await command.record_order(
                action_id=action_id,
                public_alias=alias,
                party=ResolvedPublicParty(buyer, None, PublicOrderCrmOutcome.REUSED),
                draft=value,
                idempotency_key=key,
                request_hash=request_hash,
                request_id="delivery-race",
                occurred_at=datetime.now(timezone.utc),
            )
            await command.complete(result)
            return result.commitment

    async def new_draft() -> Commitment:
        return await commitments(pool).create(
            action_id=action_id,
            actor_user_id=admin_id,
            source=CommitmentSource.ACQUISITION,
            status=CommitmentStatus.DRAFT,
            draft=undelivered,
            idempotency_key=f"race-draft:{uuid4()}",
            request_hash=uuid4().hex * 2,
            request_id="delivery-race",
            occurred_at=datetime.now(timezone.utc),
        )

    def draft_completion(order: Commitment) -> Callable[..., Awaitable[Commitment]]:
        async def complete(
            using: asyncpg.Pool[Any], key: str, window: DeliveryWindow
        ) -> Commitment:
            completion = CommitmentCompletion(
                draft.delivery_recipient, window.id, draft.delivery_contact
            )
            return await commitments(using).complete_draft(
                action_id=action_id,
                commitment_id=order.id,
                actor_user_id=admin_id,
                as_manager=True,
                completion=completion,
                idempotency_key=key,
                request_hash=completion.fingerprint(
                    action_id=action_id,
                    commitment_id=order.id,
                    actor_user_id=admin_id,
                ),
                request_id="delivery-race",
                occurred_at=datetime.now(timezone.utc),
            )

        return complete

    def manager_completion(order: Commitment) -> Callable[..., Awaitable[Commitment]]:
        async def complete(
            using: asyncpg.Pool[Any], key: str, window: DeliveryWindow
        ) -> Commitment:
            assert draft.invoice_recipient is not None
            value = DeliveryCompletionDraft(
                expected_version=delivery_completion_version(order),
                invoice_recipient=draft.invoice_recipient,
                delivery_recipient=draft.delivery_recipient,
                delivery_window_id=window.id,
                delivery_contact=draft.delivery_contact,
            )
            return await AsyncpgDeliveryCompletionRepository(using).complete_delivery(
                action_id=action_id,
                commitment_id=order.id,
                actor_user_id=admin_id,
                draft=value,
                idempotency_key=key,
                request_hash=value.fingerprint(
                    action_id=action_id,
                    commitment_id=order.id,
                    actor_user_id=admin_id,
                ),
                request_id="delivery-race",
                occurred_at=datetime.now(timezone.utc),
            )

        return complete

    async def persisted(key: str, order: Commitment | None) -> int:
        if order is None:
            return int(
                await pool.fetchval(
                    "SELECT count(*) FROM commitment WHERE idempotency_key = $1", key
                )
            )
        return int(
            await pool.fetchval(
                """SELECT count(*) FROM commitment
                WHERE id = $1 AND delivery_window_id IS NOT NULL""",
                order.id,
            )
        )

    window_iter = iter(windows)
    paths = ("acquisition", "public", "draft-completion", "manager-completion")
    for path in paths:
        for retire_first in (True, False):
            window = next(window_iter)
            order: Commitment | None = None
            if path == "acquisition":
                factory: Callable[..., Awaitable[Commitment]] = acquisition
            elif path == "public":
                factory = public
            else:
                order = await new_draft()
                factory = (
                    draft_completion(order)
                    if path == "draft-completion"
                    else manager_completion(order)
                )

            async def booking(
                using: asyncpg.Pool[Any],
                key: str,
                factory: Callable[..., Awaitable[Commitment]] = factory,
                window: DeliveryWindow = window,
            ) -> Commitment:
                return await factory(using, key, window)

            key = f"race:{uuid4()}"
            result = await race(
                pool,
                action_id=action_id,
                window=window,
                booking=booking,
                key=key,
                retire_first=retire_first,
            )
            label = f"{path}/{'retirement-first' if retire_first else 'booking-first'}"
            if retire_first:
                assert isinstance(result, DomainInvariantError), (label, result)
                assert result.code == "delivery_window_unavailable", label
                assert await persisted(key, order) == 0, label
                assert not await pool.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM command_receipt WHERE idempotency_key = $1)",
                    key,
                ), label
                if order is not None:
                    status = await pool.fetchval(
                        "SELECT status FROM commitment WHERE id = $1", order.id
                    )
                    assert status == "draft", label
            else:
                assert isinstance(result, Commitment), (label, result)
                assert result.delivery_window_snapshot == window.snapshot(
                    timezone_name
                ), label
                assert await persisted(key, order) == 1, label
                replay = await booking(pool, key)
                assert replay.replayed and replay.id == result.id, label
                assert (
                    replay.delivery_window_snapshot == result.delivery_window_snapshot
                ), label
                assert replay.delivery_recipient == result.delivery_recipient, label
                if path == "public":
                    assert (
                        await pool.fetchval(
                            "SELECT count(*) FROM consent_record WHERE commitment_id = $1",
                            result.id,
                        )
                        == 1
                    ), label
            print(f"delivery-races: PASS {label}")

    # Negative control: without the configuration row lock, a SERIALIZABLE
    # acquisition booking that waited on the action lock keeps its stale
    # snapshot and persists a booking against the just-retired window. The
    # "ausgebucht" guard's window row lock would also catch it (the
    # retirement changes that row), so the control replaces the guard with a
    # no-op; the proof window is not full.
    window = next(window_iter)
    original = getattr(commitment_adapter, "lock_configuration")
    original_guard = getattr(commitment_adapter, "guard_window_booking")

    async def unlocked_guard(
        connection: asyncpg.Connection[Any],
        *,
        window_id: UUID | None,
        allow_full_window: bool,
    ) -> bool:
        return False

    setattr(commitment_adapter, "lock_configuration", read_configuration)
    setattr(commitment_adapter, "guard_window_booking", unlocked_guard)
    try:
        key = f"race:{uuid4()}"

        async def unlocked(using: asyncpg.Pool[Any], key: str) -> Commitment:
            return await acquisition(using, key, window)

        result = await race(
            pool,
            action_id=action_id,
            window=window,
            booking=unlocked,
            key=key,
            retire_first=True,
        )
    finally:
        setattr(commitment_adapter, "lock_configuration", original)
        setattr(commitment_adapter, "guard_window_booking", original_guard)
    assert isinstance(result, Commitment), (
        "Negative control did not reproduce the stale booking",
        result,
    )
    assert await persisted(key, None) == 1
    retired_window = await pool.fetchval(
        "SELECT retired FROM action_delivery_window WHERE id = $1", window.id
    )
    assert retired_window is True
    print(
        "delivery-races: PASS negative control: without the configuration row lock "
        "a retirement-first acquisition booking is persisted against a retired window"
    )
