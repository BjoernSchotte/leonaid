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
from leonaid.adapters.postgres.public_orders import AsyncpgPublicOrderRepository
from leonaid.application.public_orders import (
    PublicOrderDraft,
    PublicOrderPartyDraft,
    PublicOrderCrmOutcome,
    ResolvedPublicParty,
)
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
        for day in (10, 11, 12, 13)
    )
    await schedules.save(replace(current, windows=(*current.windows, *windows)))

    alias = f"race-{action_id}"
    async with pool.acquire() as connection:
        for status in ("scheduled", "active"):
            await connection.execute(
                "UPDATE charity_action SET status = $2 WHERE id = $1", action_id, status
            )
        await connection.execute(
            "UPDATE charity_action SET publication_starts_at = '2026-12-01', publication_ends_at = '2027-03-01' WHERE id = $1",
            action_id,
        )
        await connection.execute(
            "INSERT INTO public_action_alias(alias, action_id) VALUES ($1, $2)",
            alias,
            action_id,
        )
        await connection.execute(
            """INSERT INTO order_form_configuration
            (id, action_id, form_key, status, title, introduction, submit_label,
             require_company_name, require_contact_name, require_email, require_phone,
             require_delivery_address, require_billing_address, allow_message)
            VALUES ($1, $2, 'race', 'active', 'Race', 'Race', 'Order',
                    false, true, true, false, true, true, true)""",
            uuid4(),
            action_id,
        )

    async def create(
        using_pool: asyncpg.Pool[Any], value: CommitmentDraft, key: str, public: bool
    ) -> Commitment:
        if public:
            assert (
                value.delivery_recipient is not None
                and value.invoice_recipient is not None
            )
            public_draft = PublicOrderDraft(
                party=PublicOrderPartyDraft(
                    "Race company", "Test", "Contact", "race@example.invalid"
                ),
                delivery_recipient=value.delivery_recipient,
                invoice_recipient=value.invoice_recipient,
                lines=tuple(
                    replace(line, quoted_unit_price_minor=100) for line in value.lines
                ),
                message=None,
                privacy_acknowledged=True,
                binding_order_confirmed=True,
                privacy_notice_version="race-v1",
                delivery_window_id=value.delivery_window_id,
            )
            request_hash = public_draft.request_hash(
                action_id=action_id, public_alias=alias
            )
            repository = AsyncpgPublicOrderRepository(using_pool)
            async with repository.order_command(
                lock_key=key, idempotency_key=key, request_hash=request_hash
            ) as command:
                if command.existing_result is not None:
                    return replace(command.existing_result.commitment, replayed=True)
                result = await command.record_order(
                    action_id=action_id,
                    public_alias=alias,
                    party=ResolvedPublicParty(
                        value.buyer, None, PublicOrderCrmOutcome.REUSED
                    ),
                    draft=public_draft,
                    idempotency_key=key,
                    request_hash=request_hash,
                    request_id="public-delivery-race",
                    occurred_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
                )
                await command.complete(result)
                return result.commitment
        return await AsyncpgCommitmentRepository(using_pool).create(
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

    for (public, retire_first), window in zip(
        ((False, True), (False, False), (True, True), (True, False)),
        windows,
        strict=True,
    ):
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
        booking_pool = pool if retire_first else wrapped
        schedule_repository = AsyncpgDeliveryRepository(
            wrapped if retire_first else pool
        )
        booking: asyncio.Task[Commitment] | None = None
        retirement: asyncio.Task[Any] | None = None
        try:
            if retire_first:
                retirement = asyncio.create_task(schedule_repository.save(retired))
            else:
                booking = asyncio.create_task(create(booking_pool, value, key, public))
            await asyncio.wait_for(gate.locked.wait(), 10)
            if retire_first:
                booking = asyncio.create_task(create(booking_pool, value, key, public))
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
                replay = await create(pool, value, key, public)
                assert replay.id == result.id and replay.replayed
                assert (
                    replay.delivery_window_snapshot == result.delivery_window_snapshot
                )
                assert replay.delivery_recipient == result.delivery_recipient
                async with pool.acquire() as observer:
                    assert (
                        await observer.fetchval(
                            "SELECT count(*) FROM commitment WHERE idempotency_key = $1",
                            key,
                        )
                        == 1
                    )
                    if public:
                        assert (
                            await observer.fetchval(
                                "SELECT count(*) FROM consent_record WHERE commitment_id = $1",
                                result.id,
                            )
                            == 1
                        )
                        assert (
                            await observer.fetchval(
                                "SELECT count(*) FROM activity_event WHERE event_type = 'public_order_received' AND payload ->> 'commitmentId' = $1",
                                str(result.id),
                            )
                            == 1
                        )
        finally:
            gate.release.set()
            tasks = [task for task in (booking, retirement) if task is not None]
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    print(
        "delivery-races: PASS: acquisition and public repositories block in both orders; retirement rejects fresh booking; booking preserves history, consent, activity and replay"
    )
