"""Manager completion of delivery and billing details: version and authorization."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from leonaid.application.delivery_completion import (
    DeliveryCompletionDraft,
    DeliveryCompletionService,
    delivery_completion_version,
)
from leonaid.application.errors import PermissionDenied
from leonaid.domain.commitments import (
    BuyerSnapshot,
    Commitment,
    CommitmentLine,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
    Money,
)
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.delivery import DeliveryContactSnapshot
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    IdentityPrincipal,
    UserAccount,
)

ACTION_ID = uuid4()
INVOICE = InvoiceRecipientSnapshot("Billing", "Invoice road 1", "12345", "Test")
DELIVERY = DeliveryRecipientSnapshot("Warehouse", "Delivery road 2", "12345", "Test")
OFFERING_ID = uuid4()


def line(quantity: int) -> CommitmentLine:
    return CommitmentLine(
        id=UUID("81000000-0000-4000-8000-000000000001"),
        offering_id=OFFERING_ID,
        description_snapshot="Krapfen",
        quantity=quantity,
        unit_snapshot=OfferingUnit.BOX,
        pieces_per_unit_snapshot=12,
        unit_price=Money(100, "EUR"),
        line_total=Money(100 * quantity, "EUR"),
    )


def order(**changes: Any) -> Commitment:
    value = Commitment(
        id=UUID("80000000-0000-4000-8000-000000000099"),
        action_id=ACTION_ID,
        source=CommitmentSource.ACQUISITION,
        status=CommitmentStatus.REVIEW_READY,
        buyer=BuyerSnapshot(CommitmentPartyKind.PERSON, uuid4(), "Buyer"),
        invoice_recipient=None,
        lines=(line(2),),
        total=Money(200, "EUR"),
    )
    return replace(value, **changes)


def principal(role: ActionRole, scope: UUID = ACTION_ID) -> IdentityPrincipal:
    user = UserAccount(uuid4(), "user@example.invalid", "User", AccountStatus.ACTIVE)
    return IdentityPrincipal(
        user,
        frozenset(),
        (
            ActionMembership(
                uuid4(), scope, "Action", user.id, role, datetime.now(timezone.utc)
            ),
        ),
    )


def test_version_tracks_every_mutable_field_but_not_lines() -> None:
    base = order()
    version = delivery_completion_version(base)
    assert len(version) == 64
    assert delivery_completion_version(replace(base, replayed=True)) == version
    repriced = replace(base, lines=(line(3),), total=Money(300, "EUR"))
    assert delivery_completion_version(repriced) == version
    for changed in (
        replace(base, status=CommitmentStatus.DRAFT),
        replace(base, invoice_recipient=INVOICE),
        replace(base, delivery_recipient=DELIVERY),
        replace(base, delivery_contact=DeliveryContactSnapshot(name="Reception")),
    ):
        assert delivery_completion_version(changed) != version


def test_draft_rejects_malformed_version_and_drops_empty_contact() -> None:
    with pytest.raises(DomainInvariantError) as error:
        DeliveryCompletionDraft(expected_version="stale", invoice_recipient=INVOICE)
    assert error.value.code == "delivery_completion_version_invalid"
    draft = DeliveryCompletionDraft(
        expected_version="a" * 64,
        invoice_recipient=INVOICE,
        delivery_contact=DeliveryContactSnapshot(),
    )
    assert draft.delivery_contact is None


def test_fingerprint_binds_actor_order_version_and_details() -> None:
    draft = DeliveryCompletionDraft("a" * 64, INVOICE, DELIVERY, uuid4())
    actor, order_id = uuid4(), uuid4()

    def fingerprint(value: DeliveryCompletionDraft, **changes: UUID) -> str:
        arguments = {
            "action_id": ACTION_ID,
            "commitment_id": order_id,
            "actor_user_id": actor,
            **changes,
        }
        return value.fingerprint(**arguments)

    base = fingerprint(draft)
    assert fingerprint(draft) == base
    assert fingerprint(draft, actor_user_id=uuid4()) != base
    assert fingerprint(draft, commitment_id=uuid4()) != base
    assert fingerprint(replace(draft, expected_version="b" * 64)) != base
    assert fingerprint(replace(draft, delivery_window_id=None)) != base
    assert (
        fingerprint(
            replace(draft, invoice_recipient=replace(INVOICE, city="Elsewhere"))
        )
        != base
    )


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def complete_delivery(self, **arguments: Any) -> Commitment:
        self.calls.append(arguments)
        return order(invoice_recipient=INVOICE)


@pytest.mark.parametrize("role", [ActionRole.ACQUIRER, ActionRole.DRIVER])
def test_only_action_managers_may_complete(role: ActionRole) -> None:
    repository = RecordingRepository()
    service = DeliveryCompletionService(repository)
    draft = DeliveryCompletionDraft("a" * 64, INVOICE)
    for actor in (principal(role), principal(ActionRole.CHARITY_ADMIN, uuid4())):
        with pytest.raises(PermissionDenied) as error:
            asyncio.run(
                service.complete(
                    actor,
                    ACTION_ID,
                    uuid4(),
                    draft=draft,
                    idempotency_key="delivery-completion:1",
                    request_id="test",
                )
            )
        assert error.value.code == "delivery_completion_manager_required"
    assert repository.calls == []


def test_manager_completion_validates_key_and_passes_fingerprint() -> None:
    repository = RecordingRepository()
    service = DeliveryCompletionService(repository)
    manager = principal(ActionRole.CHARITY_ADMIN)
    draft = DeliveryCompletionDraft("a" * 64, INVOICE)
    with pytest.raises(DomainInvariantError):
        asyncio.run(
            service.complete(
                manager,
                ACTION_ID,
                uuid4(),
                draft=draft,
                idempotency_key="bad key",
                request_id="test",
            )
        )
    order_id = uuid4()
    asyncio.run(
        service.complete(
            manager,
            ACTION_ID,
            order_id,
            draft=draft,
            idempotency_key="delivery-completion:1",
            request_id="test",
        )
    )
    (call,) = repository.calls
    assert call["request_hash"] == draft.fingerprint(
        action_id=ACTION_ID, commitment_id=order_id, actor_user_id=manager.account.id
    )
    assert call["actor_user_id"] == manager.account.id
