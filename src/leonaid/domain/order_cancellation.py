"""Invariants of a reasoned, final order cancellation.

An order may be cancelled until it is delivered. The cancellation is its own
durable record: the order keeps buyer, lines and prices and only changes its
status. An issued, unpaid invoice of the order is cancelled with it under
ADR-0009 (status ``cancelled``, number, snapshot and PDF unchanged). A
recorded payment blocks the cancellation: LeonAid books no refunds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from leonaid.domain.commitments import CommitmentStatus
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import require_aware
from leonaid.domain.invoices import InvoiceStatus

CANCELLABLE_ORDER_STATUSES = frozenset(
    {
        CommitmentStatus.DRAFT,
        CommitmentStatus.REVIEW_READY,
        CommitmentStatus.CONFIRMED,
        CommitmentStatus.INVOICED,
    }
)
# The invoice cancellation (ADR-0009) shares the reason; its lower bound
# applies to the order too, so one reason always fits both records.
REASON_MIN_LENGTH = 8
REASON_MAX_LENGTH = 500
NOTE_MAX_LENGTH = 1000


@dataclass(frozen=True, slots=True)
class CancellationBlock:
    """Why an existing order cannot be cancelled in its current state."""

    code: str
    message: str


def normalize_reason(value: str) -> str:
    reason = " ".join(value.split())
    if len(reason) < REASON_MIN_LENGTH:
        raise DomainInvariantError(
            "commitment_cancellation_reason_too_short",
            f"Der Stornogrund muss mindestens {REASON_MIN_LENGTH} Zeichen enthalten.",
        )
    if len(reason) > REASON_MAX_LENGTH:
        raise DomainInvariantError(
            "commitment_cancellation_reason_too_long",
            f"Der Stornogrund darf höchstens {REASON_MAX_LENGTH} Zeichen enthalten.",
        )
    return reason


def normalize_note(value: str | None) -> str | None:
    """Keeps line breaks of the note, trims it; blank means no note."""

    if value is None:
        return None
    note = "\n".join(line.rstrip() for line in value.strip().splitlines()).strip()
    if not note:
        return None
    if len(note) > NOTE_MAX_LENGTH:
        raise DomainInvariantError(
            "commitment_cancellation_note_too_long",
            f"Die Notiz darf höchstens {NOTE_MAX_LENGTH} Zeichen enthalten.",
        )
    return note


@dataclass(frozen=True, slots=True)
class OrderInvoiceState:
    """The order's invoice as far as the cancellation needs to know it."""

    id: UUID
    number: str
    status: InvoiceStatus
    payment_recorded: bool

    @property
    def needs_cancellation(self) -> bool:
        return self.status in {InvoiceStatus.ISSUED, InvoiceStatus.SENT}


def cancellation_block(
    *,
    status: CommitmentStatus,
    delivered: bool,
    invoice: OrderInvoiceState | None,
) -> CancellationBlock | None:
    """The reason an order cannot be cancelled, most final first; else None."""

    if status is CommitmentStatus.CANCELLED:
        return CancellationBlock(
            "commitment_already_cancelled",
            "Diese Bestellung ist bereits storniert.",
        )
    if status not in CANCELLABLE_ORDER_STATUSES:
        return CancellationBlock(
            "commitment_cancellation_status_invalid",
            "Diese Bestellung kann in ihrem Status nicht storniert werden.",
        )
    if delivered:
        return CancellationBlock(
            "commitment_cancellation_delivered",
            "Die Bestellung ist bereits geliefert und kann nicht mehr storniert "
            "werden.",
        )
    if invoice is not None and (
        invoice.payment_recorded or invoice.status is InvoiceStatus.PAID
    ):
        return CancellationBlock(
            "commitment_cancellation_payment_recorded",
            f"Zur Rechnung {invoice.number} ist bereits eine Zahlung erfasst. "
            "Bitte die Zahlung erst zurücknehmen, dann die Bestellung stornieren.",
        )
    return None


@dataclass(frozen=True, slots=True)
class OrderCancellation:
    id: UUID
    action_id: UUID
    commitment_id: UUID
    previous_status: CommitmentStatus
    reason: str
    note: str | None
    requested_by_user_id: UUID
    requested_at: datetime
    invoice_cancellation_id: UUID | None = None
    invoice_number: str | None = None
    requested_by_display_name: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.requested_at, "requested_at")
        if self.previous_status not in CANCELLABLE_ORDER_STATUSES:
            raise DomainInvariantError(
                "commitment_cancellation_previous_status_invalid",
                "Ein Storno benötigt einen stornierbaren vorherigen Status.",
            )
        object.__setattr__(self, "reason", normalize_reason(self.reason))
        object.__setattr__(self, "note", normalize_note(self.note))
