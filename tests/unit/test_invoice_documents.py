from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from leonaid.adapters.typst import RENDER_VERSION, render_payload
from leonaid.application.invoice_documents import (
    InvoiceDocumentSnapshot,
    RenderedInvoiceDocument,
)
from leonaid.domain.errors import DomainInvariantError

FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "golden"
    / "v1"
    / "documents"
    / "KT26-0001.json"
)


def snapshot() -> InvoiceDocumentSnapshot:
    payload: Any = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return InvoiceDocumentSnapshot.from_payload(payload)


def test_invoice_document_snapshot_round_trips_golden_data() -> None:
    invoice = snapshot()

    assert InvoiceDocumentSnapshot.from_payload(invoice.payload()) == invoice


def test_renderer_payload_is_locale_stable_and_snapshot_only() -> None:
    payload = render_payload(snapshot())

    assert payload["renderVersion"] == RENDER_VERSION
    assert payload["issuedOn"] == "30.06.2026"
    assert payload["gross"] == "360,00 EUR"
    assert payload["paymentDetails"] == {
        "accountHolder": "Lions Hilfswerk LeonAid Golden e.V.",
        "iban": "DE89 3704 0044 0532 0130 00",
        "bic": "COBADEFFXXX",
    }
    assert payload["lines"] == [
        {
            "description": "Krapfenbox",
            "quantity": "10",
            "unit": "Boxen",
            "unitPrice": "36,00 EUR",
            "net": "360,00 EUR",
            "tax": "0,00 EUR",
            "gross": "360,00 EUR",
        }
    ]
    assert "status" not in payload
    assert "approvedByUserId" not in payload


def test_rendered_document_rejects_non_pdf_bytes() -> None:
    with pytest.raises(DomainInvariantError) as error:
        RenderedInvoiceDocument.create(
            content=b"not-a-pdf",
            filename="Rechnung-KT26-0001.pdf",
            render_version=RENDER_VERSION,
        )

    assert error.value.code == "invoice_document_pdf_invalid"
