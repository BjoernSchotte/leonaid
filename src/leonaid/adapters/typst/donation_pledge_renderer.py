"""Deterministic Typst renderer of the donation pledge ("Spendenzusage")."""

from __future__ import annotations

from pathlib import Path

from leonaid.adapters.typst.invoice_renderer import (
    TYPST_VERSION,
    TypstCompiler,
    date_label,
    money_label,
)
from leonaid.application.rendered_documents import RenderedDocument
from leonaid.domain.donations import DonationPledgeDocument

PLEDGE_TEMPLATE_VERSION = "donation-pledge-v1"
PLEDGE_RENDER_VERSION = f"{PLEDGE_TEMPLATE_VERSION}+typst-{TYPST_VERSION}"
PLEDGE_TEMPLATE = Path(__file__).with_name("templates") / "donation-pledge-v1.typ"


def _iban_label(value: str) -> str:
    return " ".join(value[index : index + 4] for index in range(0, len(value), 4))


def pledge_render_payload(document: DonationPledgeDocument) -> dict[str, object]:
    """Presentation data of the pledge. Not an invoice: no tax lines, no
    "Rechnung" anywhere; the receiving body's data, never the issuer's."""

    body = document.body
    amount = money_label(
        document.amount.amount_minor,
        "€" if document.amount.currency == "EUR" else document.amount.currency,
    )
    return {
        "renderVersion": PLEDGE_RENDER_VERSION,
        "number": document.number,
        "title": f"Spendenzusage {document.number}",
        "issuedOn": date_label(document.issued_on),
        "amount": amount,
        "thanks": (
            f"Vielen Dank für Ihre Spende von {amount} für die Aktion "
            f"„{document.action_name}“ ({document.carrier_name})."
        ),
        "purpose": document.action_purpose,
        "request": (
            f"Bitte überweisen Sie den Betrag auf das Konto des "
            f"{body.legal_name} und geben Sie als Verwendungszweck "
            f"{document.number} an."
        ),
        "notice": body.pledge_text,
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
            "taxOffice": body.tax_office,
            "taxNumber": body.tax_number,
        },
        "bank": {
            "accountHolder": body.bank_account_holder,
            "iban": _iban_label(body.iban),
            "bic": body.bic,
            "reference": document.number,
        },
    }


class TypstDonationPledgeRenderer:
    def __init__(
        self,
        *,
        executable: str = "typst",
        template: Path = PLEDGE_TEMPLATE,
        timeout_seconds: int = 30,
    ) -> None:
        self._template = template
        self._compiler = TypstCompiler(
            executable=executable, timeout_seconds=timeout_seconds
        )

    def render(self, document: DonationPledgeDocument) -> RenderedDocument:
        content = self._compiler.compile(
            template=self._template,
            template_version=PLEDGE_TEMPLATE_VERSION,
            data_name="document.json",
            payload=pledge_render_payload(document),
            created_at=document.issued_at,
            label=f"Spendenzusage {document.number}",
        )
        return RenderedDocument.create(
            content=content,
            filename=f"Spendenzusage-{document.number}.pdf",
            render_version=PLEDGE_RENDER_VERSION,
        )
