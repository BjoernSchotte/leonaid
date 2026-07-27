from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from leonaid.domain.documents import (
    GeneratedDocument,
    GeneratedDocumentStatus,
    GeneratedDocumentType,
)
from leonaid.domain.errors import DomainInvariantError

DOCUMENT_ID = UUID("90000000-0000-4000-8000-000000000001")
ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
COMMITMENT_ID = UUID("80000000-0000-4000-8000-000000000001")
INVOICE_ID = UUID("90000000-0000-4000-8000-000000000001")
CREATED_AT = datetime(2026, 6, 30, 8, 0, tzinfo=timezone.utc)


def pending_document() -> GeneratedDocument:
    return GeneratedDocument(
        id=DOCUMENT_ID,
        action_id=ACTION_ID,
        commitment_id=COMMITMENT_ID,
        invoice_id=INVOICE_ID,
        twenty_company_id=UUID("40000000-0000-4000-8000-000000000001"),
        twenty_person_id=None,
        document_type=GeneratedDocumentType.INVOICE_PDF,
        media_type="application/pdf",
        filename=None,
        storage_bucket=None,
        object_key=None,
        storage_version_id=None,
        size_bytes=None,
        sha256=None,
        render_version=None,
        version=1,
        status=GeneratedDocumentStatus.PENDING,
        created_at=CREATED_AT,
    )


def available_document() -> GeneratedDocument:
    return replace(
        pending_document(),
        filename="Rechnung-KT26-0001.pdf",
        storage_bucket="leonaid",
        object_key=f"actions/{ACTION_ID}/invoices/{INVOICE_ID}/v1/golden.pdf",
        storage_version_id="golden-storage-version-1",
        size_bytes=12_345,
        sha256="1" * 64,
        render_version="invoice-v1+typst-0.13.1",
        status=GeneratedDocumentStatus.AVAILABLE,
        available_at=CREATED_AT,
    )


def test_pending_document_has_no_storage_identity() -> None:
    document = pending_document()

    assert document.status is GeneratedDocumentStatus.PENDING
    assert document.object_key is None


def test_available_document_can_be_controlled_deleted_before_send() -> None:
    deleted_at = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)

    deleted = available_document().mark_deleted(deleted_at=deleted_at)

    assert deleted.status is GeneratedDocumentStatus.DELETED
    assert deleted.deleted_at == deleted_at
    assert deleted.object_key == available_document().object_key


def test_sent_document_can_neither_be_deleted_nor_replaced() -> None:
    sent = replace(available_document(), sent_at=CREATED_AT)

    with pytest.raises(DomainInvariantError) as error:
        sent.mark_deleted(deleted_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc))

    assert error.value.code == "generated_document_sent_immutable"
