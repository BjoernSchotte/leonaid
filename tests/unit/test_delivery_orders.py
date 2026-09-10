"""Delivery requirements and backward-compatible command identity."""

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, time, timezone
from uuid import UUID, uuid4

import pytest

from leonaid.application.commitments import CommitmentDraft, CommitmentLineDraft
from leonaid.application.public_orders import PublicOrderDraft, PublicOrderPartyDraft
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import (
    BuyerSnapshot,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
)
from leonaid.domain.delivery import (
    DeliveryConfiguration,
    DeliveryContactSnapshot,
    DeliveryWindow,
)
from leonaid.domain.errors import DomainInvariantError


def test_contact_normalization_and_independent_optional_fields() -> None:
    assert DeliveryContactSnapshot(" Reception ", " +49 (0) 123-45 ").payload() == {
        "name": "Reception",
        "phone": "+49 (0) 123-45",
    }
    assert DeliveryContactSnapshot("   ", " ").empty
    assert DeliveryContactSnapshot(phone="123").name is None
    assert DeliveryContactSnapshot(name="Reception").phone is None
    for values in (
        {"name": "x" * 201},
        {"phone": "1" * 41},
        {"name": "A\nB"},
        {"phone": "call me"},
        {"phone": "---"},
    ):
        with pytest.raises(DomainInvariantError):
            DeliveryContactSnapshot(**values)


def test_complete_delivery_is_required_but_drafts_and_non_delivery_are_supported() -> (
    None
):
    action = uuid4()
    window = DeliveryWindow(uuid4(), action, date(2037, 12, 4), time(8), time(10))
    delivery = DeliveryConfiguration(action, True, windows=(window,))
    moment = datetime(2037, 12, 1, tzinfo=timezone.utc)
    for address, selection in ((False, None), (True, None), (False, window.id)):
        with pytest.raises(DomainInvariantError) as error:
            delivery.validate_order(
                window_id=selection,
                has_address=address,
                contact=None,
                complete=True,
                now=moment,
            )
        assert error.value.code == "delivery_required"
    assert (
        delivery.validate_order(
            window_id=None, has_address=False, contact=None, complete=False, now=moment
        )
        is None
    )
    assert (
        DeliveryConfiguration(action).validate_order(
            window_id=None, has_address=False, contact=None, complete=True, now=moment
        )
        is None
    )
    with pytest.raises(DomainInvariantError):
        DeliveryConfiguration(action).validate_order(
            window_id=None,
            has_address=True,
            contact=DeliveryContactSnapshot(name="Test"),
            complete=True,
            now=moment,
        )
    assert (
        delivery.validate_order(
            window_id=window.id,
            has_address=True,
            contact=None,
            complete=True,
            now=moment,
        )["startsAt"]
        == "2037-12-04T07:00:00+00:00"
    )


def test_old_internal_request_hash_is_byte_compatible_and_new_fields_change_it() -> (
    None
):
    action = UUID("20000000-0000-4000-8000-000000000001")
    buyer = BuyerSnapshot(
        CommitmentPartyKind.PERSON, UUID("40000000-0000-4000-8000-000000000001"), "Test"
    )
    line = CommitmentLineDraft(
        UUID("70000000-0000-4000-8000-000000000001"), 1, OfferingUnit.BOX
    )
    draft = CommitmentDraft(buyer, None, (line,))
    # Exact pre-extension wire identity, independent of the new optional fields.
    legacy = {
        "actionId": str(action),
        "source": "acquisition",
        "status": "draft",
        "buyer": buyer.payload(),
        "invoiceRecipient": None,
        "deliveryRecipient": None,
        "message": None,
        "lines": [{"offeringId": str(line.offering_id), "quantity": 1, "unit": "box"}],
    }
    expected = hashlib.sha256(
        json.dumps(
            legacy, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
    ).hexdigest()

    def fingerprint(value: CommitmentDraft) -> str:
        return value.fingerprint(
            action_id=action,
            source=CommitmentSource.ACQUISITION,
            status=CommitmentStatus.DRAFT,
        )

    assert fingerprint(draft) == expected
    assert (
        fingerprint(replace(draft, delivery_contact=DeliveryContactSnapshot(" ", " ")))
        == expected
    )
    assert (
        fingerprint(
            replace(draft, delivery_contact=DeliveryContactSnapshot(name="Test"))
        )
        != expected
    )
    assert fingerprint(replace(draft, delivery_window_id=uuid4())) != expected


def test_public_hash_preserves_absent_contact_and_tracks_changed_delivery() -> None:
    party = PublicOrderPartyDraft(None, "Test", "Customer", "test@example.invalid")
    address = DeliveryRecipientSnapshot("Test", "Testweg 1", "12345", "Teststadt")
    invoice = InvoiceRecipientSnapshot(
        "Test", "Testweg 1", "12345", "Teststadt", email="test@example.invalid"
    )
    line = CommitmentLineDraft(uuid4(), 1, OfferingUnit.BOX, 100)
    draft = PublicOrderDraft(
        party, address, invoice, (line,), None, True, True, "test-v1"
    )
    action = uuid4()

    def fingerprint(value: PublicOrderDraft) -> str:
        return value.request_hash(action_id=action, public_alias="test")

    expected = fingerprint(draft)
    assert (
        fingerprint(replace(draft, delivery_contact=DeliveryContactSnapshot()))
        == expected
    )
    assert fingerprint(replace(draft, delivery_window_id=uuid4())) != expected
    assert (
        fingerprint(
            replace(draft, delivery_contact=DeliveryContactSnapshot(phone="123"))
        )
        != expected
    )
