"""Live order integration checks, using the real commitment repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery import AsyncpgDeliveryRepository
from leonaid.application.commitments import CommitmentDraft, CommitmentLineDraft
from leonaid.application.errors import Conflict
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import (
    BuyerSnapshot,
    Commitment,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
)
from leonaid.domain.errors import DomainInvariantError
from tools.delivery.form_configuration import prove_form_configuration
from tools.delivery.concurrency import prove_booking_races
from tools.delivery.completion import prove_completion


async def prove_orders(pool: asyncpg.Pool[Any], action_id: UUID) -> None:
    actor, offering = uuid4(), uuid4()
    async with pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO user_account(id, email, display_name, status) VALUES ($1, 'order@example.invalid', 'Test', 'active')",
            actor,
        )
        await connection.execute(
            "INSERT INTO charity_action_capability(action_id, capability) VALUES ($1, 'ordering')",
            action_id,
        )
        await connection.execute(
            """INSERT INTO offering(id, action_id, code, name, status, unit, unit_price_minor, currency, allowed_quantity_units)
            VALUES ($1, $2, 'test', 'Test', 'active', 'piece', 100, 'EUR', ARRAY['piece'])""",
            offering,
            action_id,
        )
    schedules = AsyncpgDeliveryRepository(pool)
    schedule = await schedules.get(action_id)
    window = next(item for item in schedule.windows if not item.retired)
    draft = CommitmentDraft(
        buyer=BuyerSnapshot(CommitmentPartyKind.COMPANY, uuid4(), "Test buyer"),
        invoice_recipient=InvoiceRecipientSnapshot(
            "Invoice", "Testweg 2", "00000", "Teststadt"
        ),
        delivery_recipient=DeliveryRecipientSnapshot(
            "Delivery",
            "Testweg 1",
            "00000",
            "Teststadt",
            instructions="Department\nFloor 4",
        ),
        lines=(CommitmentLineDraft(offering, 2, OfferingUnit.PIECE),),
        delivery_window_id=window.id,
    )
    repository = AsyncpgCommitmentRepository(pool)
    async with pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO acquisition_assignment(id, action_id, twenty_company_id, acquirer_user_id) VALUES ($1, $2, $3, $4)",
            uuid4(),
            action_id,
            draft.buyer.twenty_id,
            actor,
        )

    async def create(
        value: CommitmentDraft,
        key: str,
        status: CommitmentStatus = CommitmentStatus.REVIEW_READY,
    ) -> Commitment:
        return await repository.create(
            action_id=action_id,
            actor_user_id=actor,
            source=CommitmentSource.ACQUISITION,
            status=status,
            draft=value,
            idempotency_key=key,
            request_hash=value.fingerprint(
                action_id=action_id, source=CommitmentSource.ACQUISITION, status=status
            ),
            request_id="delivery-live",
            occurred_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        )

    for invalid in (
        replace(draft, delivery_window_id=None),
        replace(draft, delivery_recipient=None),
        replace(draft, delivery_window_id=uuid4()),
    ):
        try:
            await create(invalid, str(uuid4()))
        except DomainInvariantError:
            pass
        else:
            raise AssertionError("Incomplete or foreign delivery accepted")
    incomplete = await create(
        replace(draft, delivery_window_id=None, delivery_recipient=None),
        str(uuid4()),
        CommitmentStatus.DRAFT,
    )
    assert incomplete.delivery_window_id is None
    key = str(uuid4())
    order = await create(draft, key)
    assert order.total.amount_minor == 200
    assert order.delivery_window_snapshot == window.snapshot(schedule.timezone)
    records = await repository.list_for_action(action_id=action_id)
    loaded = next(
        record.commitment for record in records if record.commitment.id == order.id
    )
    assert loaded.delivery_window_snapshot == order.delivery_window_snapshot
    assert loaded.delivery_recipient == draft.delivery_recipient
    # Keep another window selectable so retiring the booked window is a valid save.
    replacement = replace(
        window,
        id=uuid4(),
        starts_at=window.ends_at,
        ends_at=window.ends_at.replace(hour=window.ends_at.hour + 1),
    )
    await schedules.save(
        replace(
            schedule,
            windows=tuple(
                replace(w, retired=True) if w.id == window.id else w
                for w in schedule.windows
            )
            + (replacement,),
        )
    )
    replay = await create(draft, key)
    assert replay.id == order.id and replay.replayed
    assert replay.delivery_window_snapshot == order.delivery_window_snapshot
    try:
        await create(replace(draft, delivery_window_id=replacement.id), key)
    except Conflict:
        pass
    else:
        raise AssertionError("Changed delivery selection reused an idempotency key")
    try:
        await create(draft, str(uuid4()))
    except DomainInvariantError:
        pass
    else:
        raise AssertionError("Retired delivery window accepted a fresh order")
    print(
        "delivery-orders: PASS: creation/readback, incomplete draft, required fields, retirement, exact replay and changed-key conflict"
    )
    await prove_booking_races(pool, action_id, actor, draft)
    await prove_completion(pool, action_id, actor, incomplete)
    await prove_form_configuration(pool, actor)
