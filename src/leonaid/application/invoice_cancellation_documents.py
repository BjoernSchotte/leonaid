"""The ``invoice_cancellation_pdf`` document: ports and render source."""

from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID

from leonaid.application.rendered_documents import (
    DocumentRendering,
    RenderedDocument,
)
from leonaid.domain.documents import GeneratedDocument
from leonaid.domain.invoice_cancellation_documents import InvoiceCancellationDocument


class InvoiceCancellationPdfRenderer(Protocol):
    def render(self, document: InvoiceCancellationDocument) -> RenderedDocument: ...


class InvoiceCancellationDocumentReader(Protocol):
    async def invoice_cancellation_document(
        self, invoice_id: UUID
    ) -> InvoiceCancellationDocument | None: ...


class InvoiceCancellationDocumentSource:
    """Renders the stored snapshot of the cancellation invoice."""

    def __init__(
        self,
        *,
        documents: InvoiceCancellationDocumentReader,
        renderer: InvoiceCancellationPdfRenderer,
    ) -> None:
        self._documents = documents
        self._renderer = renderer

    async def render(self, document: GeneratedDocument) -> DocumentRendering:
        if document.invoice_id is None:
            raise RuntimeError("Die Stornorechnung verweist auf keine Rechnung.")
        snapshot = await self._documents.invoice_cancellation_document(
            document.invoice_id
        )
        if snapshot is None:
            raise RuntimeError("Die Stornorechnung des Dokuments wurde nicht gefunden.")
        # Typst runs as a blocking subprocess; keep the worker event loop free.
        rendered = await asyncio.to_thread(self._renderer.render, snapshot)
        return DocumentRendering(
            rendered=rendered,
            storage_path=(
                f"invoices/{snapshot.invoice_id}/cancellations/"
                f"{snapshot.cancellation_id}"
            ),
            metadata={
                "invoice-id": str(snapshot.invoice_id),
                "invoice-number": snapshot.original_number,
                "cancellation-id": str(snapshot.cancellation_id),
                "cancellation-number": snapshot.number,
            },
        )
