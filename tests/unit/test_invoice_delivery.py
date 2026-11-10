from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from leonaid.application.invoice_deliveries import (
    DOCUMENT_WAIT,
    INVOICE_MAIL_SEND_REQUESTED,
    InvoiceDeliveryDocumentFailed,
    InvoiceDeliveryDocumentPending,
)
from leonaid.application.outbox import OutboxWorker
from leonaid.domain.outbox import ClaimedOutboxEvent, RetryPolicy

from datetime import date
from uuid import UUID

from leonaid.application.invoice_deliveries import (
    InvoiceDeliveryContext,
    InvoiceDeliveryService,
)


def golden_context() -> InvoiceDeliveryContext:
    return InvoiceDeliveryContext(
        action_id=UUID("20000000-0000-4000-8000-000000000001"),
        action_name="Krapfentaxi 2026",
        invoice_id=UUID("90000000-0000-4000-8000-000000000001"),
        invoice_number="KT26-0001",
        document_id=UUID("92000000-0000-4000-8000-000000000001"),
        recipient_name="Bäckerei Sonnenseite KG",
        recipient_email="rechnung@sonnenseite.invalid",
        issuer_name="Lions Hilfswerk LeonAid Golden e.V.",
        gross_minor=36000,
        currency="EUR",
        due_on=date(2026, 7, 14),
        payment_reference="KT26-0001",
    )


def test_invoice_delivery_message_is_clear_and_snapshot_based() -> None:
    message = InvoiceDeliveryService._message_text(golden_context())

    assert message == (
        "Guten Tag Bäckerei Sonnenseite KG,\n\n"
        "anbei erhalten Sie die Rechnung KT26-0001 zur Charity-Aktion "
        "„Krapfentaxi 2026“.\n\n"
        "Rechnungsbetrag: 360,00 €\n"
        "Zahlbar bis: 14.07.2026\n"
        "Verwendungszweck: KT26-0001\n\n"
        "Bei Fragen zu dieser Rechnung antworten Sie bitte auf diese E-Mail.\n\n"
        "Vielen Dank für Ihre Unterstützung.\n\n"
        "Freundliche Grüße\n"
        "Lions Hilfswerk LeonAid Golden e.V."
    )


def test_invoice_delivery_money_format_handles_grouping() -> None:
    assert InvoiceDeliveryService._format_money(123456789, "EUR") == "1.234.567,89 €"
    assert InvoiceDeliveryService._format_money(1250, "CHF") == "12,50 CHF"


# --- a mail whose PDF is still being rendered waits; it does not fail -------


class WaitingQueue:
    def __init__(self) -> None:
        self.event: ClaimedOutboxEvent | None = ClaimedOutboxEvent(
            id=uuid4(),
            aggregate_type="invoice_delivery",
            aggregate_id=uuid4(),
            event_type=INVOICE_MAIL_SEND_REQUESTED,
            idempotency_key="invoice-delivery:unit:v1",
            payload={},
            attempts=1,
            claim_token=uuid4(),
            claimed_by="unit",
        )
        self.deferred: list[dict[str, object]] = []
        self.failures: list[dict[str, object]] = []

    async def claim_next(
        self, *, worker_id: str, now: datetime
    ) -> ClaimedOutboxEvent | None:
        event, self.event = self.event, None
        return event

    async def complete(self, **_: object) -> None:
        raise AssertionError("a waiting or failed mail must not complete")

    async def fail(self, **values: object) -> None:
        self.failures.append(values)

    async def defer(self, **values: object) -> None:
        self.deferred.append(values)


class Raising:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        raise self.error


def worker_for(queue: WaitingQueue, error: Exception, now: datetime) -> OutboxWorker:
    return OutboxWorker(
        worker_id="unit",
        queue=queue,
        handlers={INVOICE_MAIL_SEND_REQUESTED: Raising(error)},
        retry_policy=RetryPolicy(max_attempts=5),
        clock=lambda: now,
    )


def test_a_mail_waits_for_its_pdf_without_using_an_attempt() -> None:
    now = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
    queue = WaitingQueue()

    handled = asyncio.run(
        worker_for(queue, InvoiceDeliveryDocumentPending(), now).run_once()
    )

    assert handled is True
    # Back to pending for a moment; never a failure, never a dead letter,
    # however long the rendering takes.
    assert queue.failures == []
    assert len(queue.deferred) == 1
    assert queue.deferred[0]["available_at"] == now + DOCUMENT_WAIT


def test_a_mail_whose_pdf_will_not_come_fails_at_once_and_visibly() -> None:
    now = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
    queue = WaitingQueue()

    asyncio.run(
        worker_for(queue, InvoiceDeliveryDocumentFailed("kein PDF"), now).run_once()
    )

    assert queue.deferred == []
    assert len(queue.failures) == 1
    assert queue.failures[0]["dead_letter"] is True
    assert queue.failures[0]["error_code"] == "invoice_delivery_document_failed"
