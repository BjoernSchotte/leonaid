"""The cancellation invoice ("Stornorechnung") of a cancelled invoice.

It is a document of its own with a number of the invoice series (ADR-0015).
It copies issuer, recipient, tax case and lines of the invoice it cancels and
names that invoice's number and date. The invoice itself is not touched
(ADR-0009).

Money and quantities are non-negative everywhere in LeonAid, by type and by
database check. This type keeps the original amounts and is the one place
that knows the cancellation invoice shows them with a minus sign:
``printed_minor``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from leonaid.domain.calendar import local_day
from leonaid.domain.commitments import InvoiceRecipientSnapshot, Money
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import require_aware
from leonaid.domain.invoices import (
    INVOICE_NUMBER,
    Invoice,
    InvoiceIssuerSnapshot,
    InvoiceLineSnapshot,
    TaxTreatment,
)

INVOICE_CANCELLATION_DOCUMENT_SCHEMA_VERSION = 1


def _object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DomainInvariantError(
            "invoice_cancellation_document_payload_invalid",
            f"{label} der Stornorechnung ist ungültig.",
        )
    return value


def _integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DomainInvariantError(
            "invoice_cancellation_document_payload_invalid",
            f"{label} der Stornorechnung muss eine Ganzzahl sein.",
        )
    return value


@dataclass(frozen=True, slots=True)
class InvoiceCancellationDocument:
    cancellation_id: UUID
    invoice_id: UUID
    number: str
    issued_at: datetime
    issued_on: date
    original_number: str
    original_issued_on: date
    issuer: InvoiceIssuerSnapshot
    recipient: InvoiceRecipientSnapshot
    lines: tuple[InvoiceLineSnapshot, ...]
    tax_treatment: TaxTreatment
    tax_note: str
    net: Money
    tax: Money
    gross: Money
    # What had been received for the invoice when it was cancelled.
    received: Money

    def __post_init__(self) -> None:
        require_aware(self.issued_at, "issued_at")
        for number in (self.number, self.original_number):
            if not INVOICE_NUMBER.fullmatch(number):
                raise DomainInvariantError(
                    "invoice_cancellation_number_invalid",
                    "Die Nummer der Stornorechnung besitzt ein ungültiges Format.",
                )
        if self.number == self.original_number:
            raise DomainInvariantError(
                "invoice_cancellation_number_reused",
                "Die Stornorechnung benötigt eine eigene Nummer.",
            )
        if self.issued_on < self.original_issued_on:
            raise DomainInvariantError(
                "invoice_cancellation_date_invalid",
                "Die Stornorechnung darf nicht vor der Rechnung datiert sein.",
            )
        if not self.lines:
            raise DomainInvariantError(
                "invoice_cancellation_lines_required",
                "Eine Stornorechnung benötigt mindestens eine Position.",
            )
        currency = self.gross.currency
        net = sum(line.net.amount_minor for line in self.lines)
        tax = sum(line.tax.amount_minor for line in self.lines)
        gross = sum(line.gross.amount_minor for line in self.lines)
        if (
            Money(net, currency) != self.net
            or Money(tax, currency) != self.tax
            or Money(gross, currency) != self.gross
            or self.net.plus(self.tax) != self.gross
        ):
            raise DomainInvariantError(
                "invoice_cancellation_totals_invalid",
                "Die Beträge der Stornorechnung stimmen nicht mit den Positionen überein.",
            )
        if self.received.currency != currency:
            raise DomainInvariantError(
                "invoice_cancellation_currency_mismatch",
                "Der erhaltene Betrag muss die Rechnungswährung haben.",
            )

    @staticmethod
    def printed_minor(amount: Money) -> int:
        """The amount as the cancellation invoice shows it: negated.

        The stored amount stays the invoice's, non-negative. Zero stays zero.
        """

        return -amount.amount_minor

    @property
    def refund_due(self) -> bool:
        """Money was received for the cancelled invoice and goes back."""

        return self.received.amount_minor > 0

    @classmethod
    def issue(
        cls,
        *,
        cancellation_id: UUID,
        number: str,
        invoice: Invoice,
        received: Money,
        issued_at: datetime,
    ) -> InvoiceCancellationDocument:
        """Full cancellation only: every line of the invoice, unchanged."""

        require_aware(issued_at, "issued_at")
        return cls(
            cancellation_id=cancellation_id,
            invoice_id=invoice.id,
            number=number,
            issued_at=issued_at,
            # The club's day of the cancellation, fixed for the printed date.
            issued_on=max(local_day(issued_at), invoice.issued_on),
            original_number=invoice.number,
            original_issued_on=invoice.issued_on,
            issuer=invoice.issuer,
            recipient=invoice.recipient,
            lines=invoice.lines,
            tax_treatment=invoice.tax_treatment,
            tax_note=invoice.tax_note,
            net=invoice.net,
            tax=invoice.tax,
            gross=invoice.gross,
            received=received,
        )

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": INVOICE_CANCELLATION_DOCUMENT_SCHEMA_VERSION,
            "cancellationId": str(self.cancellation_id),
            "invoiceId": str(self.invoice_id),
            "number": self.number,
            "issuedAt": self.issued_at.isoformat(),
            "issuedOn": self.issued_on.isoformat(),
            "originalNumber": self.original_number,
            "originalIssuedOn": self.original_issued_on.isoformat(),
            "issuer": self.issuer.payload(),
            "recipient": self.recipient.payload(),
            "lines": [line.payload() for line in self.lines],
            "taxTreatment": self.tax_treatment.value,
            "taxNote": self.tax_note,
            "totals": {
                "netMinor": self.net.amount_minor,
                "taxMinor": self.tax.amount_minor,
                "grossMinor": self.gross.amount_minor,
                "currency": self.gross.currency,
            },
            "receivedMinor": self.received.amount_minor,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> InvoiceCancellationDocument:
        version = _integer(payload.get("schemaVersion"), label="Schemaversion")
        if version != INVOICE_CANCELLATION_DOCUMENT_SCHEMA_VERSION:
            raise DomainInvariantError(
                "invoice_cancellation_document_schema_unsupported",
                f"Dokumentschema {version} wird nicht unterstützt.",
            )
        totals = _object(payload.get("totals"), label="Summen")
        currency = str(totals.get("currency"))
        lines = payload.get("lines")
        if not isinstance(lines, list):
            raise DomainInvariantError(
                "invoice_cancellation_document_payload_invalid",
                "Positionen der Stornorechnung sind ungültig.",
            )
        return cls(
            cancellation_id=UUID(str(payload.get("cancellationId"))),
            invoice_id=UUID(str(payload.get("invoiceId"))),
            number=str(payload.get("number")),
            issued_at=datetime.fromisoformat(str(payload.get("issuedAt"))),
            issued_on=date.fromisoformat(str(payload.get("issuedOn"))),
            original_number=str(payload.get("originalNumber")),
            original_issued_on=date.fromisoformat(str(payload.get("originalIssuedOn"))),
            issuer=InvoiceIssuerSnapshot.from_payload(
                _object(payload.get("issuer"), label="Rechnungsaussteller")
            ),
            recipient=InvoiceRecipientSnapshot.from_payload(
                _object(payload.get("recipient"), label="Rechnungsempfänger")
            ),
            lines=tuple(
                InvoiceLineSnapshot.from_payload(_object(item, label="Position"))
                for item in lines
            ),
            tax_treatment=TaxTreatment(str(payload.get("taxTreatment"))),
            tax_note=str(payload.get("taxNote")),
            net=Money(_integer(totals.get("netMinor"), label="Nettosumme"), currency),
            tax=Money(_integer(totals.get("taxMinor"), label="Steuersumme"), currency),
            gross=Money(
                _integer(totals.get("grossMinor"), label="Bruttosumme"), currency
            ),
            received=Money(
                _integer(payload.get("receivedMinor"), label="Erhaltener Betrag"),
                currency,
            ),
        )
