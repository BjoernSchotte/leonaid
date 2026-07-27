from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import pytest

from leonaid.domain.commitments import Money
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.invoice_settlements import (
    InvoiceCancellation,
    InvoiceSettlementState,
    PaymentRecord,
)
from leonaid.domain.invoices import InvoiceStatus

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
INVOICE_ID = UUID("90000000-0000-4000-8000-000000000001")
PAYMENT_ID = UUID("97000000-0000-4000-8000-000000000010")
CANCELLATION_ID = UUID("98000000-0000-4000-8000-000000000010")
ADMIN_ID = UUID("10000000-0000-4000-8000-000000000002")
ISSUED_AT = datetime(2026, 6, 30, 14, tzinfo=timezone.utc)
RECORDED_AT = datetime(2026, 7, 12, 9, tzinfo=timezone.utc)


def invoice_state(
    status: InvoiceStatus = InvoiceStatus.SENT,
) -> InvoiceSettlementState:
    return InvoiceSettlementState(
        id=INVOICE_ID,
        action_id=ACTION_ID,
        number="KT26-0001",
        status=status,
        issued_at=ISSUED_AT,
        gross=Money(36_000, "EUR"),
    )


def test_exact_full_payment_keeps_date_amount_and_reference() -> None:
    payment = PaymentRecord.record_full(
        id=PAYMENT_ID,
        invoice=invoice_state(),
        amount=Money(36_000, "EUR"),
        received_on=date(2026, 7, 10),
        reference="  KT26-0001   Bankumsatz  ",
        recorded_by_user_id=ADMIN_ID,
        recorded_at=RECORDED_AT,
    )

    assert payment.amount == Money(36_000, "EUR")
    assert payment.received_on == date(2026, 7, 10)
    assert payment.reference == "KT26-0001 Bankumsatz"


@pytest.mark.parametrize(
    ("amount", "code"),
    (
        (Money(35_999, "EUR"), "invoice_payment_full_amount_required"),
        (Money(36_001, "EUR"), "invoice_payment_full_amount_required"),
        (Money(36_000, "USD"), "invoice_payment_currency_mismatch"),
    ),
)
def test_partial_overpayment_and_wrong_currency_are_rejected(
    amount: Money,
    code: str,
) -> None:
    with pytest.raises(DomainInvariantError) as captured:
        PaymentRecord.record_full(
            id=PAYMENT_ID,
            invoice=invoice_state(),
            amount=amount,
            received_on=date(2026, 7, 10),
            reference="KT26-0001",
            recorded_by_user_id=ADMIN_ID,
            recorded_at=RECORDED_AT,
        )

    assert captured.value.code == code


@pytest.mark.parametrize(
    ("received_on", "code"),
    (
        (date(2026, 6, 29), "invoice_payment_before_issue"),
        (date(2026, 7, 13), "invoice_payment_future_date"),
    ),
)
def test_payment_date_must_be_between_issue_and_recording(
    received_on: date,
    code: str,
) -> None:
    with pytest.raises(DomainInvariantError) as captured:
        PaymentRecord.record_full(
            id=PAYMENT_ID,
            invoice=invoice_state(),
            amount=Money(36_000, "EUR"),
            received_on=received_on,
            reference="KT26-0001",
            recorded_by_user_id=ADMIN_ID,
            recorded_at=RECORDED_AT,
        )

    assert captured.value.code == code


@pytest.mark.parametrize(
    "status",
    (InvoiceStatus.PAID, InvoiceStatus.CANCELLED),
)
def test_payment_never_reopens_terminal_invoice(status: InvoiceStatus) -> None:
    with pytest.raises(DomainInvariantError) as captured:
        PaymentRecord.record_full(
            id=PAYMENT_ID,
            invoice=invoice_state(status),
            amount=Money(36_000, "EUR"),
            received_on=date(2026, 7, 10),
            reference="KT26-0001",
            recorded_by_user_id=ADMIN_ID,
            recorded_at=RECORDED_AT,
        )

    assert captured.value.code == "invoice_status_transition_invalid"


@pytest.mark.parametrize(
    "status",
    (InvoiceStatus.ISSUED, InvoiceStatus.SENT, InvoiceStatus.PAID),
)
def test_storno_preserves_original_status_and_reason(
    status: InvoiceStatus,
) -> None:
    cancellation = InvoiceCancellation.cancel(
        id=CANCELLATION_ID,
        invoice=invoice_state(status),
        reason="Empfängeranschrift muss fachlich korrigiert werden.",
        requested_by_user_id=ADMIN_ID,
        requested_at=RECORDED_AT,
    )

    assert cancellation.original_status is status
    assert cancellation.reason == "Empfängeranschrift muss fachlich korrigiert werden."


def test_cancelled_invoice_cannot_be_cancelled_again() -> None:
    with pytest.raises(DomainInvariantError) as captured:
        InvoiceCancellation.cancel(
            id=CANCELLATION_ID,
            invoice=invoice_state(InvoiceStatus.CANCELLED),
            reason="Noch einmal stornieren.",
            requested_by_user_id=ADMIN_ID,
            requested_at=RECORDED_AT,
        )

    assert captured.value.code == "invoice_status_transition_invalid"
