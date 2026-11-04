"""Shared builders for invoice unit tests (no tests here)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from leonaid.application.invoice_documents import InvoiceDocumentSnapshot
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import (
    BuyerSnapshot,
    Commitment,
    CommitmentLine,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
    InvoiceRecipientSnapshot,
    Money,
)
from leonaid.domain.invoices import (
    InvoiceIssuerSnapshot,
    InvoicePaymentDetailsSnapshot,
    InvoiceProfile,
    TaxTreatment,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
COMMITMENT_ID = UUID("80000000-0000-4000-8000-000000000002")
INVOICE_ID = UUID("90000000-0000-4000-8000-000000000004")
PROFILE_ID = UUID("96000000-0000-4000-8000-000000000001")
LEGAL_CONFIGURATION_ID = UUID("94000000-0000-4000-8000-000000000044")
ADMIN_ID = UUID("10000000-0000-4000-8000-000000000002")
ISSUED_AT = datetime(2026, 10, 12, 10, tzinfo=timezone.utc)


def commitment(
    *,
    status: CommitmentStatus = CommitmentStatus.REVIEW_READY,
) -> Commitment:
    line = CommitmentLine(
        id=UUID("81000000-0000-4000-8000-000000000001"),
        offering_id=UUID("70000000-0000-4000-8000-000000000001"),
        description_snapshot="Krapfenbox",
        quantity=3,
        unit_snapshot=OfferingUnit.BOX,
        pieces_per_unit_snapshot=24,
        unit_price=Money(3_600, "EUR"),
        line_total=Money(10_800, "EUR"),
    )
    return Commitment(
        id=COMMITMENT_ID,
        action_id=ACTION_ID,
        source=CommitmentSource.ACQUISITION,
        status=status,
        buyer=BuyerSnapshot(
            party_kind=CommitmentPartyKind.COMPANY,
            twenty_id=UUID("40000000-0000-4000-8000-000000000002"),
            display_name="Bäckerei Sonnenseite KG",
            email="einkauf@sonnenseite.invalid",
        ),
        invoice_recipient=InvoiceRecipientSnapshot(
            recipient_name="Bäckerei Sonnenseite KG",
            street_line_1="Sonnenstraße 2",
            postal_code="10243",
            city="Beispielstadt",
            country_code="DE",
            email="rechnung@sonnenseite.invalid",
        ),
        lines=(line,),
        total=Money(10_800, "EUR"),
    )


def profile(
    *,
    tax_treatment: TaxTreatment = TaxTreatment.SMALL_BUSINESS,
    tax_rate_basis_points: int = 0,
    confirmed_at: datetime | None = ISSUED_AT - timedelta(days=30),
) -> InvoiceProfile:
    return InvoiceProfile(
        id=PROFILE_ID,
        action_id=ACTION_ID,
        issuer=InvoiceIssuerSnapshot(
            legal_name="Lions Hilfswerk LeonAid Golden e.V.",
            street_line_1="Clubweg 1",
            postal_code="86150",
            city="Augsburg",
            country_code="DE",
            tax_identifier="103/999/99999",
            email="finanzen@leonaid.invalid",
        ),
        payment_details=InvoicePaymentDetailsSnapshot(
            account_holder="Lions Hilfswerk LeonAid Golden e.V.",
            iban="DE89 3704 0044 0532 0130 00",
            bic="COBADEFFXXX",
        ),
        tax_treatment=tax_treatment,
        tax_rate_basis_points=tax_rate_basis_points,
        tax_note=(
            "Umsatzsteuer 19 %."
            if tax_treatment is TaxTreatment.STANDARD_VAT
            else "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet."
        ),
        number_prefix="KT26-",
        next_number=4,
        number_width=4,
        payment_terms_days=14,
        confirmed_at=confirmed_at,
        legal_configuration_version_id=LEGAL_CONFIGURATION_ID,
    )


GOLDEN_DOCUMENT = (
    Path(__file__).parents[1]
    / "fixtures"
    / "golden"
    / "v1"
    / "documents"
    / "KT26-0001.json"
)


def golden_document_payload() -> dict[str, Any]:
    payload: Any = json.loads(GOLDEN_DOCUMENT.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def document_snapshot() -> InvoiceDocumentSnapshot:
    return InvoiceDocumentSnapshot.from_payload(golden_document_payload())
