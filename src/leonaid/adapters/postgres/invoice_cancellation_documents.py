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

from leonaid.adapters.postgres.document_series import (
    allocate_document_number,
    series_of_issued_number,
)
from leonaid.adapters.postgres.invoice_payment_state import ACTIVE_PAID_MINOR_SQL
from leonaid.adapters.postgres.invoices import AsyncpgInvoiceRepository
from leonaid.application.errors import ResourceNotFound
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
    prefix, width = await cancellation_series(
        connection, action_id=action_id, invoice_number=invoice.number
    )
    number = await allocate_document_number(
        connection,
        kind=DocumentSeriesKind.INVOICE,
        prefix=prefix,
        width=width,
        occurred_at=occurred_at,
    )
    return InvoiceCancellationDocument.issue(
        cancellation_id=cancellation_id,
        number=number,
        invoice=invoice,
        received=Money(int(row["received_minor"]), invoice.gross.currency),
        issued_at=occurred_at,
    )


async def cancellation_series(
    connection: asyncpg.Connection[Any],
    *,
    action_id: UUID,
    invoice_number: str,
) -> tuple[str, int]:
    """Prefix and width of the series a cancellation invoice is numbered in.

    An invoice must never be impossible to cancel, so there is always one:

    1. the action's invoice profile: the prefix in force today (D-C1);
    2. without a profile (invoices seeded or written before profiles were
       created for every action): the active legal configuration;
    3. without that too: the series the invoice's own number belongs to.
    """

    row = await connection.fetchrow(
        """
        SELECT number_prefix, number_width FROM invoice_profile
        WHERE action_id = $1
        """,
        action_id,
    )
    if row is None:
        row = await connection.fetchrow(
            """
            SELECT version.number_prefix, version.number_width
            FROM legal_configuration_state AS state
            JOIN legal_configuration_version AS version
              ON version.id = state.active_version_id
            """
        )
    if row is None:
        return await series_of_issued_number(
            connection, kind=DocumentSeriesKind.INVOICE, number=invoice_number
        )
    return str(row["number_prefix"]), int(row["number_width"])


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
