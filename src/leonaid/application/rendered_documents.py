"""What a document renderer hands to the storage step, for every kind."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

from leonaid.domain.documents import GeneratedDocument
from leonaid.domain.errors import DomainInvariantError


@dataclass(frozen=True, slots=True)
class RenderedDocument:
    content: bytes
    filename: str
    media_type: str
    render_version: str
    sha256: str

    @classmethod
    def create(
        cls,
        *,
        content: bytes,
        filename: str,
        render_version: str,
    ) -> RenderedDocument:
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-1_024:]:
            raise DomainInvariantError(
                "invoice_document_pdf_invalid",
                "Der Renderer hat kein vollständiges PDF erzeugt.",
            )
        return cls(
            content=content,
            filename=filename,
            media_type="application/pdf",
            render_version=render_version,
            sha256=hashlib.sha256(content).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class DocumentRendering:
    """A rendered document and where its kind keeps it.

    ``storage_path`` is the part of the object key that names the business
    object, below the action and above the version, for example
    ``invoices/<invoice id>``.
    """

    rendered: RenderedDocument
    storage_path: str
    metadata: dict[str, str] = field(default_factory=dict)


class DocumentSource(Protocol):
    """Reads the snapshot of one document type and renders it.

    One source per ``GeneratedDocumentType``. The storage handler knows no
    document kind: a new kind registers its source and nothing else changes.
    """

    async def render(self, document: GeneratedDocument) -> DocumentRendering: ...
