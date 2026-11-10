"""Payment entry, balance and cancellation invariants for immutable invoices."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from leonaid.domain.commitments import Money
from leonaid.domain.calendar import local_day
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import require_aware
from leonaid.domain.invoices import ALLOWED_INVOICE_TRANSITIONS, InvoiceStatus


def _required(
    value: str,
    *,
    code: str,
    label: str,
    maximum_length: int,
) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise DomainInvariantError(code, f"{label} darf nicht leer sein.")
    if len(normalized) > maximum_length:
        raise DomainInvariantError(
            f"{code}_too_long",
            f"{label} darf höchstens {maximum_length} Zeichen enthalten.",
        )
    return normalized


@dataclass(frozen=True, slots=True)
class InvoiceSettlementState:
    id: UUID
    action_id: UUID
    number: str
    status: InvoiceStatus
    issued_at: datetime
    # The stored invoice date; payments may not predate the printed date.
    issued_on: date
    gross: Money

    def __post_init__(self) -> None:
        require_aware(self.issued_at, "issued_at")

    def require_transition(self, target: InvoiceStatus) -> None:
        if target not in ALLOWED_INVOICE_TRANSITIONS[self.status]:
            raise DomainInvariantError(
                "invoice_status_transition_invalid",
                f"Die Rechnung darf nicht von {self.status.value} "
                f"nach {target.value} wechseln.",
            )


class SettlementStatus(StrEnum):
    """Payment state derived from the sum of the active payment entries."""

    OPEN = "open"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    OVERPAID = "overpaid"
    CANCELLED = "cancelled"


def _optional_text(
    value: str | None,
    *,
    code: str,
    label: str,
    maximum_length: int,
) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) > maximum_length:
        raise DomainInvariantError(
            f"{code}_too_long",
            f"{label} darf höchstens {maximum_length} Zeichen enthalten.",
        )
    return normalized


REVERSAL_REASON_MINIMUM = 8


@dataclass(frozen=True, slots=True)
class PaymentReversal:
    """Takes one payment entry out of the sum. The entry itself stays."""

    id: UUID
    action_id: UUID
    invoice_id: UUID
    payment_id: UUID
    reason: str
    reversed_by_user_id: UUID
    reversed_at: datetime
    reversed_by_display_name: str | None = None
    replayed: bool = False

    def __post_init__(self) -> None:
        require_aware(self.reversed_at, "reversed_at")
        object.__setattr__(
            self,
            "reason",
            _required(
                self.reason,
                code="invoice_payment_reversal_reason_required",
                label="Grund der Rückbuchung",
                maximum_length=500,
            ),
        )
        if len(self.reason) < REVERSAL_REASON_MINIMUM:
            raise DomainInvariantError(
                "invoice_payment_reversal_reason_too_short",
                "Der Grund der Rückbuchung muss mindestens acht Zeichen enthalten.",
            )


@dataclass(frozen=True, slots=True)
class PaymentRecord:
    """One received payment entry of an invoice; several may exist."""

    id: UUID
    action_id: UUID
    invoice_id: UUID
    amount: Money
    received_on: date
    reference: str
    recorded_by_user_id: UUID
    recorded_at: datetime
    recorded_by_display_name: str | None = None
    replayed: bool = False
    note: str | None = None
    reversal: PaymentReversal | None = None

    def __post_init__(self) -> None:
        require_aware(self.recorded_at, "recorded_at")
        if self.amount.amount_minor <= 0:
            raise DomainInvariantError(
                "invoice_payment_amount_invalid",
                "Der Zahlungseingang muss größer als null sein.",
            )
        object.__setattr__(
            self,
            "reference",
            _required(
                self.reference,
                code="invoice_payment_reference_required",
                label="Zahlungsreferenz",
                maximum_length=160,
            ),
        )
        object.__setattr__(
            self,
            "note",
            _optional_text(
                self.note,
                code="invoice_payment_note",
                label="Notiz",
                maximum_length=500,
            ),
        )
        if self.reversal is not None and self.reversal.payment_id != self.id:
            raise DomainInvariantError(
                "invoice_payment_reversal_mismatch",
                "Die Rückbuchung gehört zu einem anderen Zahlungseingang.",
            )

    @property
    def active(self) -> bool:
        """Counts toward the paid sum: not reversed."""

        return self.reversal is None

    @classmethod
    def record(
        cls,
        *,
        id: UUID,
        invoice: InvoiceSettlementState,
        amount: Money,
        received_on: date,
        reference: str,
        recorded_by_user_id: UUID,
        recorded_at: datetime,
        note: str | None = None,
    ) -> PaymentRecord:
        """A received amount of any positive size (ADR-0014)."""

        require_aware(recorded_at, "recorded_at")
        if invoice.status is InvoiceStatus.CANCELLED:
            raise DomainInvariantError(
                "invoice_payment_cancelled",
                "Für eine stornierte Rechnung kann keine Zahlung erfasst werden.",
            )
        if amount.currency != invoice.gross.currency:
            raise DomainInvariantError(
                "invoice_payment_currency_mismatch",
                "Die Zahlungswährung muss der Rechnungswährung entsprechen.",
            )
        if received_on < invoice.issued_on:
            raise DomainInvariantError(
                "invoice_payment_before_issue",
                "Der Zahlungseingang darf nicht vor der Rechnungsfreigabe liegen.",
            )
        if received_on > local_day(recorded_at):
            raise DomainInvariantError(
                "invoice_payment_future_date",
                "Ein zukünftiger Zahlungseingang kann nicht verbucht werden.",
            )
        return cls(
            id=id,
            action_id=invoice.action_id,
            invoice_id=invoice.id,
            amount=amount,
            received_on=received_on,
            reference=reference,
            recorded_by_user_id=recorded_by_user_id,
            recorded_at=recorded_at,
            note=note,
        )

    def reverse(
        self,
        *,
        id: UUID,
        reason: str,
        reversed_by_user_id: UUID,
        reversed_at: datetime,
    ) -> PaymentReversal:
        if self.reversal is not None:
            raise DomainInvariantError(
                "invoice_payment_already_reversed",
                "Dieser Zahlungseingang ist bereits zurückgebucht.",
            )
        return PaymentReversal(
            id=id,
            action_id=self.action_id,
            invoice_id=self.invoice_id,
            payment_id=self.id,
            reason=reason,
            reversed_by_user_id=reversed_by_user_id,
            reversed_at=reversed_at,
        )


def settlement_version(payments: Iterable[PaymentRecord]) -> int:
    """Optimistic version of an invoice's payments.

    Entries and reversals are only ever added, never changed or removed, so
    their count grows with every change: a stale form is recognised without a
    stored counter.
    """

    return sum(1 if payment.active else 2 for payment in payments)


@dataclass(frozen=True, slots=True)
class InvoiceBalance:
    """Sum of the active payment entries against the invoice total, in cents."""

    gross: Money
    paid: Money
    cancelled: bool = False

    def __post_init__(self) -> None:
        if self.paid.currency != self.gross.currency:
            raise DomainInvariantError(
                "invoice_payment_currency_mismatch",
                "Die Zahlungswährung muss der Rechnungswährung entsprechen.",
            )

    @classmethod
    def of(
        cls,
        gross: Money,
        payments: Iterable[PaymentRecord],
        *,
        cancelled: bool = False,
    ) -> InvoiceBalance:
        paid = Money(0, gross.currency)
        for payment in payments:
            if payment.active:
                paid = paid.plus(payment.amount)
        return cls(gross=gross, paid=paid, cancelled=cancelled)

    @property
    def open_amount(self) -> Money:
        """The remainder still to be received; zero once cancelled."""

        if self.cancelled:
            return Money(0, self.gross.currency)
        return Money(
            max(self.gross.amount_minor - self.paid.amount_minor, 0),
            self.gross.currency,
        )

    @property
    def overpaid_amount(self) -> Money:
        """What was received beyond the total; a refund is booked outside."""

        if self.cancelled:
            return Money(0, self.gross.currency)
        return Money(
            max(self.paid.amount_minor - self.gross.amount_minor, 0),
            self.gross.currency,
        )

    @property
    def status(self) -> SettlementStatus:
        if self.cancelled:
            return SettlementStatus.CANCELLED
        if self.paid.amount_minor > self.gross.amount_minor:
            return SettlementStatus.OVERPAID
        if self.paid.amount_minor == self.gross.amount_minor:
            return SettlementStatus.PAID
        if self.paid.amount_minor == 0:
            return SettlementStatus.OPEN
        return SettlementStatus.PARTIALLY_PAID

    def invoice_status(self, *, delivered: bool) -> InvoiceStatus:
        """The stored invoice status for this balance.

        `paid` means nothing is left to receive (also when overpaid). Below
        the total the invoice falls back to `sent` or `issued`, depending on
        whether a delivery was confirmed. A cancellation is never undone.
        """

        if self.cancelled:
            return InvoiceStatus.CANCELLED
        if self.paid.amount_minor >= self.gross.amount_minor:
            return InvoiceStatus.PAID
        return InvoiceStatus.SENT if delivered else InvoiceStatus.ISSUED


@dataclass(frozen=True, slots=True)
class InvoiceRefundSettlement:
    """The manager's note that the money of a cancelled invoice went back.

    LeonAid books no refund: the transfer happens outside. This only closes
    the reminder "Erstattung offen".
    """

    settled_on: date
    note: str | None
    settled_by_user_id: UUID
    settled_at: datetime
    settled_by_display_name: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.settled_at, "settled_at")
        object.__setattr__(
            self,
            "note",
            _optional_text(
                self.note,
                code="invoice_refund_note",
                label="Notiz zur Erstattung",
                maximum_length=500,
            ),
        )


@dataclass(frozen=True, slots=True)
class InvoiceCancellation:
    id: UUID
    action_id: UUID
    invoice_id: UUID
    original_status: InvoiceStatus
    reason: str
    requested_by_user_id: UUID
    requested_at: datetime
    requested_by_display_name: str | None = None
    replayed: bool = False
    # The cancellation invoice. None for a cancellation recorded before the
    # document existed, until a manager issues it.
    number: str | None = None
    issued_on: date | None = None
    # Active payments of the cancelled invoice; they can no longer change.
    received: Money | None = None
    refund: InvoiceRefundSettlement | None = None

    def __post_init__(self) -> None:
        require_aware(self.requested_at, "requested_at")
        if (self.number is None) != (self.issued_on is None):
            raise DomainInvariantError(
                "invoice_cancellation_document_incomplete",
                "Nummer und Datum der Stornorechnung gehören zusammen.",
            )
        if self.original_status is InvoiceStatus.CANCELLED:
            raise DomainInvariantError(
                "invoice_cancellation_original_status_invalid",
                "Ein Storno benötigt einen vorherigen Rechnungsstatus.",
            )
        object.__setattr__(
            self,
            "reason",
            _required(
                self.reason,
                code="invoice_cancellation_reason_required",
                label="Stornogrund",
                maximum_length=500,
            ),
        )
        if len(self.reason) < 8:
            raise DomainInvariantError(
                "invoice_cancellation_reason_too_short",
                "Der Stornogrund muss mindestens acht Zeichen enthalten.",
            )

    @classmethod
    def cancel(
        cls,
        *,
        id: UUID,
        invoice: InvoiceSettlementState,
        reason: str,
        requested_by_user_id: UUID,
        requested_at: datetime,
    ) -> InvoiceCancellation:
        require_aware(requested_at, "requested_at")
        invoice.require_transition(InvoiceStatus.CANCELLED)
        return cls(
            id=id,
            action_id=invoice.action_id,
            invoice_id=invoice.id,
            original_status=invoice.status,
            reason=reason,
            requested_by_user_id=requested_by_user_id,
            requested_at=requested_at,
        )

    @property
    def has_document(self) -> bool:
        return self.number is not None

    @property
    def refund_open(self) -> bool:
        """Money was received and no manager recorded that it went back."""

        return (
            self.received is not None
            and self.received.amount_minor > 0
            and self.refund is None
        )

    def settle_refund(
        self,
        *,
        settled_on: date,
        note: str | None,
        settled_by_user_id: UUID,
        settled_at: datetime,
    ) -> InvoiceRefundSettlement:
        require_aware(settled_at, "settled_at")
        if self.refund is not None:
            raise DomainInvariantError(
                "invoice_refund_already_settled",
                "Die Erstattung ist bereits als erledigt vermerkt.",
            )
        if self.received is None or self.received.amount_minor <= 0:
            raise DomainInvariantError(
                "invoice_refund_not_due",
                "Für diese Rechnung ist kein Zahlungseingang erfasst; es gibt "
                "nichts zu erstatten.",
            )
        if settled_on < local_day(self.requested_at):
            raise DomainInvariantError(
                "invoice_refund_before_cancellation",
                "Die Erstattung kann nicht vor dem Storno liegen.",
            )
        if settled_on > local_day(settled_at):
            raise DomainInvariantError(
                "invoice_refund_future_date",
                "Eine zukünftige Erstattung kann nicht vermerkt werden.",
            )
        return InvoiceRefundSettlement(
            settled_on=settled_on,
            note=note,
            settled_by_user_id=settled_by_user_id,
            settled_at=settled_at,
        )
