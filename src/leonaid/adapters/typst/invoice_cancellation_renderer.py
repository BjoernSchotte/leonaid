"""Deterministic Typst renderer of the cancellation invoice."""

from __future__ import annotations

from pathlib import Path

from leonaid.adapters.typst.invoice_renderer import (
    TYPST_VERSION,
    TypstCompiler,
    date_label,
    money_label,
    unit_label,
)
from leonaid.application.rendered_documents import RenderedDocument
from leonaid.domain.commitments import Money
from leonaid.domain.invoice_cancellation_documents import InvoiceCancellationDocument

CANCELLATION_TEMPLATE_VERSION = "invoice-cancellation-v1"
CANCELLATION_RENDER_VERSION = f"{CANCELLATION_TEMPLATE_VERSION}+typst-{TYPST_VERSION}"
CANCELLATION_TEMPLATE = (
    Path(__file__).with_name("templates") / "invoice-cancellation-v1.typ"
)


def cancellation_render_payload(
    document: InvoiceCancellationDocument,
) -> dict[str, object]:
    """Presentation data: the document's amounts, printed with a minus sign."""

    def printed(amount: Money) -> str:
        return money_label(document.printed_minor(amount), amount.currency)

    original_issued_on = date_label(document.original_issued_on)
    original = f"{document.original_number} vom {original_issued_on}"
    if document.refund_due:
        # The sentence follows the agreed wording (spec Appendix A.2), which
        # writes the amount with the euro sign; the table keeps the currency
        # code of the invoice it reverses.
        received = money_label(
            document.received.amount_minor,
            "€" if document.received.currency == "EUR" else document.received.currency,
        )
        closing = (
            f"Auf die Rechnung {document.original_number} haben wir {received} "
            "erhalten. Die Erstattung erfolgt gesondert."
        )
    else:
        closing = (
            f"Aus der Rechnung {document.original_number} ist kein Betrag mehr "
            "zu zahlen."
        )
    return {
        "renderVersion": CANCELLATION_RENDER_VERSION,
        "number": document.number,
        "title": f"Stornorechnung {document.number}",
        "reference": f"zur Rechnung {original}",
        "introduction": (
            f"Mit dieser Stornorechnung heben wir die Rechnung {original} "
            "vollständig auf. Die Beträge der Rechnung werden mit umgekehrtem "
            "Vorzeichen ausgewiesen."
        ),
        "issuedOn": date_label(document.issued_on),
        "originalNumber": document.original_number,
        "originalIssuedOn": original_issued_on,
        "issuer": document.issuer.payload(),
        "recipient": document.recipient.payload(),
        "lines": [
            {
                "description": line.description,
                "quantity": str(line.quantity),
                "unit": unit_label(line.unit.value, line.quantity),
                "unitPrice": printed(line.unit_price_gross),
                "net": printed(line.net),
                "tax": printed(line.tax),
                "gross": printed(line.gross),
            }
            for line in document.lines
        ],
        "net": printed(document.net),
        "tax": printed(document.tax),
        "gross": printed(document.gross),
        "taxNote": document.tax_note,
        "closing": closing,
    }


class TypstInvoiceCancellationRenderer:
    def __init__(
        self,
        *,
        executable: str = "typst",
        template: Path = CANCELLATION_TEMPLATE,
        timeout_seconds: int = 30,
    ) -> None:
        self._template = template
        self._compiler = TypstCompiler(
            executable=executable, timeout_seconds=timeout_seconds
        )

    def render(self, document: InvoiceCancellationDocument) -> RenderedDocument:
        content = self._compiler.compile(
            template=self._template,
            template_version=CANCELLATION_TEMPLATE_VERSION,
            data_name="document.json",
            payload=cancellation_render_payload(document),
            created_at=document.issued_at,
            label=f"Stornorechnung {document.number}",
        )
        return RenderedDocument.create(
            content=content,
            filename=f"Stornorechnung-{document.number}.pdf",
            render_version=CANCELLATION_RENDER_VERSION,
        )
