"""Deterministic Typst renderer of the donation receipt
("Zuwendungsbestätigung"), following the official sample for money
donations to bodies of § 5 Abs. 1 Nr. 9 KStG."""

from __future__ import annotations

from pathlib import Path

from leonaid.adapters.typst.invoice_renderer import (
    TYPST_VERSION,
    TypstCompiler,
    date_label,
    money_label,
)
from leonaid.application.rendered_documents import RenderedDocument
from leonaid.domain.donation_receipts import DonationReceiptDocument, amount_in_words

RECEIPT_TEMPLATE_VERSION = "donation-receipt-v1"
RECEIPT_RENDER_VERSION = f"{RECEIPT_TEMPLATE_VERSION}+typst-{TYPST_VERSION}"
RECEIPT_TEMPLATE = Path(__file__).with_name("templates") / "donation-receipt-v1.typ"

RECEIPT_TITLE = "Bestätigung über Geldzuwendungen"
RECEIPT_SUBTITLE = (
    "im Sinne des § 10b des Einkommensteuergesetzes an eine der in § 5 Abs. 1 "
    "Nr. 9 des Körperschaftsteuergesetzes bezeichneten Körperschaften, "
    "Personenvereinigungen oder Vermögensmassen"
)
NO_WAIVER = "Es handelt sich nicht um den Verzicht auf Erstattung von Aufwendungen."


def receipt_render_payload(document: DonationReceiptDocument) -> dict[str, object]:
    """Presentation data of the receipt: the receiving body, the donor, the
    amount in figures and in words, the day of the donation, the notice
    paragraph of the body's kind of notice, the purposes, the signatory."""

    body = document.body
    machine = document.signed_by_machine
    return {
        "renderVersion": RECEIPT_RENDER_VERSION,
        "number": document.number,
        "documentTitle": f"Zuwendungsbestätigung {document.number}",
        "title": RECEIPT_TITLE,
        "subtitle": RECEIPT_SUBTITLE,
        "donationNumber": document.donation_number,
        "amount": money_label(document.amount.amount_minor, "€"),
        "amountInWords": amount_in_words(document.amount),
        "receivedOn": date_label(document.received_on),
        "noWaiver": NO_WAIVER,
        "notice": document.notice_paragraph(),
        "purpose": (
            f"Es wird bestätigt, dass die Zuwendung nur zur {body.purposes} "
            "verwendet wird."
        ),
        "placeAndDate": f"{body.city}, {date_label(document.issued_on)}",
        "signatory": f"{body.signatory_name}, {body.signatory_function}",
        "signedByMachine": machine,
        # By hand: an empty line to sign on. Machine: the sentence that names
        # the procedure notified to the tax office (R 10b.1 Abs. 4 EStR).
        "signatureNote": (
            "Diese Zuwendungsbestätigung wurde maschinell erstellt und trägt "
            "keine eigenhändige Unterschrift. Das Verfahren ist dem "
            f"{body.tax_office} angezeigt (R 10b.1 Abs. 4 EStR)."
            if machine
            else "(Ort, Datum und Unterschrift des Zuwendungsempfängers)"
        ),
        "liability": body.receipt_liability_text,
        "donor": {
            "name": document.donor.name,
            "streetLine1": document.donor.street_line_1,
            "postalCode": document.donor.postal_code,
            "city": document.donor.city,
            "countryCode": document.donor.country_code,
        },
        "body": {
            "legalName": body.legal_name,
            "streetLine1": body.street_line_1,
            "postalCode": body.postal_code,
            "city": body.city,
            "countryCode": body.country_code,
        },
    }


class TypstDonationReceiptRenderer:
    def __init__(
        self,
        *,
        executable: str = "typst",
        template: Path = RECEIPT_TEMPLATE,
        timeout_seconds: int = 30,
    ) -> None:
        self._template = template
        self._compiler = TypstCompiler(
            executable=executable, timeout_seconds=timeout_seconds
        )

    def render(self, document: DonationReceiptDocument) -> RenderedDocument:
        payload = receipt_render_payload(document)
        content = self._compiler.compile(
            template=self._template,
            template_version=RECEIPT_TEMPLATE_VERSION,
            data_name="document.json",
            payload=payload,
            created_at=document.issued_at,
            label=f"Zuwendungsbestätigung {document.number}",
        )
        return RenderedDocument.create(
            content=content,
            filename=f"Zuwendungsbestaetigung-{document.number}.pdf",
            render_version=RECEIPT_RENDER_VERSION,
        )
