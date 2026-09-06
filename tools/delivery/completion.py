"""Live delivery repair and invoice precondition proof on disposable orders."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.delivery import AsyncpgDeliveryRepository
from leonaid.adapters.postgres.delivery_completion import (
    AsyncpgDeliveryCompletionRepository,
)
from leonaid.adapters.postgres.invoices import AsyncpgInvoiceRepository
from leonaid.application.delivery_completion import (
    DeliveryCompletionDraft,
    DeliveryCompletionService,
    delivery_completion_version,
)
from leonaid.application.errors import Conflict, PermissionDenied, ResourceNotFound
from leonaid.domain.commitments import (
    Commitment,
    CommitmentStatus,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
)
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    IdentityPrincipal,
    UserAccount,
)


async def prove_completion(
    pool: asyncpg.Pool[Any], action_id: UUID, actor_id: UUID, order: Commitment
) -> None:
    now = datetime(2027, 1, 1, tzinfo=timezone.utc)
    schedules = AsyncpgDeliveryRepository(pool)
    schedule = await schedules.get(action_id)
    window = next(window for window in schedule.windows if not window.retired)
    account = UserAccount(
        actor_id, "order@example.invalid", "Test", AccountStatus.ACTIVE
    )

    def principal(
        role: ActionRole, scoped_action: UUID = action_id
    ) -> IdentityPrincipal:
        return IdentityPrincipal(
            account,
            frozenset(),
            (ActionMembership(uuid4(), scoped_action, "Test", actor_id, role, now),),
        )

    service = DeliveryCompletionService(AsyncpgDeliveryCompletionRepository(pool))
    draft = DeliveryCompletionDraft(
        delivery_completion_version(order),
        DeliveryRecipientSnapshot(
            "Delivery repair",
            "Floorweg 4",
            "00000",
            "Teststadt",
            instructions="Department\nFloor 4",
        ),
        InvoiceRecipientSnapshot(
            "Invoice repair",
            "Rechnungsweg 8",
            "00000",
            "Teststadt",
            email="invoice@example.invalid",
        ),
        window.id,
    )

    async def complete(
        value: DeliveryCompletionDraft,
        key: str,
        actor: IdentityPrincipal | None = None,
        identifier: UUID = order.id,
    ) -> Commitment:
        return await service.complete(
            actor or principal(ActionRole.CHARITY_ADMIN),
            action_id,
            identifier,
            draft=value,
            key=key,
            request_id="completion-proof",
            now=now,
        )

    for unauthorized in (
        principal(ActionRole.ACQUIRER),
        principal(ActionRole.DRIVER),
        principal(ActionRole.CHARITY_ADMIN, uuid4()),
    ):
        try:
            await complete(draft, str(uuid4()), unauthorized)
        except PermissionDenied:
            pass
        else:
            raise AssertionError("Unauthorized delivery completion accepted")
    try:
        await complete(draft, str(uuid4()), identifier=uuid4())
    except ResourceNotFound:
        pass
    else:
        raise AssertionError("Missing order completion accepted")
    async with pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO charity_action_capability(action_id, capability) VALUES ($1, 'invoicing')",
            action_id,
        )

    async def issue(expected: str) -> None:
        try:
            await AsyncpgInvoiceRepository(pool).issue(
                action_id=action_id,
                commitment_id=order.id,
                actor_user_id=actor_id,
                service_on=date(2027, 2, 5),
                idempotency_key=str(uuid4()),
                request_hash="a" * 64,
                request_id="completion-invoice-proof",
                occurred_at=now,
            )
        except Conflict as error:
            assert error.code == expected, error.code
        else:
            raise AssertionError("Incomplete fixture unexpectedly issued an invoice")

    await issue("invoice_delivery_incomplete")
    keys = (str(uuid4()), str(uuid4()))
    results = await asyncio.gather(
        *(complete(draft, key) for key in keys), return_exceptions=True
    )
    assert sum(isinstance(result, Conflict) for result in results) == 1
    saved = next(result for result in results if isinstance(result, Commitment))
    key = keys[results.index(saved)]
    assert saved.status is CommitmentStatus.REVIEW_READY
    assert (
        saved.total == order.total
        and saved.lines == order.lines
        and saved.buyer == order.buyer
    )
    assert (
        saved.invoice_recipient == draft.invoice_recipient
        and saved.delivery_recipient == draft.delivery_recipient
    )
    assert saved.delivery_window_snapshot == window.snapshot(schedule.timezone)
    await issue("invoice_profile_missing")
    # Retired booked times remain valid for completion replay and invoice review.
    await schedules.save(
        replace(
            schedule,
            windows=tuple(
                replace(item, retired=True) if item.id == window.id else item
                for item in schedule.windows
            )
            + (replace(window, id=uuid4(), delivery_on=date(2027, 2, 20)),),
        )
    )
    replay = await complete(draft, key)
    assert replay.id == saved.id and replay.replayed
    assert replay.delivery_window_snapshot == saved.delivery_window_snapshot
    await issue("invoice_profile_missing")
    for changed, expected in (
        (
            replace(
                draft,
                invoice_recipient=replace(draft.invoice_recipient, city="Changed"),
            ),
            "idempotency_conflict",
        ),
    ):
        try:
            await complete(changed, key)
        except Conflict as error:
            assert error.code == expected
        else:
            raise AssertionError("Changed completion reused a command key")
    async with pool.acquire() as connection:
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM audit_event WHERE entity_id = $1 AND event_type = 'commitment_delivery_completed'",
                order.id,
            )
            == 1
        )
        await connection.execute(
            "UPDATE commitment SET status = 'confirmed' WHERE id = $1", order.id
        )
    try:
        await complete(
            replace(draft, expected_version=delivery_completion_version(saved)),
            str(uuid4()),
        )
    except Conflict as error:
        assert error.code == "delivery_completion_closed"
    else:
        raise AssertionError("Confirmed order was editable")
    print(
        "delivery-completion: PASS: authorization, invoice guard, concurrent edits, unchanged price/lines, billing/delivery snapshots, retirement replay and confirmed-order protection"
    )
