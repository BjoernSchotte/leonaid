"""Generated-document lifecycle and immutability rules."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError

SHA256 = re.compile(r"^[0-9a-f]{64}$")
INVOICE_DOCUMENT_RENDER_REQUESTED = "invoice.document.render.requested.v1"


class GeneratedDocumentStatus(StrEnum):
    PENDING = "pending"
    AVAILABLE = "available"
    DELETED = "deleted"


class GeneratedDocumentType(StrEnum):
    INVOICE_PDF = "invoice_pdf"


@dataclass(frozen=True, slots=True)
class GeneratedDocument:
    id: UUID
    action_id: UUID
    commitment_id: UUID | None
    invoice_id: UUID | None
    twenty_company_id: UUID | None
    twenty_person_id: UUID | None
    document_type: GeneratedDocumentType
    media_type: str
    filename: str | None
    storage_bucket: str | None
    object_key: str | None
    storage_version_id: str | None
    size_bytes: int | None
    sha256: str | None
    render_version: str | None
    version: int
    status: GeneratedDocumentStatus
    created_at: datetime
    available_at: datetime | None = None
    sent_at: datetime | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.commitment_id is None and self.invoice_id is None:
            raise DomainInvariantError(
                "generated_document_owner_required",
                "Ein erzeugtes Dokument benötigt einen fachlichen Bezug.",
            )
        if not self.media_type.strip():
            raise DomainInvariantError(
                "generated_document_media_type_required",
                "Ein erzeugtes Dokument benötigt einen Medientyp.",
            )
        if self.version < 1:
            raise DomainInvariantError(
                "generated_document_version_invalid",
                "Die Dokumentversion muss positiv sein.",
            )
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise DomainInvariantError(
                "generated_document_time_invalid",
                "Der Erzeugungszeitpunkt muss eine Zeitzone enthalten.",
            )
        for label, value in (
            ("available_at", self.available_at),
            ("sent_at", self.sent_at),
            ("deleted_at", self.deleted_at),
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise DomainInvariantError(
                    "generated_document_time_invalid",
                    f"{label} muss eine Zeitzone enthalten.",
                )
        if self.status is GeneratedDocumentStatus.PENDING:
            if any(
                value is not None
                for value in (
                    self.filename,
                    self.storage_bucket,
                    self.object_key,
                    self.storage_version_id,
                    self.size_bytes,
                    self.sha256,
                    self.render_version,
                    self.available_at,
                    self.sent_at,
                    self.deleted_at,
                )
            ):
                raise DomainInvariantError(
                    "generated_document_pending_has_storage",
                    "Ein ausstehendes Dokument darf noch keinen Speicherbezug besitzen.",
                )
            return
        required = (
            self.filename,
            self.storage_bucket,
            self.object_key,
            self.storage_version_id,
            self.size_bytes,
            self.sha256,
            self.render_version,
            self.available_at,
        )
        if any(value is None for value in required):
            raise DomainInvariantError(
                "generated_document_storage_incomplete",
                "Ein verfügbares Dokument benötigt vollständige Speicher-Metadaten.",
            )
        if not SHA256.fullmatch(self.sha256 or ""):
            raise DomainInvariantError(
                "generated_document_sha256_invalid",
                "Die Dokumentprüfsumme ist ungültig.",
            )
        if self.size_bytes is None or self.size_bytes < 1:
            raise DomainInvariantError(
                "generated_document_size_invalid",
                "Ein verfügbares Dokument muss mindestens ein Byte groß sein.",
            )
        if (
            self.sent_at is not None
            and self.status is not GeneratedDocumentStatus.AVAILABLE
        ):
            raise DomainInvariantError(
                "generated_document_sent_not_available",
                "Nur ein verfügbares Dokument kann versandt sein.",
            )
        if self.status is GeneratedDocumentStatus.DELETED and self.deleted_at is None:
            raise DomainInvariantError(
                "generated_document_deleted_time_required",
                "Ein gelöschtes Dokument benötigt einen Löschzeitpunkt.",
            )
        if (
            self.status is GeneratedDocumentStatus.AVAILABLE
            and self.deleted_at is not None
        ):
            raise DomainInvariantError(
                "generated_document_available_deleted",
                "Ein verfügbares Dokument darf nicht als gelöscht markiert sein.",
            )

    @property
    def is_sent(self) -> bool:
        return self.sent_at is not None

    def mark_deleted(self, *, deleted_at: datetime) -> GeneratedDocument:
        if self.status is not GeneratedDocumentStatus.AVAILABLE:
            raise DomainInvariantError(
                "generated_document_delete_status_invalid",
                "Nur ein verfügbares Dokument kann kontrolliert gelöscht werden.",
            )
        if self.is_sent:
            raise DomainInvariantError(
                "generated_document_sent_immutable",
                "Ein versandtes Dokument darf weder überschrieben noch gelöscht werden.",
            )
        return replace(
            self,
            status=GeneratedDocumentStatus.DELETED,
            deleted_at=deleted_at,
        )
