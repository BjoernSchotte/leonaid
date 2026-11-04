from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date
from uuid import UUID

import pytest

from leonaid.domain.commitments import (
    Commitment,
    CommitmentStatus,
    Money,
)
from leonaid.domain.errors import DomainInvariantError
from tests.unit.invoice_builders import (
    ADMIN_ID,
    INVOICE_ID,
    ISSUED_AT,
    commitment,
    profile,
)
from leonaid.domain.invoices import (
    Invoice,
    InvoiceProfile,
    InvoiceStatus,
    TaxTreatment,
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
    assert invoice.payment_details.payload() == {
        "accountHolder": "Lions Hilfswerk LeonAid Golden e.V.",
        "iban": "DE89370400440532013000",
        "bic": "COBADEFFXXX",
    }
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


def test_invoice_profile_without_payment_details_is_fail_closed() -> None:
    unconfigured = replace(profile(), payment_details=None)

    assert not unconfigured.ready_to_issue
    with pytest.raises(DomainInvariantError) as error:
        issue(invoice_profile=unconfigured)

    assert error.value.code == "invoice_profile_not_confirmed"


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
