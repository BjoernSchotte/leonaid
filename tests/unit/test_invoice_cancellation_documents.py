from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from leonaid.adapters.typst import (
    CANCELLATION_RENDER_VERSION,
    cancellation_render_payload,
    render_payload,
)
from leonaid.application.documents import DocumentStorageHandler
from leonaid.application.invoice_cancellation_documents import (
    InvoiceCancellationDocumentSource,
)
from leonaid.application.invoice_deliveries import (
    InvoiceCancellationDeliveryContext,
    InvoiceDeliveryKind,
    cancellation_delivery_draft,
)
from leonaid.application.invoice_documents import InvoiceDocumentSource
from leonaid.application.object_storage import (
    ObjectLocation,
    ObjectWrite,
    RetrievedObject,
    StoredObject,
)
from leonaid.application.rendered_documents import (
    DocumentRendering,
    RenderedDocument,
)
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import Money
from leonaid.domain.documents import (
    DOCUMENT_RENDER_REQUESTED,
    INVOICE_DOCUMENT_RENDER_REQUESTED,
    GeneratedDocument,
    GeneratedDocumentStatus,
    GeneratedDocumentType,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.invoice_cancellation_documents import InvoiceCancellationDocument
from leonaid.domain.invoice_settlements import InvoiceCancellation
from leonaid.domain.invoices import Invoice, InvoiceStatus
from leonaid.domain.outbox import ClaimedOutboxEvent
from tests.unit.invoice_builders import (
    ACTION_ID,
    ADMIN_ID,
    INVOICE_ID,
    ISSUED_AT,
    commitment,
    document_snapshot,
    profile,
)

CANCELLATION_ID = UUID("97000000-0000-4000-8000-000000000004")
CANCELLED_AT = ISSUED_AT + timedelta(days=9)
PDF = b"%PDF-1.7\n" + b"x" * 64 + b"\n%%EOF\n"
GOLDEN_CANCELLATIONS = (
    Path(__file__).parents[1] / "fixtures" / "golden" / "v1" / "cancellations"
)


def invoice() -> Invoice:
    return Invoice.issue(
        id=INVOICE_ID,
        number="KT26-0017",
        commitment=commitment(),
        profile=profile(),
        approved_by_user_id=ADMIN_ID,
        issued_at=ISSUED_AT,
        service_on=date(2026, 11, 15),
    )


def document(received_minor: int = 0) -> InvoiceCancellationDocument:
    return InvoiceCancellationDocument.issue(
        cancellation_id=CANCELLATION_ID,
        number="KT26-0042",
        invoice=invoice(),
        received=Money(received_minor, "EUR"),
        issued_at=CANCELLED_AT,
    )


def test_cancellation_copies_the_invoice_and_names_it() -> None:
    original = invoice()
    cancellation = document()

    assert cancellation.number == "KT26-0042"
    assert cancellation.original_number == "KT26-0017"
    assert cancellation.original_issued_on == original.issued_on
    # The club's day of the cancellation, not the invoice's date.
    assert cancellation.issued_on == date(2026, 10, 21)
    assert cancellation.issuer == original.issuer
    assert cancellation.recipient == original.recipient
    assert cancellation.lines == original.lines
    assert cancellation.tax_treatment is original.tax_treatment
    assert cancellation.tax_note == original.tax_note


def test_stored_amounts_stay_positive_and_only_the_print_is_negative() -> None:
    cancellation = document()

    assert cancellation.gross == Money(10_800, "EUR")
    assert cancellation.lines[0].quantity == 3
    assert cancellation.printed_minor(cancellation.gross) == -10_800
    assert cancellation.printed_minor(cancellation.tax) == 0
    stored = cancellation.payload()
    assert stored["totals"] == {
        "netMinor": 10_800,
        "taxMinor": 0,
        "grossMinor": 10_800,
        "currency": "EUR",
    }
    assert "-" not in json.dumps(stored["totals"])


def test_snapshot_round_trips_and_refuses_unknown_schema() -> None:
    cancellation = document(received_minor=7_200)

    assert InvoiceCancellationDocument.from_payload(cancellation.payload()) == (
        cancellation
    )
    with pytest.raises(DomainInvariantError) as error:
        InvoiceCancellationDocument.from_payload(
            {**cancellation.payload(), "schemaVersion": 2}
        )
    assert error.value.code == "invoice_cancellation_document_schema_unsupported"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"number": "KT26-0017"}, "invoice_cancellation_number_reused"),
        ({"number": "kt26-42"}, "invoice_cancellation_number_invalid"),
        ({"issued_on": date(2026, 10, 11)}, "invoice_cancellation_date_invalid"),
        ({"lines": ()}, "invoice_cancellation_lines_required"),
        ({"gross": Money(10_799, "EUR")}, "invoice_cancellation_totals_invalid"),
        ({"received": Money(0, "CHF")}, "invoice_cancellation_currency_mismatch"),
    ],
)
def test_inconsistent_document_is_rejected(
    changes: dict[str, object], code: str
) -> None:
    with pytest.raises(DomainInvariantError) as error:
        replace(document(), **changes)  # type: ignore[arg-type]

    assert error.value.code == code


