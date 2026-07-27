from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import (
    BuyerSnapshot,
    Commitment,
    CommitmentLine,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
    InvoiceRecipientSnapshot,
    Money,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.invoices import (
    Invoice,
    InvoiceIssuerSnapshot,
    InvoiceProfile,
    InvoiceStatus,
    TaxTreatment,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
COMMITMENT_ID = UUID("80000000-0000-4000-8000-000000000002")
INVOICE_ID = UUID("90000000-0000-4000-8000-000000000004")
PROFILE_ID = UUID("96000000-0000-4000-8000-000000000001")
ADMIN_ID = UUID("10000000-0000-4000-8000-000000000002")
ISSUED_AT = datetime(2026, 10, 12, 10, tzinfo=timezone.utc)


def commitment(
    *,
    status: CommitmentStatus = CommitmentStatus.REVIEW_READY,
) -> Commitment:
    line = CommitmentLine(
        id=UUID("81000000-0000-4000-8000-000000000001"),
        offering_id=UUID("70000000-0000-4000-8000-000000000001"),
        description_snapshot="Krapfenbox",
        quantity=3,
        unit_snapshot=OfferingUnit.BOX,
        pieces_per_unit_snapshot=24,
        unit_price=Money(3_600, "EUR"),
        line_total=Money(10_800, "EUR"),
    )
    return Commitment(
        id=COMMITMENT_ID,
        action_id=ACTION_ID,
        source=CommitmentSource.ACQUISITION,
        status=status,
        buyer=BuyerSnapshot(
            party_kind=CommitmentPartyKind.COMPANY,
            twenty_id=UUID("40000000-0000-4000-8000-000000000002"),
            display_name="Bäckerei Sonnenseite KG",
            email="einkauf@sonnenseite.invalid",
        ),
        invoice_recipient=InvoiceRecipientSnapshot(
            recipient_name="Bäckerei Sonnenseite KG",
            street_line_1="Sonnenstraße 2",
            postal_code="10243",
            city="Beispielstadt",
            country_code="DE",
            email="rechnung@sonnenseite.invalid",
        ),
        lines=(line,),
        total=Money(10_800, "EUR"),
    )


def profile(
    *,
    tax_treatment: TaxTreatment = TaxTreatment.SMALL_BUSINESS,
    tax_rate_basis_points: int = 0,
    confirmed_at: datetime | None = ISSUED_AT - timedelta(days=30),
) -> InvoiceProfile:
    return InvoiceProfile(
        id=PROFILE_ID,
        action_id=ACTION_ID,
        issuer=InvoiceIssuerSnapshot(
            legal_name="Lions Hilfswerk LeonAid Golden e.V.",
            street_line_1="Clubweg 1",
            postal_code="86150",
            city="Augsburg",
            country_code="DE",
            tax_identifier="103/999/99999",
            email="finanzen@leonaid.invalid",
        ),
        tax_treatment=tax_treatment,
        tax_rate_basis_points=tax_rate_basis_points,
        tax_note=(
            "Umsatzsteuer 19 %."
            if tax_treatment is TaxTreatment.STANDARD_VAT
            else "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet."
        ),
        number_prefix="KT26-",
        next_number=4,
        number_width=4,
        payment_terms_days=14,
        confirmed_at=confirmed_at,
    )


def issue(
    *,
    source: Commitment | None = None,
    invoice_profile: InvoiceProfile | None = None,
) -> Invoice:
    return Invoice.issue(
        id=INVOICE_ID,
        number="KT26-0004",
        commitment=source or commitment(),
        profile=invoice_profile or profile(),
        approved_by_user_id=ADMIN_ID,
        issued_at=ISSUED_AT,
        service_on=date(2026, 11, 15),
    )


def test_small_business_invoice_keeps_exact_amount_and_due_date() -> None:
    invoice = issue()

    assert invoice.status is InvoiceStatus.ISSUED
    assert invoice.net == Money(10_800, "EUR")
    assert invoice.tax == Money(0, "EUR")
    assert invoice.gross == Money(10_800, "EUR")
    assert invoice.due_on == date(2026, 10, 26)
    assert invoice.payment_reference == "KT26-0004"
    assert invoice.lines[0].payload() == {
        "description": "Krapfenbox",
        "quantity": 3,
        "unit": "box",
        "unitPriceGrossMinor": 3_600,
        "taxRateBasisPoints": 0,
        "netMinor": 10_800,
        "taxMinor": 0,
        "grossMinor": 10_800,
        "currency": "EUR",
    }


def test_standard_vat_is_derived_from_gross_with_half_up_minor_units() -> None:
    invoice = issue(
        invoice_profile=profile(
            tax_treatment=TaxTreatment.STANDARD_VAT,
            tax_rate_basis_points=1_900,
        )
    )

    assert invoice.net == Money(9_076, "EUR")
    assert invoice.tax == Money(1_724, "EUR")
    assert invoice.gross == Money(10_800, "EUR")
    assert invoice.lines[0].net.plus(invoice.lines[0].tax) == invoice.lines[0].gross


def test_issued_snapshot_is_frozen_and_independent_from_later_source_changes() -> None:
    original = commitment()
    invoice = issue(source=original)
    changed = replace(
        original,
        invoice_recipient=replace(
            original.invoice_recipient,
            street_line_1="Neue CRM-Straße 99",
        )
        if original.invoice_recipient is not None
        else None,
    )

    assert changed.invoice_recipient is not None
    assert changed.invoice_recipient.street_line_1 == "Neue CRM-Straße 99"
    assert invoice.recipient.street_line_1 == "Sonnenstraße 2"
    with pytest.raises(FrozenInstanceError):
        invoice.number = "KT26-9999"


def test_status_automaton_never_reopens_or_overwrites_a_cancelled_invoice() -> None:
    issued = issue()
    sent = issued.transition_to(InvoiceStatus.SENT)
    paid = sent.transition_to(InvoiceStatus.PAID)
    cancelled = paid.transition_to(InvoiceStatus.CANCELLED)

    assert cancelled.number == issued.number
    assert cancelled.recipient == issued.recipient
    with pytest.raises(DomainInvariantError) as reopen:
        cancelled.transition_to(InvoiceStatus.ISSUED)
    assert reopen.value.code == "invoice_status_transition_invalid"


@pytest.mark.parametrize(
    ("source", "invoice_profile", "code"),
    (
        (
            commitment(status=CommitmentStatus.DRAFT),
            profile(),
            "invoice_commitment_not_review_ready",
        ),
        (
            replace(commitment(), invoice_recipient=None),
            profile(),
            "invoice_recipient_required",
        ),
        (
            commitment(),
            profile(confirmed_at=None),
            "invoice_profile_not_confirmed",
        ),
        (
            commitment(),
            replace(
                profile(),
                action_id=UUID("20000000-0000-4000-8000-000000000003"),
            ),
            "invoice_profile_action_mismatch",
        ),
    ),
)
def test_issue_rejects_unapproved_or_incomplete_source_state(
    source: Commitment,
    invoice_profile: InvoiceProfile,
    code: str,
) -> None:
    with pytest.raises(DomainInvariantError) as captured:
        issue(source=source, invoice_profile=invoice_profile)
    assert captured.value.code == code
