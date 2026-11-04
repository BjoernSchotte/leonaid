"""The manual "ausgebucht" switch: domain rule, public pre-check, request hashes."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timezone
from uuid import UUID, uuid4

import pytest

from leonaid.application.commitments import (
    CommitmentCompletion,
    CommitmentDraft,
    CommitmentLineDraft,
)
from leonaid.application.delivery import require_publicly_bookable
from leonaid.application.delivery_completion import DeliveryCompletionDraft
from leonaid.application.errors import Conflict
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import (
    BuyerSnapshot,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
    InvoiceRecipientSnapshot,
)
from leonaid.domain.delivery import DeliveryConfiguration, DeliveryWindow
from leonaid.domain.errors import DomainInvariantError
from leonaid.entrypoints.fastapi.schemas import (
    CreateCommitmentRequest,
    DeliveryWindowRequest,
    DeliveryWindowResponse,
)

ACTION = UUID("20000000-0000-4000-8000-000000000001")


def window(**changes: object) -> DeliveryWindow:
    value = DeliveryWindow(uuid4(), ACTION, date(2037, 12, 4), time(8), time(10))
    return replace(value, **changes)  # type: ignore[arg-type]


def test_a_retired_window_is_never_fully_booked() -> None:
    assert window(fully_booked=True).fully_booked
    with pytest.raises(DomainInvariantError) as error:
        window(retired=True, fully_booked=True)
    assert error.value.code == "delivery_window_full_retired"


def test_public_pre_check_refuses_only_the_full_window() -> None:
    full, open_ = (
        window(fully_booked=True),
        window(starts_at=time(10), ends_at=time(12)),
    )
    configuration = DeliveryConfiguration(ACTION, True, windows=(full, open_))
    require_publicly_bookable(configuration, None)
    require_publicly_bookable(configuration, open_.id)
    with pytest.raises(Conflict) as error:
        require_publicly_bookable(configuration, full.id)
    assert error.value.code == "delivery_window_full"
    # Admin and acquisition capture still select it.
    assert (
        configuration.select(full.id, now=datetime(2037, 1, 1, tzinfo=timezone.utc))
        == full
    )


def test_the_confirmation_stays_out_of_every_request_hash() -> None:
    buyer = BuyerSnapshot(CommitmentPartyKind.PERSON, uuid4(), "Test")
    line = CommitmentLineDraft(uuid4(), 1, OfferingUnit.BOX)
    draft = CommitmentDraft(buyer, None, (line,), delivery_window_id=uuid4())
    hashes = {
        value.fingerprint(
            action_id=ACTION,
            source=CommitmentSource.ADMIN,
            status=CommitmentStatus.REVIEW_READY,
        )
        for value in (draft, replace(draft, allow_full_window=True))
    }
    assert len(hashes) == 1
    completion = CommitmentCompletion(delivery_window_id=uuid4())
    ids = {"action_id": ACTION, "commitment_id": uuid4(), "actor_user_id": uuid4()}
    assert completion.fingerprint(**ids) == replace(
        completion, allow_full_window=True
    ).fingerprint(**ids)
    manager = DeliveryCompletionDraft(
        "0" * 64,
        InvoiceRecipientSnapshot("Billing", "Road 1", "12345", "Test"),
        delivery_window_id=uuid4(),
    )
    assert manager.fingerprint(**ids) == replace(
        manager, allow_full_window=True
    ).fingerprint(**ids)


def test_wire_shape() -> None:
    full = window(fully_booked=True)
    assert DeliveryWindowResponse.model_validate(full).model_dump(by_alias=True)[
        "fullyBooked"
    ]
    # A loaded window may be sent back as it is; the switch has its own
    # command, so the form never builds a window that is full.
    echoed = DeliveryWindowRequest.model_validate(
        {
            "deliveryOn": "2037-12-04",
            "startsAt": "08:00",
            "endsAt": "10:00",
            "fullyBooked": True,
        }
    )
    assert echoed.fully_booked is True
    request = CreateCommitmentRequest.model_validate(
        {
            "source": "admin",
            "buyer": {
                "partyKind": "person",
                "twentyId": str(uuid4()),
                "displayName": "T",
            },
            "lines": [{"offeringId": str(uuid4()), "quantity": 1, "unit": "box"}],
        }
    )
    assert request.allow_full_window is False