def test_render_payload_prints_the_minus_sign_and_the_reference() -> None:
    payload = cancellation_render_payload(document())

    assert payload["renderVersion"] == CANCELLATION_RENDER_VERSION
    assert payload["title"] == "Stornorechnung KT26-0042"
    assert payload["reference"] == "zur Rechnung KT26-0017 vom 12.10.2026"
    assert payload["introduction"] == (
        "Mit dieser Stornorechnung heben wir die Rechnung KT26-0017 vom "
        "12.10.2026 vollständig auf. Die Beträge der Rechnung werden mit "
        "umgekehrtem Vorzeichen ausgewiesen."
    )
    assert payload["issuedOn"] == "21.10.2026"
    assert payload["lines"] == [
        {
            "description": "Krapfenbox",
            "quantity": "3",
            "unit": "Boxen",
            "unitPrice": "-36,00 EUR",
            "net": "-108,00 EUR",
            "tax": "0,00 EUR",
            "gross": "-108,00 EUR",
        }
    ]
    assert payload["gross"] == "-108,00 EUR"
    assert payload["tax"] == "0,00 EUR"
    assert payload["closing"] == (
        "Aus der Rechnung KT26-0017 ist kein Betrag mehr zu zahlen."
    )
    # No payment request and no reason on a cancellation invoice.
    assert "paymentDetails" not in payload
    assert "reason" not in payload


def test_render_payload_names_received_money_and_the_refund() -> None:
    payload = cancellation_render_payload(document(received_minor=7_200))

    assert payload["closing"] == (
        "Auf die Rechnung KT26-0017 haben wir 72,00 EUR erhalten. "
        "Die Erstattung erfolgt gesondert."
    )


def test_package_lines_print_their_unit_on_both_documents() -> None:
    snapshot = document_snapshot()
    packages = replace(
        snapshot,
        lines=tuple(
            replace(line, unit=OfferingUnit.PACKAGE) for line in snapshot.lines
        ),
    )
    single = replace(
        packages.lines[0],
        quantity=1,
        gross=packages.lines[0].unit_price_gross,
        net=packages.lines[0].unit_price_gross,
    )

    lines = render_payload(packages)["lines"]
    assert isinstance(lines, list)
    assert lines[0]["unit"] == "Pakete"
    one = render_payload(
        replace(
            packages,
            lines=(single,),
            net=single.net,
            gross=single.gross,
        )
    )["lines"]
    assert isinstance(one, list)
    assert one[0]["unit"] == "Paket"


def test_golden_cancellation_fixtures_are_valid_documents() -> None:
    fixtures = sorted(GOLDEN_CANCELLATIONS.glob("KT26-*.json"))

    assert [path.stem for path in fixtures] == ["KT26-0004", "KT26-0005"]
    for path in fixtures:
        payload = json.loads(path.read_text(encoding="utf-8"))
        parsed = InvoiceCancellationDocument.from_payload(payload)
        assert parsed.payload() == payload
        assert parsed.number == path.stem
    unpaid, paid = (
        InvoiceCancellationDocument.from_payload(
            json.loads(path.read_text(encoding="utf-8"))
        )
        for path in fixtures
    )
    assert not unpaid.refund_due and paid.refund_due


