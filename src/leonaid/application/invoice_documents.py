"""Renderer-neutral invoice document snapshots and ports."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from leonaid.domain.commitments import InvoiceRecipientSnapshot, Money
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.invoices import (
    Invoice,
    InvoiceIssuerSnapshot,
    InvoiceLineSnapshot,
    TaxTreatment,
)

INVOICE_DOCUMENT_SCHEMA_VERSION = 1


def _object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DomainInvariantError(
            "invoice_document_payload_invalid",
            f"{label} des Rechnungsdokuments ist ungültig.",
        )
    return value


def _array(value: object, *, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise DomainInvariantError(
            "invoice_document_payload_invalid",
            f"{label} des Rechnungsdokuments ist ungültig.",
        )
    return [_object(item, label=label) for item in value]


def _integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DomainInvariantError(
            "invoice_document_payload_invalid",
            f"{label} des Rechnungsdokuments muss eine Ganzzahl sein.",
        )
    return value


@dataclass(frozen=True, slots=True)
class InvoiceDocumentSnapshot:
    """Only immutable issued-invoice fields consumed by document renderers."""

    invoice_id: UUID
    number: str
    issued_at: datetime
    service_on: date
    due_on: date
    issuer: InvoiceIssuerSnapshot
    recipient: InvoiceRecipientSnapshot
    lines: tuple[InvoiceLineSnapshot, ...]
    tax_treatment: TaxTreatment
    tax_note: str
    net: Money
    tax: Money
    gross: Money
    payment_reference: str

    def __post_init__(self) -> None:
        if self.issued_at.tzinfo is None or self.issued_at.utcoffset() is None:
            raise DomainInvariantError(
                "invoice_document_issued_at_timezone_required",
                "Das Rechnungsdokument benötigt einen eindeutigen Freigabezeitpunkt.",
            )
        if not self.lines:
            raise DomainInvariantError(
                "invoice_document_lines_required",
                "Das Rechnungsdokument benötigt mindestens eine Position.",
            )
        line_net = Money(0, self.gross.currency)
        line_tax = Money(0, self.gross.currency)
        line_gross = Money(0, self.gross.currency)
        for line in self.lines:
            line_net = line_net.plus(line.net)
            line_tax = line_tax.plus(line.tax)
            line_gross = line_gross.plus(line.gross)
        if (
            line_net != self.net
            or line_tax != self.tax
            or line_gross != self.gross
            or self.net.plus(self.tax) != self.gross
        ):
            raise DomainInvariantError(
                "invoice_document_totals_invalid",
                "Die Dokumentbeträge stimmen nicht mit den Rechnungspositionen überein.",
            )

    @classmethod
    def from_invoice(cls, invoice: Invoice) -> InvoiceDocumentSnapshot:
        return cls(
            invoice_id=invoice.id,
            number=invoice.number,
            issued_at=invoice.issued_at,
            service_on=invoice.service_on,
            due_on=invoice.due_on,
            issuer=invoice.issuer,
            recipient=invoice.recipient,
            lines=invoice.lines,
            tax_treatment=invoice.tax_treatment,
            tax_note=invoice.tax_note,
            net=invoice.net,
            tax=invoice.tax,
            gross=invoice.gross,
            payment_reference=invoice.payment_reference,
        )

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": INVOICE_DOCUMENT_SCHEMA_VERSION,
            "invoiceId": str(self.invoice_id),
            "number": self.number,
            "issuedAt": self.issued_at.isoformat(),
            "serviceOn": self.service_on.isoformat(),
            "dueOn": self.due_on.isoformat(),
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
            "paymentReference": self.payment_reference,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> InvoiceDocumentSnapshot:
        version = _integer(payload.get("schemaVersion"), label="Schemaversion")
        if version != INVOICE_DOCUMENT_SCHEMA_VERSION:
            raise DomainInvariantError(
                "invoice_document_schema_unsupported",
                f"Dokumentschema {version} wird nicht unterstützt.",
            )
        totals = _object(payload.get("totals"), label="Summen")
        currency = str(totals.get("currency"))
        return cls(
            invoice_id=UUID(str(payload.get("invoiceId"))),
            number=str(payload.get("number")),
            issued_at=datetime.fromisoformat(str(payload.get("issuedAt"))),
            service_on=date.fromisoformat(str(payload.get("serviceOn"))),
            due_on=date.fromisoformat(str(payload.get("dueOn"))),
            issuer=InvoiceIssuerSnapshot.from_payload(
                _object(payload.get("issuer"), label="Rechnungsaussteller")
            ),
            recipient=InvoiceRecipientSnapshot.from_payload(
                _object(payload.get("recipient"), label="Rechnungsempfänger")
            ),
            lines=tuple(
                InvoiceLineSnapshot.from_payload(item)
                for item in _array(payload.get("lines"), label="Positionen")
            ),
            tax_treatment=TaxTreatment(str(payload.get("taxTreatment"))),
            tax_note=str(payload.get("taxNote")),
            net=Money(_integer(totals.get("netMinor"), label="Nettosumme"), currency),
            tax=Money(
                _integer(totals.get("taxMinor"), label="Steuersumme"),
                currency,
            ),
            gross=Money(
                _integer(totals.get("grossMinor"), label="Bruttosumme"),
                currency,
            ),
            payment_reference=str(payload.get("paymentReference")),
        )


@dataclass(frozen=True, slots=True)
class RenderedInvoiceDocument:
    content: bytes
    filename: str
    media_type: str
    render_version: str
    sha256: str

    @classmethod
    def create(
        cls,
        *,
        content: bytes,
        filename: str,
        render_version: str,
    ) -> RenderedInvoiceDocument:
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-1_024:]:
            raise DomainInvariantError(
                "invoice_document_pdf_invalid",
                "Der Renderer hat kein vollständiges PDF erzeugt.",
            )
        return cls(
            content=content,
            filename=filename,
            media_type="application/pdf",
            render_version=render_version,
            sha256=hashlib.sha256(content).hexdigest(),
        )


class InvoicePdfRenderer(Protocol):
    def render(self, snapshot: InvoiceDocumentSnapshot) -> RenderedInvoiceDocument: ...
