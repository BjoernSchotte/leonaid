from __future__ import annotations

from datetime import date
from uuid import UUID

from leonaid.application.invoice_deliveries import (
    InvoiceDeliveryContext,
    InvoiceDeliveryService,
)


def golden_context() -> InvoiceDeliveryContext:
    return InvoiceDeliveryContext(
        action_id=UUID("20000000-0000-4000-8000-000000000001"),
        action_name="Krapfentaxi 2026",
        invoice_id=UUID("90000000-0000-4000-8000-000000000001"),
        invoice_number="KT26-0001",
        document_id=UUID("92000000-0000-4000-8000-000000000001"),
        recipient_name="Bäckerei Sonnenseite KG",
        recipient_email="rechnung@sonnenseite.invalid",
        issuer_name="Lions Hilfswerk LeonAid Golden e.V.",
        gross_minor=36000,
        currency="EUR",
        due_on=date(2026, 7, 14),
        payment_reference="KT26-0001",
    )


def test_invoice_delivery_message_is_clear_and_snapshot_based() -> None:
    message = InvoiceDeliveryService._message_text(golden_context())

    assert message == (
        "Guten Tag Bäckerei Sonnenseite KG,\n\n"
        "anbei erhalten Sie die Rechnung KT26-0001 zur Charity-Aktion "
        "„Krapfentaxi 2026“.\n\n"
        "Rechnungsbetrag: 360,00 €\n"
        "Zahlbar bis: 14.07.2026\n"
        "Verwendungszweck: KT26-0001\n\n"
        "Bei Fragen zu dieser Rechnung antworten Sie bitte auf diese E-Mail.\n\n"
        "Vielen Dank für Ihre Unterstützung.\n\n"
        "Freundliche Grüße\n"
        "Lions Hilfswerk LeonAid Golden e.V."
    )


def test_invoice_delivery_money_format_handles_grouping() -> None:
    assert InvoiceDeliveryService._format_money(123456789, "EUR") == "1.234.567,89 €"
    assert InvoiceDeliveryService._format_money(1250, "CHF") == "12,50 CHF"