# --- the storage handler picks the source by document type -----------------


def generated(document_type: GeneratedDocumentType) -> GeneratedDocument:
    return GeneratedDocument(
        id=uuid4(),
        action_id=ACTION_ID,
        commitment_id=None,
        invoice_id=INVOICE_ID,
        twenty_company_id=None,
        twenty_person_id=None,
        document_type=document_type,
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
        created_at=CANCELLED_AT,
    )


class Documents:
    def __init__(self, item: GeneratedDocument) -> None:
        self.item = item
        self.available: dict[str, object] | None = None

    async def document(self, document_id: UUID) -> GeneratedDocument | None:
        return self.item if document_id == self.item.id else None

    async def mark_available(self, **values: object) -> GeneratedDocument:
        self.available = values
        return self.item

    async def invoice_snapshot(self, invoice_id: UUID) -> object:
        return document_snapshot()

    async def invoice_cancellation_document(
        self, invoice_id: UUID
    ) -> InvoiceCancellationDocument | None:
        return document() if invoice_id == INVOICE_ID else None


class Storage:
    bucket = "leonaid"

    def __init__(self) -> None:
        self.writes: list[ObjectWrite] = []

    async def ensure_private_versioned_bucket(self) -> None:
        return None

    async def put_immutable(self, write: ObjectWrite) -> StoredObject:
        self.writes.append(write)
        return StoredObject(
            location=ObjectLocation(
                bucket=write.location.bucket, key=write.location.key, version_id="v1"
            ),
            media_type=write.media_type,
            size_bytes=len(write.content),
            sha256=write.sha256,
            metadata=write.metadata,
        )

    async def get(self, location: ObjectLocation) -> RetrievedObject:
        write = self.writes[-1]
        return RetrievedObject(
            stored=await self._stored(write),
            content=write.content,
        )

    async def _stored(self, write: ObjectWrite) -> StoredObject:
        return StoredObject(
            location=ObjectLocation(
                bucket=write.location.bucket, key=write.location.key, version_id="v1"
            ),
            media_type=write.media_type,
            size_bytes=len(write.content),
            sha256=write.sha256,
            metadata=write.metadata,
        )


class Renderer:
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.rendered: list[object] = []

    def render(self, snapshot: object) -> RenderedDocument:
        self.rendered.append(snapshot)
        return RenderedDocument.create(
            content=PDF, filename=self.filename, render_version="proof-v1"
        )


def event(item: GeneratedDocument, event_type: str) -> ClaimedOutboxEvent:
    return ClaimedOutboxEvent(
        id=uuid4(),
        aggregate_type="generated_document",
        aggregate_id=item.id,
        event_type=event_type,
        idempotency_key=f"document-render:{item.id}:v1",
        payload={"documentId": str(item.id)},
        attempts=0,
        claim_token=uuid4(),
        claimed_by="unit",
    )


def handler(
    documents: Documents, storage: Storage
) -> tuple[DocumentStorageHandler, Renderer, Renderer]:
    invoices = Renderer("Rechnung-KT26-0001.pdf")
    cancellations = Renderer("Stornorechnung-KT26-0042.pdf")
    return (
        DocumentStorageHandler(
            repository=documents,  # type: ignore[arg-type]
            sources={
                GeneratedDocumentType.INVOICE_PDF: InvoiceDocumentSource(
                    snapshots=documents,  # type: ignore[arg-type]
                    renderer=invoices,  # type: ignore[arg-type]
                ),
                GeneratedDocumentType.INVOICE_CANCELLATION_PDF: (
                    InvoiceCancellationDocumentSource(
                        documents=documents, renderer=cancellations
                    )
                ),
            },
            storage=storage,  # type: ignore[arg-type]
        ),
        invoices,
        cancellations,
    )


