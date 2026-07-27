"""Generated-document rendering, storage and protected download use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from leonaid.application.errors import (
    DependencyUnavailable,
    PermissionDenied,
    ResourceNotFound,
)
from leonaid.application.invoice_documents import (
    InvoiceDocumentSnapshot,
    InvoicePdfRenderer,
)
from leonaid.application.invoices import may_read_invoices
from leonaid.application.object_storage import (
    ObjectLocation,
    ObjectStorage,
    ObjectStorageError,
    ObjectWrite,
    StoredObject,
)
from leonaid.domain.documents import (
    GeneratedDocument,
    GeneratedDocumentStatus,
    GeneratedDocumentType,
    INVOICE_DOCUMENT_RENDER_REQUESTED,
)
from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.outbox import ClaimedOutboxEvent


@dataclass(frozen=True, slots=True)
class GeneratedDocumentRenderJob:
    document: GeneratedDocument
    invoice_snapshot: InvoiceDocumentSnapshot


@dataclass(frozen=True, slots=True)
class GeneratedDocumentDownload:
    document: GeneratedDocument
    content: bytes


class GeneratedDocumentRepository(Protocol):
    async def render_job(
        self,
        document_id: UUID,
    ) -> GeneratedDocumentRenderJob | None: ...

    async def mark_available(
        self,
        *,
        document_id: UUID,
        filename: str,
        render_version: str,
        stored: StoredObject,
        available_at: datetime,
    ) -> GeneratedDocument: ...

    async def for_download(
        self,
        *,
        action_id: UUID,
        document_id: UUID,
    ) -> GeneratedDocument | None: ...


class InvoiceDocumentStorageHandler:
    def __init__(
        self,
        *,
        repository: GeneratedDocumentRepository,
        renderer: InvoicePdfRenderer,
        storage: ObjectStorage,
    ) -> None:
        self._repository = repository
        self._renderer = renderer
        self._storage = storage

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        if event.event_type != INVOICE_DOCUMENT_RENDER_REQUESTED:
            raise ValueError("Der Dokument-Handler erhielt einen fremden Ereignistyp.")
        raw_document_id = event.payload.get("documentId")
        try:
            document_id = UUID(str(raw_document_id))
        except (TypeError, ValueError) as error:
            raise ValueError("Der Renderauftrag besitzt keine Dokument-ID.") from error
        job = await self._repository.render_job(document_id)
        if job is None:
            raise RuntimeError("Der Renderauftrag verweist auf kein Dokument.")
        if job.document.document_type is not GeneratedDocumentType.INVOICE_PDF:
            raise RuntimeError(
                "Der Renderauftrag besitzt einen unbekannten Dokumenttyp."
            )
        await self._storage.ensure_private_versioned_bucket()
        if job.document.status is GeneratedDocumentStatus.AVAILABLE:
            await self._verify_available(job.document)
            return
        if job.document.status is not GeneratedDocumentStatus.PENDING:
            raise RuntimeError("Ein gelöschtes Dokument darf nicht neu erzeugt werden.")

        rendered = self._renderer.render(job.invoice_snapshot)
        key = (
            f"actions/{job.document.action_id}/invoices/"
            f"{job.invoice_snapshot.invoice_id}/v{job.document.version}/"
            f"{rendered.sha256}.pdf"
        )
        stored = await self._storage.put_immutable(
            ObjectWrite(
                location=ObjectLocation(
                    bucket=self._storage.bucket,
                    key=key,
                ),
                content=rendered.content,
                media_type=rendered.media_type,
                sha256=rendered.sha256,
                metadata={
                    "document-id": str(job.document.id),
                    "invoice-id": str(job.invoice_snapshot.invoice_id),
                    "invoice-number": job.invoice_snapshot.number,
                    "render-version": rendered.render_version,
                    "document-version": str(job.document.version),
                },
            )
        )
        retrieved = await self._storage.get(stored.location)
        if retrieved.content != rendered.content or retrieved.stored != stored:
            raise RuntimeError(
                "Der gespeicherte Rechnungsbeleg ist nicht byteidentisch lesbar."
            )
        await self._repository.mark_available(
            document_id=job.document.id,
            filename=rendered.filename,
            render_version=rendered.render_version,
            stored=stored,
            available_at=datetime.now(timezone.utc),
        )

    async def _verify_available(self, document: GeneratedDocument) -> None:
        location = _location(document)
        retrieved = await self._storage.get(location)
        if (
            retrieved.stored.sha256 != document.sha256
            or retrieved.stored.size_bytes != document.size_bytes
            or retrieved.stored.media_type != document.media_type
        ):
            raise RuntimeError(
                "Das bereits verfügbare Dokument verletzt seine Speicher-Metadaten."
            )


class GeneratedDocumentService:
    def __init__(
        self,
        *,
        repository: GeneratedDocumentRepository,
        storage: ObjectStorage,
    ) -> None:
        self._repository = repository
        self._storage = storage

    async def download(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        document_id: UUID,
    ) -> GeneratedDocumentDownload:
        if not may_read_invoices(actor, action_id):
            raise PermissionDenied(
                "document_download_required",
                "Du darfst Finanzdokumente dieser Charity-Aktion nicht herunterladen.",
            )
        document = await self._repository.for_download(
            action_id=action_id,
            document_id=document_id,
        )
        if document is None:
            raise ResourceNotFound(
                "generated_document_not_found",
                "Das angeforderte Dokument wurde nicht gefunden.",
            )
        try:
            retrieved = await self._storage.get(_location(document))
        except ObjectStorageError as error:
            raise DependencyUnavailable(
                "generated_document_storage_unavailable",
                "Das Dokument ist momentan nicht sicher abrufbar.",
            ) from error
        if (
            retrieved.stored.sha256 != document.sha256
            or retrieved.stored.size_bytes != document.size_bytes
            or retrieved.stored.media_type != document.media_type
        ):
            raise DependencyUnavailable(
                "generated_document_integrity_failed",
                "Das Dokument konnte nicht mit bestätigter Integrität geladen werden.",
            )
        return GeneratedDocumentDownload(
            document=document,
            content=retrieved.content,
        )


def _location(document: GeneratedDocument) -> ObjectLocation:
    if (
        document.storage_bucket is None
        or document.object_key is None
        or document.storage_version_id is None
    ):
        raise RuntimeError("Das Dokument besitzt keinen vollständigen Speicherbezug.")
    return ObjectLocation(
        bucket=document.storage_bucket,
        key=document.object_key,
        version_id=document.storage_version_id,
    )
