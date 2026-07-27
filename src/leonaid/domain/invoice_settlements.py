"""Full-payment and cancellation invariants for immutable invoices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from leonaid.domain.commitments import Money
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


@dataclass(frozen=True, slots=True)
class PaymentRecord:
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

    @classmethod
    def record_full(
        cls,
        *,
        id: UUID,
        invoice: InvoiceSettlementState,
        amount: Money,
        received_on: date,
        reference: str,
        recorded_by_user_id: UUID,
        recorded_at: datetime,
    ) -> PaymentRecord:
        require_aware(recorded_at, "recorded_at")
        invoice.require_transition(InvoiceStatus.PAID)
        if amount.currency != invoice.gross.currency:
            raise DomainInvariantError(
                "invoice_payment_currency_mismatch",
                "Die Zahlungswährung muss der Rechnungswährung entsprechen.",
            )
        if amount.amount_minor != invoice.gross.amount_minor:
            raise DomainInvariantError(
                "invoice_payment_full_amount_required",
                "Im PoC kann nur der vollständige Rechnungsbetrag verbucht werden.",
            )
        if received_on < invoice.issued_at.date():
            raise DomainInvariantError(
                "invoice_payment_before_issue",
                "Der Zahlungseingang darf nicht vor der Rechnungsfreigabe liegen.",
            )
        if received_on > recorded_at.date():
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

    def __post_init__(self) -> None:
        require_aware(self.requested_at, "requested_at")
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