def test_cancellation_document_is_rendered_from_its_snapshot_and_stored() -> None:
    item = generated(GeneratedDocumentType.INVOICE_CANCELLATION_PDF)
    documents, storage = Documents(item), Storage()
    worker, invoices, cancellations = handler(documents, storage)

    asyncio.run(worker.handle(event(item, DOCUMENT_RENDER_REQUESTED)))

    assert invoices.rendered == [] and cancellations.rendered == [document()]
    write = storage.writes[0]
    assert write.location.key == (
        f"actions/{ACTION_ID}/invoices/{INVOICE_ID}/cancellations/"
        f"{CANCELLATION_ID}/v1/{write.sha256}.pdf"
    )
    assert write.metadata["document-type"] == "invoice_cancellation_pdf"
    assert write.metadata["cancellation-number"] == "KT26-0042"
    assert write.metadata["invoice-number"] == "KT26-0017"
    assert documents.available is not None
    assert documents.available["filename"] == "Stornorechnung-KT26-0042.pdf"


def test_invoice_document_keeps_its_key_and_its_first_event_name() -> None:
    item = generated(GeneratedDocumentType.INVOICE_PDF)
    documents, storage = Documents(item), Storage()
    worker, invoices, cancellations = handler(documents, storage)

    asyncio.run(worker.handle(event(item, INVOICE_DOCUMENT_RENDER_REQUESTED)))

    assert len(invoices.rendered) == 1 and cancellations.rendered == []
    write = storage.writes[0]
    snapshot = document_snapshot()
    assert write.location.key == (
        f"actions/{ACTION_ID}/invoices/{snapshot.invoice_id}/v1/{write.sha256}.pdf"
    )
    assert write.metadata["invoice-number"] == snapshot.number


def test_a_type_without_source_and_a_foreign_event_are_refused() -> None:
    item = generated(GeneratedDocumentType.INVOICE_CANCELLATION_PDF)
    documents, storage = Documents(item), Storage()
    only_invoices = DocumentStorageHandler(
        repository=documents,  # type: ignore[arg-type]
        sources={},
        storage=storage,  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="unbekannten Dokumenttyp"):
        asyncio.run(only_invoices.handle(event(item, DOCUMENT_RENDER_REQUESTED)))
    with pytest.raises(ValueError, match="fremden Ereignistyp"):
        asyncio.run(only_invoices.handle(event(item, "mail.send.v1")))
    assert storage.writes == []


def test_a_new_kind_only_needs_its_source() -> None:
    """What the donation documents rely on: no handler change per kind."""

    class PledgeSource:
        async def render(self, document: GeneratedDocument) -> DocumentRendering:
            return DocumentRendering(
                rendered=RenderedDocument.create(
                    content=PDF,
                    filename="Spendenzusage-SP26-0001.pdf",
                    render_version="proof-v1",
                ),
                storage_path="donations/1",
                metadata={"donation-number": "SP26-0001"},
            )

    item = generated(GeneratedDocumentType.INVOICE_PDF)
    documents, storage = Documents(item), Storage()
    worker = DocumentStorageHandler(
        repository=documents,  # type: ignore[arg-type]
        sources={GeneratedDocumentType.INVOICE_PDF: PledgeSource()},
        storage=storage,  # type: ignore[arg-type]
    )

    asyncio.run(worker.handle(event(item, DOCUMENT_RENDER_REQUESTED)))

    assert storage.writes[0].location.key.startswith(
        f"actions/{ACTION_ID}/donations/1/v1/"
    )
    assert storage.writes[0].metadata["donation-number"] == "SP26-0001"


# --- refund marker ----------------------------------------------------------


def cancellation(received_minor: int) -> InvoiceCancellation:
    return InvoiceCancellation(
        id=CANCELLATION_ID,
        action_id=ACTION_ID,
        invoice_id=INVOICE_ID,
        original_status=InvoiceStatus.PAID,
        reason="Sponsor hat die Bestellung zurückgezogen",
        requested_by_user_id=ADMIN_ID,
        requested_at=CANCELLED_AT,
        number="KT26-0042",
        issued_on=date(2026, 10, 21),
        received=Money(received_minor, "EUR"),
    )


