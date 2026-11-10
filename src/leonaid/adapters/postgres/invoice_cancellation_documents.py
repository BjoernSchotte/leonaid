"""Issuing the cancellation invoice inside the caller's transaction.

Both cancel paths (``cancelInvoice`` and ``cancelCommitment``) and the later
issue for an older cancellation use these steps. The caller holds the
invoice's advisory locks and its row lock, so the payments read here can no
longer change.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.document_series import allocate_document_number
from leonaid.adapters.postgres.invoice_payment_state import ACTIVE_PAID_MINOR_SQL
from leonaid.adapters.postgres.invoices import AsyncpgInvoiceRepository
from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.domain.commitments import Money
from leonaid.domain.document_series import DocumentSeriesKind
from leonaid.domain.documents import DOCUMENT_RENDER_REQUESTED, GeneratedDocumentType
from leonaid.domain.invoice_cancellation_documents import InvoiceCancellationDocument

CANCELLATION_DOCUMENT_VERSION = 1


async def prepare_cancellation_document(
    connection: asyncpg.Connection[Any],
    *,
    cancellation_id: UUID,
    action_id: UUID,
    invoice_id: UUID,
    occurred_at: datetime,
) -> InvoiceCancellationDocument:
    """Takes the next number of the invoice series and builds the snapshot.

    The number is rolled back with the transaction when a later step fails.
    """

    row = await connection.fetchrow(
        f"""
        SELECT invoice.*, {ACTIVE_PAID_MINOR_SQL} AS received_minor
        FROM invoice
        WHERE invoice.id = $1 AND invoice.action_id = $2
        """,
        invoice_id,
        action_id,
    )
    if row is None:
        raise ResourceNotFound(
            "invoice_settlement_not_found",
            "Die Rechnung wurde in dieser Charity-Aktion nicht gefunden.",
        )
    invoice = AsyncpgInvoiceRepository._invoice_from_row(row)
    # The series of the prefix in force now: the cancellation invoice is a
    # document of today (D-C1), whatever prefix the invoice once had.
    profile = await connection.fetchrow(
        "SELECT number_prefix, number_width FROM invoice_profile WHERE action_id = $1",
        action_id,
    )
    if profile is None:
        raise Conflict(
            "invoice_profile_missing",
            "Für diese Charity-Aktion fehlt das Rechnungsprofil. Ohne dessen "
            "Nummernkreis kann keine Stornorechnung ausgestellt werden.",
        )
    number = await allocate_document_number(
        connection,
        kind=DocumentSeriesKind.INVOICE,
        prefix=str(profile["number_prefix"]),
        width=int(profile["number_width"]),
        occurred_at=occurred_at,
    )
    return InvoiceCancellationDocument.issue(
        cancellation_id=cancellation_id,
        number=number,
        invoice=invoice,
        received=Money(int(row["received_minor"]), invoice.gross.currency),
        issued_at=occurred_at,
    )


def document_columns(
    document: InvoiceCancellationDocument,
) -> tuple[str, object, datetime, str, int]:
    """number, issued_on, issued_at, snapshot JSON and document version."""

    return (
        document.number,
        document.issued_on,
        document.issued_at,
        json.dumps(document.payload(), ensure_ascii=False, separators=(",", ":")),
        CANCELLATION_DOCUMENT_VERSION,
    )


async def request_cancellation_render(
    connection: asyncpg.Connection[Any],
    *,
    document: InvoiceCancellationDocument,
    action_id: UUID,
    occurred_at: datetime,
) -> UUID:
    """The pending PDF of the cancellation invoice and its render job."""

    document_id = uuid4()
    await connection.execute(
        """
        INSERT INTO generated_document (
            id, action_id, commitment_id, invoice_id,
            twenty_company_id, twenty_person_id,
            document_type, media_type, version, status,
            created_at, updated_at
        )
        SELECT
            $1, invoice.action_id, invoice.commitment_id, invoice.id,
            commitment.twenty_company_id, commitment.twenty_person_id,
            $4, 'application/pdf', $5, 'pending', $3, $3
        FROM invoice
        JOIN commitment ON commitment.id = invoice.commitment_id
        WHERE invoice.id = $2 AND invoice.action_id = $6
        """,
        document_id,
        document.invoice_id,
        occurred_at,
        GeneratedDocumentType.INVOICE_CANCELLATION_PDF.value,
        CANCELLATION_DOCUMENT_VERSION,
        action_id,
    )
    await connection.execute(
        """
        INSERT INTO outbox_event (
            id, aggregate_type, aggregate_id, event_type,
            idempotency_key, payload, available_at, created_at
        )
        VALUES ($1, 'generated_document', $2, $3, $4, $5::jsonb, $6, $6)
        """,
        uuid4(),
        document_id,
        DOCUMENT_RENDER_REQUESTED,
        f"document-render:{document_id}:v{CANCELLATION_DOCUMENT_VERSION}",
        json.dumps({"documentId": str(document_id)}, separators=(",", ":")),
        occurred_at,
    )
    return document_id
