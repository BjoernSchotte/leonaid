"""Storage proof for both existing order pipelines, without an external CRM."""

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery import AsyncpgDeliveryRepository
from leonaid.adapters.postgres.public_orders import AsyncpgPublicOrderRepository
from leonaid.application.commitments import CommitmentDraft, CommitmentLineDraft
from leonaid.application.errors import Conflict
from leonaid.application.public_orders import (
    PublicOrderCrmOutcome,
    PublicOrderDraft,
    PublicOrderPartyDraft,
    ResolvedPublicParty,
)
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import (
    BuyerSnapshot,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
)
from leonaid.domain.delivery import DeliveryContactSnapshot
from leonaid.domain.errors import DomainInvariantError


async def prove_orders(pool: asyncpg.Pool, action_id: UUID, admin_id: UUID) -> None:
    repo = AsyncpgCommitmentRepository(pool)
    schedules = AsyncpgDeliveryRepository(pool)
    delivery = await schedules.get(action_id)
    window = delivery.windows[0]
    offering_id = await pool.fetchval(
        "SELECT id FROM offering WHERE action_id=$1 LIMIT 1", action_id
    )
    await pool.execute("UPDATE offering SET status='active' WHERE id=$1", offering_id)
    buyer = BuyerSnapshot(
        CommitmentPartyKind.PERSON, uuid4(), "Customer", "customer@example.invalid"
    )
    invoice = InvoiceRecipientSnapshot(
        "Billing", "Invoice road 1", "12345", "Test", email="customer@example.invalid"
    )
    address = DeliveryRecipientSnapshot("Warehouse", "Delivery road 2", "12345", "Test")
    contact = DeliveryContactSnapshot("Reception", "+49 123-45")
    line = CommitmentLineDraft(offering_id, 2, OfferingUnit.BOX, 3600)
    draft = CommitmentDraft(
        buyer,
        invoice,
        (line,),
        address,
        delivery_window_id=window.id,
        delivery_contact=contact,
    )
    now = datetime.now(timezone.utc)

    async def create(
        value: CommitmentDraft,
        key: str,
        status: CommitmentStatus = CommitmentStatus.REVIEW_READY,
    ):
        return await repo.create(
            action_id=action_id,
            actor_user_id=admin_id,
            source=CommitmentSource.ADMIN,
            status=status,
            draft=value,
            idempotency_key=key,
            request_hash=value.fingerprint(
                action_id=action_id, source=CommitmentSource.ADMIN, status=status
            ),
            request_id="delivery-order-proof",
            occurred_at=now,
        )

    key = f"delivery:{uuid4()}"
    internal = await create(draft, key)
    assert internal.delivery_window_snapshot == window.snapshot(delivery.timezone)
    assert (
        internal.delivery_contact == contact and internal.delivery_recipient == address
    )
    assert internal.invoice_recipient == invoice
    incomplete = replace(
        draft, delivery_recipient=None, delivery_window_id=None, delivery_contact=None
    )
    await create(incomplete, f"delivery:{uuid4()}", CommitmentStatus.DRAFT)
    for invalid in (incomplete, replace(draft, delivery_window_id=uuid4())):
        try:
            await create(invalid, f"delivery:{uuid4()}")
        except DomainInvariantError:
            pass
        else:
            raise AssertionError("Incomplete or foreign delivery accepted")

    # Existing public pipeline: active publication, order token/CRM admission are
    # covered by the public HTTP gate; here exercise its real transaction/store.
    await pool.execute(
        "UPDATE charity_action SET status='active', publication_starts_at=$2, publication_ends_at=$3 WHERE id=$1",
        action_id,
        now - timedelta(days=1),
        now + timedelta(days=1),
    )
    await pool.execute(
        "UPDATE order_form_configuration SET status='active' WHERE action_id=$1",
        action_id,
    )
    alias = f"delivery-{uuid4()}"
    await pool.execute(
        "INSERT INTO public_action_alias(alias,action_id) VALUES ($1,$2)",
        alias,
        action_id,
    )
    public = AsyncpgPublicOrderRepository(pool)
    public_draft = PublicOrderDraft(
        PublicOrderPartyDraft(None, "Test", "Customer", "customer@example.invalid"),
        address,
        invoice,
        (line,),
        None,
        True,
        True,
        "test-v1",
        delivery_window_id=window.id,
        delivery_contact=contact,
    )
    party = ResolvedPublicParty(
        buyer=buyer, contact_twenty_id=None, outcome=PublicOrderCrmOutcome.REUSED
    )
    public_key = f"delivery:{uuid4()}"
    public_hash = public_draft.request_hash(action_id=action_id, public_alias=alias)
    async with public.order_command(
        lock_key=f"delivery:{buyer.twenty_id}",
        idempotency_key=public_key,
        request_hash=public_hash,
    ) as command:
        outcome = await command.record_order(
            action_id=action_id,
            public_alias=alias,
            party=party,
            draft=public_draft,
            idempotency_key=public_key,
            request_hash=public_hash,
            request_id="delivery-order-proof",
            occurred_at=now,
        )
        await command.complete(outcome)
    assert (
        outcome.commitment.delivery_window_snapshot == internal.delivery_window_snapshot
    )
    assert outcome.commitment.delivery_contact == contact
    assert outcome.commitment.delivery_recipient == address
    rows = await pool.fetch(
        "SELECT delivery_window_snapshot, delivery_contact_snapshot FROM commitment WHERE id=ANY($1::uuid[])",
        [internal.id, outcome.commitment.id],
    )
    assert len(rows) == 2 and rows[0] == rows[1]
    assert json.loads(rows[0]["delivery_contact_snapshot"]) == contact.payload()
    listed = await repo.list_for_action(action_id=action_id)
    assert (
        next(
            item.commitment for item in listed if item.commitment.id == internal.id
        ).delivery_contact
        == contact
    )
    retired = replace(
        delivery,
        windows=tuple(
            replace(w, retired=True) if w.id == window.id else w
            for w in delivery.windows
        ),
    )
    await schedules.save(retired)
    assert (await create(draft, key)).replayed
    async with public.order_command(
        lock_key=f"delivery:{buyer.twenty_id}",
        idempotency_key=public_key,
        request_hash=public_hash,
    ) as command:
        assert command.existing_result is not None
        assert command.existing_result.commitment.delivery_contact == contact
        assert (
            command.existing_result.commitment.delivery_window_snapshot
            == internal.delivery_window_snapshot
        )
    try:
        await create(
            replace(draft, delivery_contact=DeliveryContactSnapshot(name="Changed")),
            key,
        )
    except Conflict:
        pass
    else:
        raise AssertionError("Changed idempotent command accepted")
    try:
        await create(draft, f"delivery:{uuid4()}")
    except DomainInvariantError:
        pass
    else:
        raise AssertionError("New booking accepted retired window")
    print(
        "KLF-030 storage PASS: internal/public physical snapshots, separated invoice/delivery/contact, draft, required fields, foreign/unavailable IDs, read/list, immutable replay and changed-command conflict"
    )
