"""PostgreSQL repository for generated-document jobs and metadata."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.documents import (
    GeneratedDocumentRecord,
    GeneratedDocumentReference,
    GeneratedDocumentReferenceKind,
    GeneratedDocumentRenderJob,
    GeneratedDocumentRepository,
)
from leonaid.application.invoice_documents import InvoiceDocumentSnapshot
from leonaid.application.object_storage import StoredObject
from leonaid.domain.commitments import InvoiceRecipientSnapshot, Money
from leonaid.domain.documents import (
    GeneratedDocument,
    GeneratedDocumentStatus,
    GeneratedDocumentType,
)
from leonaid.domain.invoices import (
    InvoiceIssuerSnapshot,
    InvoiceLineSnapshot,
    TaxTreatment,
)


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} besitzt kein gültiges JSON-Objekt.")
    return {str(key): item for key, item in value.items()}


def _json_array(value: object, *, label: str) -> list[dict[str, object]]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RuntimeError(f"{label} besitzt keine gültige JSON-Liste.")
    return [
        {str(key): nested for key, nested in item.items()}
        for item in value
        if isinstance(item, dict)
    ]


class AsyncpgGeneratedDocumentRepository(GeneratedDocumentRepository):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def render_job(
        self,
        document_id: UUID,
    ) -> GeneratedDocumentRenderJob | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT
                    document.*,
                    invoice.number AS invoice_number,
                    invoice.issued_at AS invoice_issued_at,
                    invoice.service_on AS invoice_service_on,
                    invoice.due_on AS invoice_due_on,
                    invoice.issuer_snapshot AS invoice_issuer_snapshot,
                    invoice.recipient_snapshot AS invoice_recipient_snapshot,
                    invoice.line_snapshot AS invoice_line_snapshot,
                    invoice.tax_treatment AS invoice_tax_treatment,
                    invoice.tax_note AS invoice_tax_note,
                    invoice.net_minor AS invoice_net_minor,
                    invoice.tax_minor AS invoice_tax_minor,
                    invoice.gross_minor AS invoice_gross_minor,
                    invoice.currency AS invoice_currency,
                    invoice.payment_reference AS invoice_payment_reference
                FROM generated_document AS document
                JOIN invoice ON invoice.id = document.invoice_id
                WHERE document.id = $1
                """,
                document_id,
            )
        if row is None:
            return None
        return GeneratedDocumentRenderJob(
            document=self._document(row),
            invoice_snapshot=self._invoice_snapshot(row),
        )

    async def mark_available(
        self,
        *,
        document_id: UUID,
        filename: str,
        render_version: str,
        stored: StoredObject,
        available_at: datetime,
    ) -> GeneratedDocument:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    UPDATE generated_document
                    SET filename = $2,
                        storage_bucket = $3,
                        object_key = $4,
                        storage_version_id = $5,
                        size_bytes = $6,
                        sha256 = $7,
                        render_version = $8,
                        status = 'available',
                        available_at = $9,
                        updated_at = $9
                    WHERE id = $1
                      AND status = 'pending'
                    RETURNING *
                    """,
                    document_id,
                    filename,
                    stored.location.bucket,
                    stored.location.key,
                    stored.location.version_id,
                    stored.size_bytes,
                    stored.sha256,
                    render_version,
                    available_at,
                )
                if row is None:
                    row = await connection.fetchrow(
                        "SELECT * FROM generated_document WHERE id = $1 FOR UPDATE",
                        document_id,
                    )
                    if row is None:
                        raise RuntimeError(
                            "Das fertig gerenderte Dokument ist nicht mehr vorhanden."
                        )
                    document = self._document(row)
                    if not self._same_available(
                        document,
                        filename=filename,
                        render_version=render_version,
                        stored=stored,
                    ):
                        raise RuntimeError(
                            "Das Dokument wurde bereits mit anderen Bytes abgeschlossen."
                        )
                    return document
                await connection.execute(
                    """
                    INSERT INTO audit_event (
                        id, action_id, actor_user_id, event_type,
                        entity_type, entity_id, request_id, payload, occurred_at
                    )
                    VALUES (
                        $1, $2, NULL, 'generated_document_available',
                        'generated_document', $3, $4, $5::jsonb, $6
                    )
                    """,
                    uuid4(),
                    row["action_id"],
                    document_id,
                    f"document-render:{document_id}",
                    json.dumps(
                        {
                            "bucket": stored.location.bucket,
                            "objectKey": stored.location.key,
                            "storageVersionId": stored.location.version_id,
                            "sizeBytes": stored.size_bytes,
                            "sha256": stored.sha256,
                            "renderVersion": render_version,
                        },
                        separators=(",", ":"),
                    ),
                    available_at,
                )
        return self._document(row)

    async def for_download(
        self,
        *,
        action_id: UUID,
        document_id: UUID,
    ) -> GeneratedDocument | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT *
                FROM generated_document
                WHERE id = $1
                  AND action_id = $2
                  AND status = 'available'
                  AND document_type = 'invoice_pdf'
                """,
                document_id,
                action_id,
            )
        return None if row is None else self._document(row)

    async def list_for_reference(
        self,
        *,
        action_id: UUID,
        reference: GeneratedDocumentReference,
    ) -> tuple[GeneratedDocumentRecord, ...]:
        reference_columns = {
            GeneratedDocumentReferenceKind.ACTION: None,
            GeneratedDocumentReferenceKind.COMMITMENT: "commitment_id",
            GeneratedDocumentReferenceKind.INVOICE: "invoice_id",
            GeneratedDocumentReferenceKind.TWENTY_COMPANY: "twenty_company_id",
            GeneratedDocumentReferenceKind.TWENTY_PERSON: "twenty_person_id",
        }
        column = reference_columns[reference.kind]
        predicate = "" if column is None else f"AND document.{column} = $2"
        parameters: tuple[UUID, ...] = (
            (action_id,) if column is None else (action_id, reference.id)
        )
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                f"""
                SELECT
                    document.*,
                    invoice.number AS invoice_number,
                    commitment.customer_snapshot
                FROM generated_document AS document
                LEFT JOIN invoice ON invoice.id = document.invoice_id
                LEFT JOIN commitment ON commitment.id = document.commitment_id
                WHERE document.action_id = $1
                  {predicate}
                ORDER BY document.created_at DESC, document.id
                """,
                *parameters,
            )
        return tuple(self._record(row) for row in rows)

    @classmethod
    def _record(cls, row: asyncpg.Record) -> GeneratedDocumentRecord:
        customer = _json_object(
            row["customer_snapshot"] or {},
            label="Dokument-Kundensnapshot",
        )
        buyer_display_name = str(
            customer.get("displayName")
            or row["invoice_number"]
            or "Unbekannter Empfänger"
        )
        return GeneratedDocumentRecord(
            document=cls._document(row),
            invoice_number=(
                str(row["invoice_number"])
                if row["invoice_number"] is not None
                else None
            ),
            buyer_display_name=buyer_display_name,
        )

    @staticmethod
    def _document(row: asyncpg.Record) -> GeneratedDocument:
        return GeneratedDocument(
            id=row["id"],
            action_id=row["action_id"],
            commitment_id=row["commitment_id"],
            invoice_id=row["invoice_id"],
            twenty_company_id=row["twenty_company_id"],
            twenty_person_id=row["twenty_person_id"],
            document_type=GeneratedDocumentType(str(row["document_type"])),
            media_type=str(row["media_type"]),
            filename=str(row["filename"]) if row["filename"] is not None else None,
            storage_bucket=(
                str(row["storage_bucket"])
                if row["storage_bucket"] is not None
                else None
            ),
            object_key=(
                str(row["object_key"]) if row["object_key"] is not None else None
            ),
            storage_version_id=(
                str(row["storage_version_id"])
                if row["storage_version_id"] is not None
                else None
            ),
            size_bytes=(
                int(row["size_bytes"]) if row["size_bytes"] is not None else None
            ),
            sha256=str(row["sha256"]) if row["sha256"] is not None else None,
            render_version=(
                str(row["render_version"])
                if row["render_version"] is not None
                else None
            ),
            version=int(row["version"]),
            status=GeneratedDocumentStatus(str(row["status"])),
            created_at=row["created_at"],
            available_at=row["available_at"],
            sent_at=row["sent_at"],
            deleted_at=row["deleted_at"],
        )

    @staticmethod
    def _invoice_snapshot(row: asyncpg.Record) -> InvoiceDocumentSnapshot:
        currency = str(row["invoice_currency"])
        return InvoiceDocumentSnapshot(
            invoice_id=row["invoice_id"],
            number=str(row["invoice_number"]),
            issued_at=row["invoice_issued_at"],
            service_on=row["invoice_service_on"],
            due_on=row["invoice_due_on"],
            issuer=InvoiceIssuerSnapshot.from_payload(
                _json_object(
                    row["invoice_issuer_snapshot"],
                    label="Rechnungsaussteller-Snapshot",
                )
            ),
            recipient=InvoiceRecipientSnapshot.from_payload(
                _json_object(
                    row["invoice_recipient_snapshot"],
                    label="Rechnungsempfänger-Snapshot",
                )
            ),
            lines=tuple(
                InvoiceLineSnapshot.from_payload(item)
                for item in _json_array(
                    row["invoice_line_snapshot"],
                    label="Rechnungspositions-Snapshot",
                )
            ),
            tax_treatment=TaxTreatment(str(row["invoice_tax_treatment"])),
            tax_note=str(row["invoice_tax_note"]),
            net=Money(int(row["invoice_net_minor"]), currency),
            tax=Money(int(row["invoice_tax_minor"]), currency),
            gross=Money(int(row["invoice_gross_minor"]), currency),
            payment_reference=str(row["invoice_payment_reference"]),
        )

    @staticmethod
    def _same_available(
        document: GeneratedDocument,
        *,
        filename: str,
        render_version: str,
        stored: StoredObject,
    ) -> bool:
        return (
            document.status is GeneratedDocumentStatus.AVAILABLE
            and document.filename == filename
            and document.render_version == render_version
            and document.storage_bucket == stored.location.bucket
            and document.object_key == stored.location.key
            and document.storage_version_id == stored.location.version_id
            and document.size_bytes == stored.size_bytes
            and document.sha256 == stored.sha256
        )
