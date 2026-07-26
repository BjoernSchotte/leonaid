from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from leonaid.domain.action_templates import OfferingStatus, OfferingUnit
from leonaid.domain.commitments import (
    BuyerSnapshot,
    Commitment,
    CommitmentLine,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
    InvoiceRecipientSnapshot,
    Money,
    Offering,
)
from leonaid.domain.errors import DomainInvariantError

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
OFFERING_ID = UUID("70000000-0000-4000-8000-000000000001")
COMPANY_ID = UUID("40000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


def krapfenbox() -> Offering:
    return Offering(
        id=OFFERING_ID,
        action_id=ACTION_ID,
        code="krapfenbox-24",
        name="Krapfenbox",
        status=OfferingStatus.ACTIVE,
        pricing_unit=OfferingUnit.BOX,
        allowed_quantity_units=frozenset({OfferingUnit.BOX}),
        pieces_per_unit=24,
        unit_price=Money(3_600, "EUR"),
        available_from=NOW - timedelta(days=1),
        available_until=NOW + timedelta(days=1),
    )


def buyer() -> BuyerSnapshot:
    return BuyerSnapshot(
        party_kind=CommitmentPartyKind.COMPANY,
        twenty_id=COMPANY_ID,
        display_name="Musterwerk GmbH",
        email="einkauf@musterwerk.invalid",
    )


def recipient() -> InvoiceRecipientSnapshot:
    return InvoiceRecipientSnapshot(
        recipient_name="Musterwerk Rechnungseingang",
        street_line_1="Zahlweg 9",
        postal_code="86150",
        city="Augsburg",
        email="rechnung@musterwerk.invalid",
    )


def test_money_rounds_half_up_and_keeps_minor_units_exact() -> None:
    assert Money.from_major(Decimal("36.004"), "EUR").amount_minor == 3_600
    assert Money.from_major(Decimal("36.005"), "EUR").amount_minor == 3_601
    assert Money.from_major(Decimal("0.005"), "EUR").amount_minor == 1
    assert Money(3_600, "EUR").multiply(3) == Money(10_800, "EUR")

    with pytest.raises(DomainInvariantError) as mismatch:
        Money(100, "EUR").plus(Money(100, "USD"))
    assert mismatch.value.code == "money_currency_mismatch"

    with pytest.raises(DomainInvariantError) as non_integer:
        Money(cast(int, 1.5), "EUR")
    assert non_integer.value.code == "money_amount_invalid"


def test_krapfenbox_is_traceable_as_boxes_pieces_and_server_total() -> None:
    line = CommitmentLine.price_from(
        krapfenbox(),
        quantity=2,
        unit=OfferingUnit.BOX,
        evaluated_at=NOW,
    )

    assert line.box_count == 2
    assert line.piece_count == 48
    assert line.unit_price == Money(3_600, "EUR")
    assert line.line_total == Money(7_200, "EUR")


@pytest.mark.parametrize(
    ("offering", "unit", "code"),
    (
        (
            replace(krapfenbox(), status=OfferingStatus.INACTIVE),
            OfferingUnit.BOX,
            "offering_not_available",
        ),
        (
            replace(krapfenbox(), available_until=NOW),
            OfferingUnit.BOX,
            "offering_not_available",
        ),
        (
            krapfenbox(),
            OfferingUnit.PIECE,
            "offering_quantity_unit_not_allowed",
        ),
    ),
)
def test_offering_status_period_and_allowed_units_are_enforced(
    offering: Offering,
    unit: OfferingUnit,
    code: str,
) -> None:
    with pytest.raises(DomainInvariantError) as captured:
        CommitmentLine.price_from(
            offering,
            quantity=1,
            unit=unit,
            evaluated_at=NOW,
        )
    assert captured.value.code == code


@pytest.mark.parametrize("source", tuple(CommitmentSource))
def test_commitment_sources_keep_buyer_recipient_and_lines_separate(
    source: CommitmentSource,
) -> None:
    line = CommitmentLine.price_from(
        krapfenbox(),
        quantity=3,
        unit=OfferingUnit.BOX,
        evaluated_at=NOW,
    )
    commitment = Commitment(
        id=UUID("80000000-0000-4000-8000-000000000099"),
        action_id=ACTION_ID,
        source=source,
        status=CommitmentStatus.REVIEW_READY,
        buyer=buyer(),
        invoice_recipient=recipient(),
        lines=(line,),
        total=Money(10_800, "EUR"),
    )

    assert commitment.buyer.display_name == "Musterwerk GmbH"
    assert commitment.invoice_recipient is not None
    assert commitment.invoice_recipient.recipient_name == "Musterwerk Rechnungseingang"
    assert commitment.lines[0].description_snapshot == "Krapfenbox"
    assert commitment.total_boxes == 3
    assert commitment.total_pieces == 72


def test_commitment_rejects_a_tampered_total() -> None:
    line = CommitmentLine.price_from(
        krapfenbox(),
        quantity=1,
        unit=OfferingUnit.BOX,
        evaluated_at=NOW,
    )
    with pytest.raises(DomainInvariantError) as captured:
        Commitment(
            id=UUID("80000000-0000-4000-8000-000000000098"),
            action_id=ACTION_ID,
            source=CommitmentSource.ACQUISITION,
            status=CommitmentStatus.DRAFT,
            buyer=buyer(),
            invoice_recipient=None,
            lines=(line,),
            total=Money(1, "EUR"),
        )
    assert captured.value.code == "commitment_total_invalid"