def test_refund_is_open_while_received_money_is_not_marked_as_returned() -> None:
    open_refund = cancellation(7_200)
    settled_at = CANCELLED_AT + timedelta(days=2)

    assert open_refund.refund_open
    assert not cancellation(0).refund_open
    refund = open_refund.settle_refund(
        settled_on=date(2026, 10, 22),
        note="  Überweisung   vom Vereinskonto ",
        settled_by_user_id=ADMIN_ID,
        settled_at=settled_at,
    )
    assert refund.note == "Überweisung vom Vereinskonto"
    assert not replace(open_refund, refund=refund).refund_open


@pytest.mark.parametrize(
    ("received_minor", "settled_on", "code"),
    [
        (0, date(2026, 10, 22), "invoice_refund_not_due"),
        (7_200, date(2026, 10, 20), "invoice_refund_before_cancellation"),
        (7_200, date(2026, 10, 24), "invoice_refund_future_date"),
    ],
)
def test_refund_rules(received_minor: int, settled_on: date, code: str) -> None:
    with pytest.raises(DomainInvariantError) as error:
        cancellation(received_minor).settle_refund(
            settled_on=settled_on,
            note=None,
            settled_by_user_id=ADMIN_ID,
            settled_at=CANCELLED_AT + timedelta(days=2),
        )

    assert error.value.code == code


def test_refund_is_recorded_once() -> None:
    settled_at = datetime(2026, 10, 23, 9, tzinfo=timezone.utc)
    first = cancellation(7_200)
    refund = first.settle_refund(
        settled_on=date(2026, 10, 22),
        note=None,
        settled_by_user_id=ADMIN_ID,
        settled_at=settled_at,
    )

    with pytest.raises(DomainInvariantError) as error:
        replace(first, refund=refund).settle_refund(
            settled_on=date(2026, 10, 22),
            note=None,
            settled_by_user_id=ADMIN_ID,
            settled_at=settled_at,
        )
    assert error.value.code == "invoice_refund_already_settled"


def test_number_and_date_of_the_document_belong_together() -> None:
    with pytest.raises(DomainInvariantError) as error:
        replace(cancellation(0), issued_on=None)

    assert error.value.code == "invoice_cancellation_document_incomplete"
    older = replace(cancellation(0), number=None, issued_on=None)
    assert not older.has_document


# --- cover mail --------------------------------------------------------------


def delivery_context(received_minor: int) -> InvoiceCancellationDeliveryContext:
    return InvoiceCancellationDeliveryContext(
        action_id=ACTION_ID,
        action_name="Krapfentaxi 2026",
        invoice_id=INVOICE_ID,
        invoice_number="KT26-0017",
        cancellation_number="KT26-0042",
        document_id=uuid4(),
        recipient_name="Bäckerei Sonnenseite KG",
        recipient_email="rechnung@sonnenseite.invalid",
        issuer_name="Lions Hilfswerk LeonAid Golden e.V.",
        received_minor=received_minor,
        currency="EUR",
    )


def test_cover_mail_follows_the_agreed_wording() -> None:
    draft = cancellation_delivery_draft(
        delivery_context(0),
        idempotency_key="unit:cancellation-delivery",
        requested_by_user_id=ADMIN_ID,
        requested_at=CANCELLED_AT,
    )

    assert draft.kind is InvoiceDeliveryKind.INVOICE_CANCELLATION
    assert draft.subject == (
        "Stornorechnung KT26-0042 zur Rechnung KT26-0017 · Krapfentaxi 2026"
    )
    assert (
        "anbei erhalten Sie die Stornorechnung zu Ihrer Rechnung KT26-0017. "
        "Die Rechnung ist damit aufgehoben." in draft.text
    )
    assert "Aus der Rechnung KT26-0017 ist kein Betrag mehr zu zahlen." in draft.text
    assert not draft.document_may_be_pending


def test_cover_mail_of_a_paid_invoice_names_the_refund() -> None:
    draft = cancellation_delivery_draft(
        delivery_context(7_200),
        idempotency_key="unit:cancellation-delivery-paid",
        requested_by_user_id=ADMIN_ID,
        requested_at=CANCELLED_AT,
        document_may_be_pending=True,
    )

    assert (
        "Auf die Rechnung KT26-0017 haben wir 72,00 € erhalten. "
        "Die Erstattung erfolgt gesondert." in draft.text
    )
    assert "kein Betrag mehr" not in draft.text
    assert draft.document_may_be_pending
