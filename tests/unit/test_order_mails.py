"""Order confirmation and cancellation notice: jobs, texts and handler rules."""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any
from uuid import UUID, uuid4

import pytest

from leonaid.application.links import LinkBuilder
from leonaid.application.order_mails import (
    LATE_REASONS,
    RECIPIENT_LIMIT,
    RECIPIENT_WINDOW,
    ORDER_CANCELLATION_MAIL,
    ORDER_CONFIRMATION_MAIL,
    OrderCancellationFacts,
    OrderMailError,
    OrderMailFacts,
    OrderMailHandler,
    OrderMailKind,
    OrderMailLinkResolver,
    OrderMailLinks,
    MailNotDueReason,
    delivery_day_not_due_reason,
    confirmation_not_due_reason,
    mail_key_sequence,
    delivery_window_label,
    limit_digest,
    mail_due,
    mail_not_due_reason,
    mailbox_key,
    order_mail_event,
    order_mail_key,
    render_delivery_day,
    render_order_cancellation,
    render_order_confirmation,
)
from leonaid.application.delivery_day_mails import (
    DeliveryDayMailSweep,
    DueDeliveryDayMail,
    delivery_day_event,
    delivery_day_links,
)
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import (
    BuyerSnapshot,
    Commitment,
    CommitmentLine,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
    Money,
)
from leonaid.domain.delivery import DeliveryContactSnapshot
from leonaid.domain.legal_configuration import LegalConfigurationVersion
from leonaid.domain.outbox import ClaimedOutboxEvent, RetryPolicy
from leonaid.domain.text import has_link_markers, has_unsafe_characters, single_line
from leonaid.application.outbox import OutboxWorker
from tests.unit.test_legal_configuration import valid_draft

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
ORDER_ID = UUID("30000000-0000-4000-8000-0000000000aa")
WINDOW_ID = UUID("60000000-0000-4000-8000-000000000001")
LINKS = OrderMailLinks(
    campaign_url="https://krapfen.leonaid.invalid/krapfentaxi",
    privacy_url="https://krapfen.leonaid.invalid/datenschutz",
    imprint_url="https://krapfen.leonaid.invalid/impressum",
)
ORDERED_AT = datetime(2026, 2, 10, 8, 30, tzinfo=timezone.utc)
CANCELLED_AT = datetime(2026, 2, 11, 9, 0, tzinfo=timezone.utc)


def legal() -> LegalConfigurationVersion:
    return LegalConfigurationVersion(
        id=uuid4(),
        version=3,
        configuration=valid_draft(),
        created_by_user_id=uuid4(),
        created_by_display_name="Admin",
        created_at=ORDERED_AT,
    )


def order(**changes: Any) -> Commitment:
    base = Commitment(
        id=ORDER_ID,
        action_id=ACTION_ID,
        source=CommitmentSource.PUBLIC_FORM,
        status=CommitmentStatus.REVIEW_READY,
        buyer=BuyerSnapshot(
            party_kind=CommitmentPartyKind.COMPANY,
            twenty_id=uuid4(),
            display_name="CRM Musterwerk Holding GmbH & Co. KG",
            email="einkauf@musterwerk.invalid",
        ),
        invoice_recipient=InvoiceRecipientSnapshot(
            recipient_name="Musterwerk GmbH",
            street_line_1="Rechnungsweg 2",
            postal_code="86150",
            city="Augsburg",
            email="einkauf@musterwerk.invalid",
        ),
        delivery_recipient=DeliveryRecipientSnapshot(
            recipient_name="Musterwerk Empfang",
            street_line_1="Lieferstraße 7",
            postal_code="86152",
            city="Augsburg",
        ),
        delivery_window_id=WINDOW_ID,
        delivery_window_snapshot={
            "windowId": str(WINDOW_ID),
            "startsAt": "2026-02-14T08:00:00+00:00",
            "endsAt": "2026-02-14T10:00:00+00:00",
            "timezone": "Europe/Berlin",
        },
        delivery_contact=DeliveryContactSnapshot(
            name="Pforte Herr Geheim",
            phone="+49 821 999999",
            driver_note="Hofeinfahrt links",
        ),
        message="Bitte am Hintereingang klingeln, Code 4711.",
        public_reference=f"LA-{ORDER_ID.hex.upper()}",
        lines=(
            CommitmentLine(
                id=uuid4(),
                offering_id=uuid4(),
                description_snapshot="Krapfen-Box",
                quantity=3,
                unit_snapshot=OfferingUnit.BOX,
                pieces_per_unit_snapshot=24,
                unit_price=Money(3600, "EUR"),
                line_total=Money(10800, "EUR"),
            ),
            CommitmentLine(
                id=uuid4(),
                offering_id=uuid4(),
                description_snapshot="Einzelkrapfen",
                quantity=1,
                unit_snapshot=OfferingUnit.PIECE,
                pieces_per_unit_snapshot=None,
                unit_price=Money(1250, "EUR"),
                line_total=Money(1250, "EUR"),
            ),
        ),
        total=Money(12050, "EUR"),
    )
    return replace(base, **changes)


def facts(
    commitment: Commitment | None = None,
    *,
    cancellation: OrderCancellationFacts | None = None,
    internal_order_mails: bool = False,
    action_status: str = "active",
    invoicing: bool = True,
    drop_state: str | None = None,
) -> OrderMailFacts:
    return OrderMailFacts(
        action_name="Krapfentaxi 2026",
        commitment=commitment or order(),
        ordered_at=ORDERED_AT,
        cancellation=cancellation,
        internal_order_mails=internal_order_mails,
        action_status=action_status,
        invoicing=invoicing,
        drop_state=drop_state,
    )


def claimed(kind: OrderMailKind, commitment_id: UUID = ORDER_ID) -> ClaimedOutboxEvent:
    event = order_mail_event(
        kind, action_id=ACTION_ID, commitment_id=commitment_id, links=LINKS
    )
    return ClaimedOutboxEvent(
        id=event.id,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        event_type=event.event_type,
        idempotency_key=event.idempotency_key,
        payload=json.loads(json.dumps(event.payload)),
        attempts=1,
        claim_token=uuid4(),
        claimed_by="unit",
    )


def test_job_is_one_per_order_and_kind_and_carries_no_personal_data() -> None:
    first = order_mail_event(
        OrderMailKind.CONFIRMATION,
        action_id=ACTION_ID,
        commitment_id=ORDER_ID,
        links=LINKS,
    )
    again = order_mail_event(
        OrderMailKind.CONFIRMATION,
        action_id=ACTION_ID,
        commitment_id=ORDER_ID,
        links=LINKS,
    )
    cancellation = order_mail_event(
        OrderMailKind.CANCELLATION,
        action_id=ACTION_ID,
        commitment_id=ORDER_ID,
        links=LINKS,
    )

    assert first == again
    assert first.event_type == ORDER_CONFIRMATION_MAIL
    assert first.idempotency_key == f"order-confirmation-mail:{ORDER_ID}"
    assert cancellation.event_type == ORDER_CANCELLATION_MAIL
    assert cancellation.idempotency_key == f"order-cancellation-mail:{ORDER_ID}"
    assert cancellation.id != first.id
    assert first.aggregate_type == "commitment"
    assert first.aggregate_id == ORDER_ID
    assert first.payload == {
        "actionId": str(ACTION_ID),
        "commitmentId": str(ORDER_ID),
        "campaignUrl": LINKS.campaign_url,
        "privacyUrl": LINKS.privacy_url,
        "imprintUrl": LINKS.imprint_url,
    }
    assert "@" not in json.dumps(first.payload)


def test_confirmation_lists_the_order_the_club_and_the_links() -> None:
    mail = render_order_confirmation(facts(), legal(), LINKS)
    reference = f"LA-{ORDER_ID.hex.upper()}"

    assert mail.recipient == "einkauf@musterwerk.invalid"
    assert mail.subject == f"Ihre Bestellung bei Krapfentaxi 2026 · {reference}"
    text = mail.text
    for expected in (
        "Guten Tag,",
        "vielen Dank für Ihre Bestellung bei der Aktion „Krapfentaxi 2026“. "
        "Wir haben sie am 10.02.2026 um 09:30 Uhr erhalten.",
        f"Bestellnummer: {reference}",
        "- Krapfen-Box: 3 Boxen (72 Stück) × 36,00 € = 108,00 €",
        "- Einzelkrapfen: 1 Stück × 12,50 € = 12,50 €",
        "Gesamtbetrag: 120,50 €",
        "Lieferfenster: Samstag, 14.02.2026, 09:00–11:00 Uhr",
        "Lieferanschrift:\n  Musterwerk Empfang\n  Lieferstraße 7\n  86152 Augsburg",
        "Rechnungsanschrift:\n  Musterwerk GmbH\n  Rechnungsweg 2\n  86150 Augsburg",
        "Zur Aktion: https://krapfen.leonaid.invalid/krapfentaxi",
        "Bei Fragen zu Ihrer Bestellung erreichen Sie uns unter "
        "rechnung@hilfswerk.test oder telefonisch unter +49 821 123456.",
        "Datenschutzerklärung: https://krapfen.leonaid.invalid/datenschutz",
        "Anbieter\nLions Hilfswerk Augsburg e.V.\nLöwenweg 12, 86150 Augsburg",
        "Vertreten durch: Vorstand: Erika Muster (Präsidentin)",
        "Vereinsregister: Amtsgericht Augsburg, VR 1234",
        "Impressum: https://krapfen.leonaid.invalid/impressum",
        "Datenschutz: https://krapfen.leonaid.invalid/datenschutz",
    ):
        assert expected in text, expected
    # Internal or third-party data never reaches the buyer.
    for forbidden in (
        "Hintereingang",
        "Hofeinfahrt links",
        "4711",
        "Pforte",
        "999999",
        "CRM Musterwerk Holding",
        str(ACTION_ID),
    ):
        assert forbidden not in text, forbidden


def test_confirmation_without_delivery_or_campaign_link_omits_those_blocks() -> None:
    mail = render_order_confirmation(
        facts(
            order(
                delivery_window_id=None,
                delivery_window_snapshot=None,
                delivery_recipient=None,
                delivery_contact=None,
            )
        ),
        legal(),
        replace(LINKS, campaign_url=None),
    )

    assert "Lieferfenster" not in mail.text
    assert "Lieferanschrift" not in mail.text
    assert "Zur Aktion" not in mail.text
    assert "Rechnungsanschrift:" in mail.text


def test_cancellation_names_the_order_and_the_cancelled_invoice() -> None:
    mail = render_order_cancellation(
        facts(
            cancellation=OrderCancellationFacts(
                cancelled_at=CANCELLED_AT, invoice_number="KT26-0007"
            )
        ),
        legal(),
        LINKS,
    )
    reference = f"LA-{ORDER_ID.hex.upper()}"

    assert mail.subject == (
        f"Stornierung Ihrer Bestellung bei Krapfentaxi 2026 · {reference}"
    )
    for expected in (
        "Ihre Bestellung vom 10.02.2026 bei der Aktion „Krapfentaxi 2026“ wurde "
        "am 11.02.2026 storniert. Sie wird nicht geliefert.",
        f"Bestellnummer: {reference}",
        "Stornierte Bestellung\n- Krapfen-Box: 3 Boxen (72 Stück)",
        "Gesamtbetrag: 120,50 €",
        "Die Rechnung KT26-0007 zu dieser Bestellung wurde ebenfalls storniert. "
        "Bitte überweisen Sie den Betrag nicht.",
        "Bei Fragen zur Stornierung erreichen Sie uns unter",
        "Impressum: https://krapfen.leonaid.invalid/impressum",
    ):
        assert expected in mail.text, expected
    assert "Hintereingang" not in mail.text


def test_cancellation_without_invoice_has_no_invoice_sentence() -> None:
    mail = render_order_cancellation(
        facts(cancellation=OrderCancellationFacts(cancelled_at=CANCELLED_AT)),
        legal(),
        LINKS,
    )

    assert "Rechnung" not in mail.text.split("Bestellnummer")[1].split("Bei Fragen")[0]


def test_cancellation_needs_its_cancellation_record() -> None:
    with pytest.raises(OrderMailError) as error:
        render_order_cancellation(facts(), legal(), LINKS)
    assert error.value.code == "order_mail_cancellation_missing"


def test_window_label_uses_the_window_zone_and_shows_a_second_day() -> None:
    assert (
        delivery_window_label(
            {
                "windowId": str(WINDOW_ID),
                # Summer time: UTC+2.
                "startsAt": "2026-07-04T20:00:00+00:00",
                "endsAt": "2026-07-04T23:00:00+00:00",
            }
        )
        == "Samstag, 04.07.2026, 22:00–Sonntag, 05.07.2026, 01:00 Uhr"
    )


class RecordingSender:
    def __init__(self) -> None:
        self.events: list[ClaimedOutboxEvent] = []

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        self.events.append(event)


class Reader:
    def __init__(
        self,
        value: OrderMailFacts | None,
        *,
        sent: bool = False,
        recent: int = 0,
    ) -> None:
        self.value = value
        self.sent = sent
        self.recent = recent
        self.calls: list[tuple[UUID, OrderMailKind]] = []
        self.counted: list[tuple[str, str, datetime]] = []
        self.locks: list[str] = []
        self.locked = False
        # Ledger keys of the mail: its first key and its resends.
        self.sent_keys_value: tuple[str, ...] = ()

    async def facts(
        self, commitment_id: UUID, kind: OrderMailKind
    ) -> OrderMailFacts | None:
        self.calls.append((commitment_id, kind))
        return self.value

    async def was_sent(self, idempotency_key: str) -> bool:
        return self.sent

    async def sent_keys(self, first_key: str) -> tuple[str, ...]:
        return tuple(key for key in self.sent_keys_value if key.startswith(first_key))

    async def recent_order_mails(
        self, *, recipient_sha256: str, mailbox: str, since: datetime
    ) -> int:
        assert self.locked, "the limit is checked under the recipient lock"
        self.counted.append((recipient_sha256, mailbox, since))
        return self.recent

    @asynccontextmanager
    async def recipient_lock(self, digest: str) -> Any:
        self.locks.append(digest)
        self.locked = True
        try:
            yield
        finally:
            self.locked = False


class Legal:
    def __init__(self, value: LegalConfigurationVersion | None) -> None:
        self.value = value

    async def active_configuration(self) -> LegalConfigurationVersion | None:
        return self.value


def handler(
    kind: OrderMailKind,
    value: OrderMailFacts | None,
    sender: RecordingSender,
    legal_value: LegalConfigurationVersion | None = None,
) -> OrderMailHandler:
    return OrderMailHandler(
        kind,
        reader=Reader(value),
        legal_configuration=Legal(legal_value or legal()),
        sender=sender,
        clock=lambda: ORDERED_AT,
    )


@pytest.mark.asyncio
async def test_handler_sends_the_rendered_mail_under_the_job_key() -> None:
    sender = RecordingSender()
    event = claimed(OrderMailKind.CONFIRMATION)

    await handler(OrderMailKind.CONFIRMATION, facts(), sender).handle(event)

    assert len(sender.events) == 1
    sent = sender.events[0]
    # The SMTP ledger deduplicates by this key across retries and claims.
    assert sent.idempotency_key == event.idempotency_key
    assert sent.id == event.id
    assert set(sent.payload) == {"to", "subject", "text"}
    assert sent.payload["to"] == "einkauf@musterwerk.invalid"
    assert "Gesamtbetrag: 120,50 €" in str(sent.payload["text"])
    # The stored job keeps only ids and links.
    assert "to" not in event.payload


@pytest.mark.asyncio
async def test_handler_sends_the_cancellation_notice() -> None:
    sender = RecordingSender()
    value = facts(cancellation=OrderCancellationFacts(cancelled_at=CANCELLED_AT))

    await handler(OrderMailKind.CANCELLATION, value, sender).handle(
        claimed(OrderMailKind.CANCELLATION)
    )

    assert "storniert" in str(sender.events[0].payload["text"])


@pytest.mark.parametrize(
    "value",
    [
        None,
        facts(order(source=CommitmentSource.ADMIN)),
        facts(
            order(source=CommitmentSource.ACQUISITION, status=CommitmentStatus.DRAFT),
            internal_order_mails=True,
        ),
        facts(
            order(
                buyer=BuyerSnapshot(
                    party_kind=CommitmentPartyKind.COMPANY,
                    twenty_id=uuid4(),
                    display_name="Anonymisiert",
                    email=None,
                )
            )
        ),
    ],
    ids=["order-gone", "internal-switched-off", "internal-draft", "erased"],
)
@pytest.mark.asyncio
async def test_handler_completes_without_mail_when_nothing_is_due(
    value: OrderMailFacts | None,
) -> None:
    sender = RecordingSender()

    await handler(OrderMailKind.CONFIRMATION, value, sender).handle(
        claimed(OrderMailKind.CONFIRMATION)
    )

    assert sender.events == []


@pytest.mark.asyncio
async def test_handler_retries_while_no_legal_configuration_is_active() -> None:
    sender = RecordingSender()
    mail = OrderMailHandler(
        OrderMailKind.CONFIRMATION,
        reader=Reader(facts()),
        legal_configuration=Legal(None),
        sender=sender,
        clock=lambda: ORDERED_AT,
    )

    with pytest.raises(OrderMailError) as error:
        await mail.handle(claimed(OrderMailKind.CONFIRMATION))

    assert error.value.code == "order_mail_legal_configuration_missing"
    assert sender.events == []


@pytest.mark.asyncio
async def test_handler_rejects_a_payload_for_another_order() -> None:
    event = claimed(OrderMailKind.CONFIRMATION)
    tampered = replace(event, payload={**event.payload, "commitmentId": str(uuid4())})

    with pytest.raises(OrderMailError) as error:
        await handler(OrderMailKind.CONFIRMATION, facts(), RecordingSender()).handle(
            tampered
        )

    assert error.value.code == "order_mail_payload_invalid"


class Connection:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row

    async def fetchrow(self, _query: str, *_arguments: object) -> object:
        return self.row


class Pool:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.connection = Connection(row)

    @asynccontextmanager
    async def _acquire(self) -> Any:
        yield self.connection

    def acquire(self) -> Any:
        return self._acquire()


@pytest.mark.asyncio
async def test_link_resolver_puts_legal_pages_on_the_public_host() -> None:
    links = LinkBuilder(
        admin_base_url="https://app.leonaid.invalid",
        site_base_url="https://site.leonaid.invalid",
    )

    async def campaign(action_id: UUID) -> str | None:
        assert action_id == ACTION_ID
        return "https://lionsopen.invalid/2026/"

    assert await OrderMailLinkResolver(links, campaign).for_action(
        ACTION_ID
    ) == OrderMailLinks(
        campaign_url="https://lionsopen.invalid/2026/",
        privacy_url="https://site.leonaid.invalid/datenschutz",
        imprint_url="https://site.leonaid.invalid/impressum",
    )


# --- Injection, limit, cancelled order, issuer country (review of #111) ---

PHISHING = (
    "Max\n\nWichtig: Bitte überweisen Sie den Betrag vorab auf "
    "DE12 3456 7890, sonst verfällt Ihre Bestellung.\r\n\t\u202eNI\u202c"
)


def test_stored_free_text_stays_on_its_own_line_without_format_characters() -> None:
    poisoned = order(
        delivery_recipient=DeliveryRecipientSnapshot(
            recipient_name=PHISHING,
            street_line_1="Weg 1\n\nNeuer Absatz",
            postal_code="86150\u200b",
            city="Augs\u202eburg",
        ),
    )

    text = render_order_confirmation(facts(poisoned), legal(), LINKS).text
    block = text.split("Lieferanschrift:\n")[1].split("\n\n")[0].split("\n")

    assert block == [
        "  Max Wichtig: Bitte überweisen Sie den Betrag vorab auf DE12 3456 7890, "
        "sonst verfällt Ihre Bestellung. NI",
        "  Weg 1 Neuer Absatz",
        "  86150 Augsburg",
    ]
    assert "\n\nWichtig" not in text
    assert all(
        character not in text
        for character in ("\u202e", "\u202c", "\u200b", "\t", "\r")
    )


def test_action_name_cannot_break_the_subject_line() -> None:
    mail = render_order_confirmation(
        replace(facts(), action_name="Krapfentaxi\r\nBcc: opfer@example.invalid"),
        legal(),
        LINKS,
    )

    assert "\n" not in mail.subject and "\r" not in mail.subject
    assert mail.subject.startswith("Ihre Bestellung bei Krapfentaxi Bcc:")


def test_single_line_and_unsafe_character_check() -> None:
    assert single_line(" a\tb\n\nc\u2028d\u202ee\u200d ") == "a b c de"
    assert has_unsafe_characters("Max\nMuster")
    assert has_unsafe_characters("Augs\u202eburg")
    assert has_unsafe_characters("Zero\u200bwidth")
    assert not has_unsafe_characters("Müller-Lüdenscheidt GmbH & Co. KG")
    assert not has_unsafe_characters("Zeile 1\nZeile 2", allow_line_breaks=True)
    assert has_unsafe_characters("Zeile\u202e", allow_line_breaks=True)


def test_provider_names_the_country_of_a_foreign_issuer() -> None:
    version = legal()
    foreign = replace(
        version,
        configuration=replace(
            version.configuration,
            issuer=replace(version.configuration.issuer, country_code="AT"),
        ),
    )

    text = render_order_confirmation(facts(), foreign, LINKS).text

    assert "Löwenweg 12, 86150 Augsburg (AT)" in text
    assert (
        "Löwenweg 12, 86150 Augsburg\n"
        in render_order_confirmation(facts(), legal(), LINKS).text
    )


@pytest.mark.asyncio
async def test_a_confirmation_of_an_already_cancelled_order_is_skipped() -> None:
    sender = RecordingSender()

    await handler(
        OrderMailKind.CONFIRMATION,
        facts(order(status=CommitmentStatus.CANCELLED)),
        sender,
    ).handle(claimed(OrderMailKind.CONFIRMATION))

    assert sender.events == []


@pytest.mark.asyncio
async def test_the_cancellation_notice_is_still_sent_for_a_cancelled_order() -> None:
    sender = RecordingSender()
    value = facts(
        order(status=CommitmentStatus.CANCELLED),
        cancellation=OrderCancellationFacts(cancelled_at=CANCELLED_AT),
    )

    await handler(OrderMailKind.CANCELLATION, value, sender).handle(
        claimed(OrderMailKind.CANCELLATION)
    )

    assert len(sender.events) == 1


@pytest.mark.asyncio
async def test_the_recipient_limit_dead_letters_the_job() -> None:
    sender = RecordingSender()
    reader = Reader(facts(), recent=RECIPIENT_LIMIT)
    now = datetime(2026, 2, 10, 12, tzinfo=timezone.utc)
    mail = OrderMailHandler(
        OrderMailKind.CONFIRMATION,
        reader=reader,
        legal_configuration=Legal(legal()),
        sender=sender,
        clock=lambda: now,
    )

    with pytest.raises(OrderMailError) as error:
        await mail.handle(claimed(OrderMailKind.CONFIRMATION))

    assert error.value.code == "order_mail_recipient_limit"
    assert error.value.retryable is False
    assert sender.events == []
    assert reader.counted == [
        (
            hashlib.sha256(b"einkauf@musterwerk.invalid").hexdigest(),
            "einkauf@musterwerk.invalid",
            now - RECIPIENT_WINDOW,
        )
    ]
    # Released although the limit raised.
    assert reader.locks == [limit_digest("einkauf@musterwerk.invalid")]
    assert reader.locked is False


@pytest.mark.asyncio
async def test_below_the_limit_the_mail_goes_out() -> None:
    sender = RecordingSender()
    mail = OrderMailHandler(
        OrderMailKind.CONFIRMATION,
        reader=Reader(facts(), recent=RECIPIENT_LIMIT - 1),
        legal_configuration=Legal(legal()),
        sender=sender,
        clock=lambda: ORDERED_AT,
    )

    await mail.handle(claimed(OrderMailKind.CONFIRMATION))

    assert len(sender.events) == 1


@pytest.mark.asyncio
async def test_a_sent_job_that_runs_again_is_neither_sent_nor_limited() -> None:
    sender = RecordingSender()
    mail = OrderMailHandler(
        OrderMailKind.CONFIRMATION,
        reader=Reader(facts(), sent=True, recent=RECIPIENT_LIMIT + 5),
        legal_configuration=Legal(legal()),
        sender=sender,
        clock=lambda: ORDERED_AT,
    )

    await mail.handle(claimed(OrderMailKind.CONFIRMATION))

    assert sender.events == []


class Queue:
    def __init__(self, event: ClaimedOutboxEvent) -> None:
        self.event: ClaimedOutboxEvent | None = event
        self.failures: list[dict[str, object]] = []

    async def claim_next(
        self, *, worker_id: str, now: datetime
    ) -> ClaimedOutboxEvent | None:
        event, self.event = self.event, None
        return event

    async def complete(self, **_: object) -> None:
        raise AssertionError("a limited job must not complete")

    async def fail(self, **values: object) -> None:
        self.failures.append(values)


@pytest.mark.asyncio
async def test_the_worker_dead_letters_a_limited_job_at_the_first_attempt() -> None:
    queue = Queue(claimed(OrderMailKind.CONFIRMATION))
    worker = OutboxWorker(
        worker_id="unit",
        queue=queue,
        handlers={
            ORDER_CONFIRMATION_MAIL: OrderMailHandler(
                OrderMailKind.CONFIRMATION,
                reader=Reader(facts(), recent=RECIPIENT_LIMIT),
                legal_configuration=Legal(legal()),
                sender=RecordingSender(),
                clock=lambda: ORDERED_AT,
            )
        },
        retry_policy=RetryPolicy(max_attempts=5),
    )

    assert await worker.run_once() is True
    assert len(queue.failures) == 1
    failure = queue.failures[0]
    # Visible in the operations view as a failed job with this code.
    assert failure["dead_letter"] is True
    assert failure["error_code"] == "order_mail_recipient_limit"


# --- Re-review of #111: R1 mailbox, R2 characters, R3 lock ---


@pytest.mark.parametrize(
    ("address", "mailbox"),
    [
        ("Victim@Example.org", "victim@example.org"),
        ("victim+1@example.org", "victim@example.org"),
        ("victim+a+b@example.org", "victim@example.org"),
        ("v.ic.tim+x@gmail.com", "victim@gmail.com"),
        ("v.ictim@googlemail.com", "victim@gmail.com"),
        # Dots matter at other providers.
        ("v.ictim@example.org", "v.ictim@example.org"),
    ],
)
def test_mailbox_key_counts_plus_tags_and_gmail_dots_as_one_mailbox(
    address: str, mailbox: str
) -> None:
    assert mailbox_key(address) == mailbox
    assert limit_digest(address) == limit_digest(mailbox)


@pytest.mark.asyncio
async def test_the_mail_goes_to_the_address_as_entered_while_the_limit_uses_the_mailbox() -> (
    None
):
    sender = RecordingSender()
    tagged = order(
        buyer=BuyerSnapshot(
            party_kind=CommitmentPartyKind.PERSON,
            twenty_id=uuid4(),
            display_name="Vera",
            email="v.era+krapfen@gmail.com",
        )
    )
    reader = Reader(facts(tagged))

    await OrderMailHandler(
        OrderMailKind.CONFIRMATION,
        reader=reader,
        legal_configuration=Legal(legal()),
        sender=sender,
        clock=lambda: ORDERED_AT,
    ).handle(claimed(OrderMailKind.CONFIRMATION))

    assert sender.events[0].payload["to"] == "v.era+krapfen@gmail.com"
    assert reader.counted[0][:2] == (
        hashlib.sha256(b"v.era+krapfen@gmail.com").hexdigest(),
        "vera@gmail.com",
    )
    assert reader.locks == [limit_digest("vera@gmail.com")]


class LockCheckingSender(RecordingSender):
    def __init__(self, reader: Reader) -> None:
        super().__init__()
        self.reader = reader

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        assert self.reader.locked, "the send runs under the recipient lock"
        await super().handle(event)


@pytest.mark.asyncio
async def test_the_send_happens_inside_the_recipient_lock() -> None:
    reader = Reader(facts())
    sender = LockCheckingSender(reader)

    await OrderMailHandler(
        OrderMailKind.CONFIRMATION,
        reader=reader,
        legal_configuration=Legal(legal()),
        sender=sender,
        clock=lambda: ORDERED_AT,
    ).handle(claimed(OrderMailKind.CONFIRMATION))

    assert len(sender.events) == 1
    assert reader.locked is False


@pytest.mark.parametrize(
    "value",
    [
        "Max\ud800",  # lone surrogate (Cs)
        "Max\ue000",  # private use (Co)
        "Max\u0378",  # unassigned (Cn)
        "\u3164",  # Hangul filler
        "Ma\u2800x",  # Braille blank
        "\u115f\u1160",  # Hangul choseong/jungseong fillers
        "Max\uffa0",  # halfwidth Hangul filler
    ],
    ids=[
        "surrogate",
        "private-use",
        "unassigned",
        "hangul-filler",
        "braille",
        "jamo",
        "halfwidth",
    ],
)
def test_surrogates_private_unassigned_and_blank_letters_are_unsafe(value: str) -> None:
    assert has_unsafe_characters(value)
    assert has_unsafe_characters(value, allow_line_breaks=True)
    cleaned = single_line(value)
    assert not has_unsafe_characters(cleaned)
    cleaned.encode("utf-8")


def test_link_markers() -> None:
    for value in (
        "https://evil.example/pay",
        "www.evil.example",
        "zahlung@evil.example",
        "HTTP://X",
    ):
        assert has_link_markers(value), value
    for value in ("Müller-Lüdenscheidt GmbH & Co. KG", "Am Wall 3", "86150 Augsburg"):
        assert not has_link_markers(value), value


INTERNAL_SOURCES = (CommitmentSource.ACQUISITION, CommitmentSource.ADMIN)


@pytest.mark.parametrize("source", INTERNAL_SOURCES)
def test_an_internal_order_gets_mails_only_while_the_action_switched_them_on(
    source: CommitmentSource,
) -> None:
    internal = order(source=source)

    assert mail_not_due_reason(internal, internal_order_mails=False) is (
        MailNotDueReason.SWITCHED_OFF
    )
    assert mail_due(internal, internal_order_mails=True)
    # The public form is not behind the switch (D-M1).
    assert mail_due(order(), internal_order_mails=False)


@pytest.mark.parametrize("source", INTERNAL_SOURCES)
def test_an_internal_draft_gets_no_mail_and_no_cancellation_notice(
    source: CommitmentSource,
) -> None:
    draft = order(source=source, status=CommitmentStatus.DRAFT)
    cancelled = order(source=source, status=CommitmentStatus.CANCELLED)

    assert mail_not_due_reason(draft, internal_order_mails=True) is (
        MailNotDueReason.ORDER_DRAFT
    )
    # A cancelled order is judged by the status it left.
    assert (
        mail_not_due_reason(
            cancelled, internal_order_mails=True, status=CommitmentStatus.DRAFT
        )
        is MailNotDueReason.ORDER_DRAFT
    )
    assert mail_due(
        cancelled, internal_order_mails=True, status=CommitmentStatus.REVIEW_READY
    )


def test_no_address_means_no_mail_whatever_the_switch() -> None:
    erased = BuyerSnapshot(
        party_kind=CommitmentPartyKind.COMPANY,
        twenty_id=uuid4(),
        display_name="Anonymisiert",
        email=None,
    )
    for source in CommitmentSource:
        assert mail_not_due_reason(
            order(source=source, buyer=erased), internal_order_mails=True
        ) is (MailNotDueReason.NO_EMAIL)


def test_internal_confirmation_says_who_recorded_the_order() -> None:
    mail = render_order_confirmation(
        facts(order(source=CommitmentSource.ACQUISITION), internal_order_mails=True),
        legal(),
        LINKS,
    )
    reference = f"LA-{ORDER_ID.hex.upper()}"

    assert mail.subject == f"Ihre Bestellung bei Krapfentaxi 2026 · {reference}"
    for expected in (
        "vielen Dank für Ihre Bestellung bei der Aktion „Krapfentaxi 2026“.\n",
        "Ihre Bestellung wurde von einem Mitglied des Lions Hilfswerk Augsburg "
        "e.V. für Sie erfasst. Stimmt etwas nicht, schreiben Sie uns bitte an "
        "rechnung@hilfswerk.test.",
        f"Bestellnummer: {reference}",
        "Gesamtbetrag: 120,50 €",
        "Datenschutzerklärung: https://krapfen.leonaid.invalid/datenschutz",
    ):
        assert expected in mail.text, expected
    # The time a member typed the order in is not the buyer's order time.
    assert "Wir haben sie am" not in mail.text
    # The public confirmation does not carry the sentence.
    assert (
        "für Sie erfasst" not in render_order_confirmation(facts(), legal(), LINKS).text
    )


@pytest.mark.parametrize("source", INTERNAL_SOURCES)
def test_internal_order_mails_never_render_internal_data(
    source: CommitmentSource,
) -> None:
    internal = order(source=source)
    texts = (
        render_order_confirmation(
            facts(internal, internal_order_mails=True), legal(), LINKS
        ).text,
        render_order_cancellation(
            facts(
                internal,
                cancellation=OrderCancellationFacts(cancelled_at=CANCELLED_AT),
                internal_order_mails=True,
            ),
            legal(),
            LINKS,
        ).text,
    )
    for text in texts:
        for forbidden in ("Hofeinfahrt links", "Pforte", "999999", "4711"):
            assert forbidden not in text, forbidden


@pytest.mark.asyncio
async def test_handler_sends_the_confirmation_of_an_internal_order() -> None:
    sender = RecordingSender()
    value = facts(order(source=CommitmentSource.ADMIN), internal_order_mails=True)

    await handler(OrderMailKind.CONFIRMATION, value, sender).handle(
        claimed(OrderMailKind.CONFIRMATION)
    )

    assert "für Sie erfasst" in str(sender.events[0].payload["text"])


@pytest.mark.asyncio
async def test_handler_skips_the_notice_for_a_cancelled_internal_draft() -> None:
    sender = RecordingSender()
    value = facts(
        order(source=CommitmentSource.ADMIN, status=CommitmentStatus.CANCELLED),
        cancellation=OrderCancellationFacts(
            cancelled_at=CANCELLED_AT, previous_status=CommitmentStatus.DRAFT
        ),
        internal_order_mails=True,
    )

    await handler(OrderMailKind.CANCELLATION, value, sender).handle(
        claimed(OrderMailKind.CANCELLATION)
    )

    assert sender.events == []


def test_a_resend_job_keeps_the_order_id_as_second_key_segment() -> None:
    first = order_mail_event(
        OrderMailKind.CONFIRMATION,
        action_id=ACTION_ID,
        commitment_id=ORDER_ID,
        links=LINKS,
    )
    resend = order_mail_event(
        OrderMailKind.CONFIRMATION,
        action_id=ACTION_ID,
        commitment_id=ORDER_ID,
        links=LINKS,
        resend=2,
    )

    assert resend.idempotency_key == f"order-confirmation-mail:{ORDER_ID}:resend:2"
    # ``recent_order_mails`` joins the order through this segment.
    assert resend.idempotency_key.split(":")[1] == str(ORDER_ID)
    assert resend.id != first.id
    assert resend.event_type == first.event_type
    assert resend.payload == first.payload
    assert order_mail_key(OrderMailKind.CANCELLATION, ORDER_ID) == (
        f"order-cancellation-mail:{ORDER_ID}"
    )
    with pytest.raises(ValueError):
        order_mail_key(OrderMailKind.CONFIRMATION, ORDER_ID, resend=0)


@pytest.mark.asyncio
async def test_a_resend_is_sent_under_its_own_key_and_counts_for_the_limit() -> None:
    sender = RecordingSender()
    reader = Reader(facts(), recent=RECIPIENT_LIMIT)
    event = order_mail_event(
        OrderMailKind.CONFIRMATION,
        action_id=ACTION_ID,
        commitment_id=ORDER_ID,
        links=LINKS,
        resend=1,
    )
    job = replace(claimed(OrderMailKind.CONFIRMATION), id=event.id)
    job = replace(job, idempotency_key=event.idempotency_key)
    limited = OrderMailHandler(
        OrderMailKind.CONFIRMATION,
        reader=reader,
        legal_configuration=Legal(legal()),
        sender=sender,
        clock=lambda: ORDERED_AT,
    )

    with pytest.raises(OrderMailError) as captured:
        await limited.handle(job)
    assert captured.value.code == "order_mail_recipient_limit"
    assert sender.events == []

    reader.recent = 0
    await limited.handle(job)
    assert [sent.idempotency_key for sent in sender.events] == [
        f"order-confirmation-mail:{ORDER_ID}:resend:1"
    ]


# ---- review of stage 1: text by state, late orders, superseded jobs ----

# The order's window: 14.02.2026, 08:00–10:00 UTC.
WINDOW_END = datetime(2026, 2, 14, 10, 0, tzinfo=timezone.utc)


def confirmation_reason(
    commitment: Commitment | None = None,
    *,
    internal_order_mails: bool = True,
    drop_state: str | None = None,
    action_status: str = "active",
    now: datetime = ORDERED_AT,
    status: CommitmentStatus | None = None,
) -> MailNotDueReason | None:
    return confirmation_not_due_reason(
        commitment or order(source=CommitmentSource.ACQUISITION),
        internal_order_mails=internal_order_mails,
        drop_state=drop_state,
        action_status=action_status,
        now=now,
        status=status,
    )


@pytest.mark.parametrize("source", tuple(CommitmentSource))
def test_a_confirmation_is_not_due_for_an_order_that_is_already_done(
    source: CommitmentSource,
) -> None:
    value = order(source=source)

    assert confirmation_reason(value) is None
    for state in ("delivered", "missed"):
        assert confirmation_reason(value, drop_state=state) is (
            MailNotDueReason.DELIVERY_RECORDED
        )
    # Until the last minute of the window, not after it.
    assert confirmation_reason(value, now=WINDOW_END - timedelta(minutes=1)) is None
    assert confirmation_reason(value, now=WINDOW_END) is MailNotDueReason.WINDOW_OVER
    for status in ("completed", "archived"):
        assert confirmation_reason(value, action_status=status) is (
            MailNotDueReason.ACTION_CLOSED
        )
    for status in ("draft", "scheduled", "active"):
        assert confirmation_reason(value, action_status=status) is None
    assert confirmation_reason(replace(value, status=CommitmentStatus.CANCELLED)) is (
        MailNotDueReason.ORDER_CANCELLED
    )
    # An order without a window has no window that could be over.
    no_window = replace(value, delivery_window_id=None, delivery_window_snapshot=None)
    assert confirmation_reason(no_window, now=WINDOW_END + timedelta(days=30)) is None


def test_the_first_reasons_of_a_confirmation_are_the_common_ones() -> None:
    internal = order(source=CommitmentSource.ADMIN)

    assert confirmation_reason(internal, internal_order_mails=False) is (
        MailNotDueReason.SWITCHED_OFF
    )
    assert confirmation_reason(
        replace(internal, status=CommitmentStatus.DRAFT), drop_state="delivered"
    ) is (MailNotDueReason.ORDER_DRAFT)


LATE_CASES = [
    (facts(drop_state="delivered"), ORDERED_AT, "delivery_recorded"),
    (facts(drop_state="missed"), ORDERED_AT, "delivery_recorded"),
    (facts(action_status="completed"), ORDERED_AT, "action_closed"),
    (facts(action_status="archived"), ORDERED_AT, "action_closed"),
    (facts(), WINDOW_END, "window_over"),
    # Orders from the public form follow the same rule.
    (facts(order(source=CommitmentSource.PUBLIC_FORM)), WINDOW_END, "window_over"),
]
LATE_IDS = [
    "delivered",
    "missed",
    "action-completed",
    "action-archived",
    "window-over",
    "public-window-over",
]


def late_handler(
    value: OrderMailFacts, now: datetime, sender: RecordingSender, *, sent: bool = False
) -> OrderMailHandler:
    return OrderMailHandler(
        OrderMailKind.CONFIRMATION,
        reader=Reader(value, sent=sent),
        legal_configuration=Legal(legal()),
        sender=sender,
        clock=lambda: now,
    )


@pytest.mark.parametrize(("value", "now", "reason"), LATE_CASES, ids=LATE_IDS)
@pytest.mark.asyncio
async def test_a_confirmation_that_comes_too_late_is_not_sent_and_leaves_no_dead_letter(
    value: OrderMailFacts, now: datetime, reason: str
) -> None:
    sender = RecordingSender()

    # The job completes (the handler returns): a dead letter of a late mail
    # could never be cleared. The order's status reports it as failed.
    await late_handler(value, now, sender).handle(claimed(OrderMailKind.CONFIRMATION))

    assert sender.events == []
    assert MailNotDueReason(reason) in LATE_REASONS


@pytest.mark.parametrize(("value", "now", "reason"), LATE_CASES, ids=LATE_IDS)
@pytest.mark.asyncio
async def test_a_late_rerun_of_a_sent_confirmation_is_no_failure(
    value: OrderMailFacts, now: datetime, reason: str
) -> None:
    sender = RecordingSender()

    # The mail went out in time; only its completion was lost.
    await late_handler(value, now, sender, sent=True).handle(
        claimed(OrderMailKind.CONFIRMATION)
    )

    assert sender.events == []


@pytest.mark.asyncio
async def test_a_confirmation_that_is_no_news_is_skipped_without_a_failure() -> None:
    sender = RecordingSender()
    erased = BuyerSnapshot(
        party_kind=CommitmentPartyKind.COMPANY,
        twenty_id=uuid4(),
        display_name="Anonymisiert",
        email=None,
    )
    for value in (
        # Cancelled (the notice covers it), even after the window.
        facts(order(status=CommitmentStatus.CANCELLED)),
        facts(order(buyer=erased)),
        facts(order(source=CommitmentSource.ADMIN), internal_order_mails=False),
    ):
        await late_handler(value, WINDOW_END, sender).handle(
            claimed(OrderMailKind.CONFIRMATION)
        )
    assert sender.events == []


def test_the_confirmation_rule_can_judge_a_draft_as_completed() -> None:
    draft = order(source=CommitmentSource.ADMIN, status=CommitmentStatus.DRAFT)
    ready = CommitmentStatus.REVIEW_READY

    assert confirmation_reason(draft) is MailNotDueReason.ORDER_DRAFT
    assert confirmation_reason(draft, status=ready) is None
    assert confirmation_reason(draft, status=ready, action_status="completed") is (
        MailNotDueReason.ACTION_CLOSED
    )
    assert confirmation_reason(draft, status=ready, now=WINDOW_END) is (
        MailNotDueReason.WINDOW_OVER
    )
    assert confirmation_reason(draft, status=ready, drop_state="delivered") is (
        MailNotDueReason.DELIVERY_RECORDED
    )
    assert confirmation_reason(draft, status=ready, internal_order_mails=False) is (
        MailNotDueReason.SWITCHED_OFF
    )


@pytest.mark.asyncio
async def test_the_cancellation_notice_does_not_depend_on_delivery_or_window() -> None:
    sender = RecordingSender()
    value = facts(
        order(status=CommitmentStatus.CANCELLED),
        cancellation=OrderCancellationFacts(cancelled_at=CANCELLED_AT),
        action_status="completed",
    )
    notice = OrderMailHandler(
        OrderMailKind.CANCELLATION,
        reader=Reader(value),
        legal_configuration=Legal(legal()),
        sender=sender,
        clock=lambda: WINDOW_END + timedelta(days=3),
    )

    await notice.handle(claimed(OrderMailKind.CANCELLATION))

    assert len(sender.events) == 1


REVIEW = "Ein Clubmitglied prüft Ihre Bestellung."
INVOICE_LATER = (
    "Die Rechnung erhalten Sie separat, sobald der Club die Bestellung geprüft hat."
)


@pytest.mark.parametrize(
    ("status", "invoicing", "expected", "absent"),
    [
        (CommitmentStatus.REVIEW_READY, True, f"{REVIEW} {INVOICE_LATER}", ()),
        (CommitmentStatus.REVIEW_READY, False, REVIEW, ("Rechnung erhalten",)),
        (
            CommitmentStatus.CONFIRMED,
            True,
            "Ihre Bestellung ist bestätigt. Die Rechnung erhalten Sie separat.",
            (REVIEW,),
        ),
        (
            CommitmentStatus.CONFIRMED,
            False,
            "Ihre Bestellung ist bestätigt.",
            (REVIEW, "Rechnung erhalten"),
        ),
        (
            CommitmentStatus.INVOICED,
            True,
            "Die Rechnung zu dieser Bestellung ist ausgestellt.",
            (REVIEW, "Rechnung erhalten"),
        ),
    ],
)
def test_the_confirmation_says_what_is_still_to_come_for_this_order(
    status: CommitmentStatus, invoicing: bool, expected: str, absent: tuple[str, ...]
) -> None:
    text = render_order_confirmation(
        facts(order(status=status), invoicing=invoicing), legal(), LINKS
    ).text

    assert f"Wie es weitergeht\n{expected}\n" in text
    for phrase in absent:
        assert phrase not in text, phrase


def test_an_invoiced_order_without_invoicing_promises_nothing() -> None:
    # Cannot happen through the application; the text must still not invent
    # a next step.
    text = render_order_confirmation(
        facts(order(status=CommitmentStatus.INVOICED), invoicing=False), legal(), LINKS
    ).text

    assert "Wie es weitergeht" not in text
    assert "Rechnung" not in text.split("Rechnungsanschrift")[0]


def test_a_mail_key_names_its_first_key_and_its_place_in_the_resends() -> None:
    first = f"order-confirmation-mail:{ORDER_ID}"

    assert mail_key_sequence(first) == (first, 0)
    assert mail_key_sequence(f"{first}:resend:12") == (first, 12)
    with pytest.raises(OrderMailError):
        mail_key_sequence(f"{first}:resend:x")


@pytest.mark.asyncio
async def test_an_old_job_does_not_send_after_a_later_resend_went_out() -> None:
    """Dead letter, manager resend, then the operator retries the old job."""

    first = f"order-confirmation-mail:{ORDER_ID}"
    sender = RecordingSender()
    reader = Reader(facts())
    reader.sent_keys_value = (f"{first}:resend:1",)
    retried = OrderMailHandler(
        OrderMailKind.CONFIRMATION,
        reader=reader,
        legal_configuration=Legal(legal()),
        sender=sender,
        clock=lambda: ORDERED_AT,
    )

    # The first job (sequence 0) is behind the sent resend: nothing goes out,
    # and the mailbox limit is not even asked.
    await retried.handle(claimed(OrderMailKind.CONFIRMATION))
    assert sender.events == []
    assert reader.counted == []

    # A later resend is not held back by the earlier one.
    event = order_mail_event(
        OrderMailKind.CONFIRMATION,
        action_id=ACTION_ID,
        commitment_id=ORDER_ID,
        links=LINKS,
        resend=2,
    )
    newer = replace(
        claimed(OrderMailKind.CONFIRMATION),
        id=event.id,
        idempotency_key=event.idempotency_key,
    )
    await retried.handle(newer)
    assert [sent.idempotency_key for sent in sender.events] == [f"{first}:resend:2"]
    # Keys of another kind of the same order do not count.
    reader.sent_keys_value = (f"order-cancellation-mail:{ORDER_ID}:resend:5",)
    await retried.handle(claimed(OrderMailKind.CONFIRMATION))
    assert len(sender.events) == 2


# ---- the mail on the delivery day -------------------------------------

BERLIN = ZoneInfo("Europe/Berlin")
# The order's window: Saturday 14.02.2026, 09:00–11:00 in Berlin.
DELIVERY_MORNING = datetime(2026, 2, 14, 7, 5, tzinfo=BERLIN)
DAY_KEY = f"order-delivery-day-mail:{ORDER_ID}:{WINDOW_ID}"


def day_facts(commitment: Commitment | None = None, **changes: Any) -> OrderMailFacts:
    values: dict[str, Any] = {
        "delivery_day_mail": True,
        "delivery_zone": BERLIN,
        **changes,
    }
    return replace(facts(commitment), **values)


def day_reason(
    commitment: Commitment | None = None,
    *,
    now: datetime = DELIVERY_MORNING,
    send_time: time | None = time(7, 0),
    delivery_day_mail: bool = True,
    drop_state: str | None = None,
    action_status: str = "active",
) -> MailNotDueReason | None:
    return delivery_day_not_due_reason(
        commitment or order(),
        delivery_day_mail=delivery_day_mail,
        drop_state=drop_state,
        action_status=action_status,
        zone=BERLIN,
        now=now,
        send_time=send_time,
    )


def claimed_day(
    window_id: UUID = WINDOW_ID, *, resend: int | None = None
) -> ClaimedOutboxEvent:
    event = order_mail_event(
        OrderMailKind.DELIVERY_DAY,
        action_id=ACTION_ID,
        commitment_id=ORDER_ID,
        links=replace(LINKS, campaign_url=None),
        window_id=window_id,
        resend=resend,
    )
    return ClaimedOutboxEvent(
        id=event.id,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        event_type=event.event_type,
        idempotency_key=event.idempotency_key,
        payload=json.loads(json.dumps(event.payload)),
        attempts=1,
        claim_token=uuid4(),
        claimed_by="unit",
    )


def day_handler(
    value: OrderMailFacts | None,
    sender: RecordingSender,
    *,
    now: datetime = DELIVERY_MORNING,
    recent: int = 0,
) -> OrderMailHandler:
    return OrderMailHandler(
        OrderMailKind.DELIVERY_DAY,
        reader=Reader(value, recent=recent),
        legal_configuration=Legal(legal()),
        sender=sender,
        clock=lambda: now,
    )


def test_the_delivery_day_job_is_keyed_by_order_and_window() -> None:
    event = order_mail_event(
        OrderMailKind.DELIVERY_DAY,
        action_id=ACTION_ID,
        commitment_id=ORDER_ID,
        links=LINKS,
        window_id=WINDOW_ID,
    )
    other_window = uuid4()

    assert event.event_type == "order.delivery_day.mail.v1"
    assert event.idempotency_key == DAY_KEY
    # ``recent_order_mails`` joins the order through the second segment.
    assert event.idempotency_key.split(":")[1] == str(ORDER_ID)
    assert event.payload["windowId"] == str(WINDOW_ID)
    assert "@" not in json.dumps(event.payload)
    # Another window is another mail; a resend keeps order and window.
    assert order_mail_key(
        OrderMailKind.DELIVERY_DAY, ORDER_ID, window_id=other_window
    ) == (f"order-delivery-day-mail:{ORDER_ID}:{other_window}")
    assert order_mail_key(
        OrderMailKind.DELIVERY_DAY, ORDER_ID, window_id=WINDOW_ID, resend=2
    ) == (f"{DAY_KEY}:resend:2")
    with pytest.raises(ValueError):
        order_mail_key(OrderMailKind.DELIVERY_DAY, ORDER_ID)
    with pytest.raises(ValueError):
        order_mail_key(OrderMailKind.CONFIRMATION, ORDER_ID, window_id=WINDOW_ID)
    # The other kinds carry no window.
    assert "windowId" not in claimed(OrderMailKind.CONFIRMATION).payload


@pytest.mark.parametrize("source", tuple(CommitmentSource))
@pytest.mark.parametrize(
    "status",
    [
        CommitmentStatus.REVIEW_READY,
        CommitmentStatus.CONFIRMED,
        CommitmentStatus.INVOICED,
    ],
)
def test_the_delivery_day_mail_is_due_for_every_source_on_the_day(
    source: CommitmentSource, status: CommitmentStatus
) -> None:
    assert day_reason(order(source=source, status=status)) is None


def test_the_delivery_day_mail_waits_for_the_day_and_the_send_time() -> None:
    def at(*moment: int) -> datetime:
        return datetime(*moment, tzinfo=BERLIN)

    # The day before, also late in the evening.
    assert day_reason(now=at(2026, 2, 13, 23, 59)) is MailNotDueReason.SCHEDULED
    # On the day before the send time.
    assert day_reason(now=at(2026, 2, 14, 6, 59)) is MailNotDueReason.SCHEDULED
    assert day_reason(now=at(2026, 2, 14, 7, 0)) is None
    # Until the window ends, also after it began.
    assert day_reason(now=at(2026, 2, 14, 10, 59)) is None
    assert day_reason(now=at(2026, 2, 14, 11, 0)) is MailNotDueReason.WINDOW_OVER
    assert day_reason(now=at(2026, 2, 15, 8, 0)) is MailNotDueReason.WINDOW_OVER
    # The worker sends a queued job whatever the send time is now.
    assert day_reason(now=at(2026, 2, 14, 5, 0), send_time=None) is None
    assert day_reason(now=at(2026, 2, 13, 23, 0), send_time=None) is (
        MailNotDueReason.SCHEDULED
    )


def test_the_delivery_day_is_counted_in_the_zone_of_the_action() -> None:
    # 00:30–02:00 in Berlin on 14.02. is still 13.02. in UTC.
    night = order(
        delivery_window_snapshot={
            "windowId": str(WINDOW_ID),
            "startsAt": "2026-02-13T23:30:00+00:00",
            "endsAt": "2026-02-14T01:00:00+00:00",
            "timezone": "Europe/Berlin",
        }
    )
    late_evening = datetime(2026, 2, 13, 22, 50, tzinfo=timezone.utc)
    after_midnight = datetime(2026, 2, 13, 23, 10, tzinfo=timezone.utc)

    assert day_reason(night, now=late_evening, send_time=None) is (
        MailNotDueReason.SCHEDULED
    )
    assert day_reason(night, now=after_midnight, send_time=None) is None
    # With the send time the mail could only go out after the window: never,
    # and the status says so on every day.
    midday = datetime(2026, 2, 14, 12, 0, tzinfo=BERLIN)
    for moment in (late_evening, after_midnight, midday):
        assert day_reason(night, now=moment) is (
            MailNotDueReason.WINDOW_BEFORE_SEND_TIME
        )
    # An action in UTC counts the same window as a delivery of the 13th.
    assert (
        delivery_day_not_due_reason(
            night,
            delivery_day_mail=True,
            drop_state=None,
            zone=ZoneInfo("UTC"),
            now=late_evening,
        )
        is None
    )


def test_the_delivery_day_mail_is_not_due_without_address_switch_or_open_delivery() -> (
    None
):
    erased = BuyerSnapshot(
        party_kind=CommitmentPartyKind.COMPANY,
        twenty_id=uuid4(),
        display_name="Anonymisiert",
        email=None,
    )
    assert day_reason(order(buyer=erased)) is MailNotDueReason.NO_EMAIL
    assert day_reason(delivery_day_mail=False) is MailNotDueReason.SWITCHED_OFF
    assert day_reason(order(status=CommitmentStatus.CANCELLED)) is (
        MailNotDueReason.ORDER_CANCELLED
    )
    assert day_reason(order(status=CommitmentStatus.DRAFT)) is (
        MailNotDueReason.ORDER_DRAFT
    )
    for state in ("delivered", "missed"):
        assert day_reason(drop_state=state) is MailNotDueReason.DELIVERY_RECORDED
    # A completed or archived action sends nothing any more, with or
    # without a send time (the worker passes none).
    for closed in ("completed", "archived"):
        for send_time in (time(7, 0), None):
            assert day_reason(action_status=closed, send_time=send_time) is (
                MailNotDueReason.ACTION_CLOSED
            )
    assert day_reason(action_status="paused") is None
    with pytest.raises(ValueError):
        day_reason(order(delivery_window_id=None, delivery_window_snapshot=None))


def test_delivery_day_mail_names_window_address_and_quantities_only() -> None:
    mail = render_delivery_day(
        day_facts(), legal(), replace(LINKS, campaign_url=None), now=DELIVERY_MORNING
    )
    reference = f"LA-{ORDER_ID.hex.upper()}"

    assert mail.recipient == "einkauf@musterwerk.invalid"
    assert mail.subject == "Ihre Lieferung kommt heute zwischen 09:00 und 11:00 Uhr"
    text = mail.text
    for expected in (
        "Guten Morgen,",
        f"Ihre Bestellung {reference} bei der Aktion „Krapfentaxi 2026“ wird heute, "
        "Samstag, 14.02.2026, zwischen 09:00 und 11:00 Uhr geliefert.",
        "Lieferadresse:\n  Musterwerk Empfang\n  Lieferstraße 7\n  86152 Augsburg",
        "Bestellt:\n- Krapfen-Box: 3 Boxen (72 Stück)\n- Einzelkrapfen: 1 Stück",
        "Ist in dieser Zeit niemand da, schreiben Sie uns bitte an "
        "rechnung@hilfswerk.test oder rufen Sie uns an: +49 821 123456.",
        "Datenschutzerklärung: https://krapfen.leonaid.invalid/datenschutz",
        "Anbieter\nLions Hilfswerk Augsburg e.V.\nLöwenweg 12, 86150 Augsburg",
        "Impressum: https://krapfen.leonaid.invalid/impressum",
    ):
        assert expected in text, expected
    # Nothing about the tour, the driver or the delivery contact, no prices,
    # no billing address and no campaign link.
    for forbidden in (
        "Hofeinfahrt links",
        "Pforte",
        "999999",
        "Hintereingang",
        "4711",
        "€",
        "Rechnungsweg",
        "Zur Aktion",
        "Fahrer",
    ):
        assert forbidden not in text, forbidden


def test_delivery_day_mail_greets_by_the_local_hour_and_copes_without_phone() -> None:
    no_phone = legal()
    no_phone = replace(
        no_phone, configuration=replace(no_phone.configuration, imprint_phone=None)
    )
    noon = datetime(2026, 2, 14, 11, 0, tzinfo=BERLIN)
    mail = render_delivery_day(day_facts(), no_phone, LINKS, now=noon)

    assert mail.text.startswith("Guten Tag,\n")
    assert (
        "Ist in dieser Zeit niemand da, schreiben Sie uns bitte an "
        "rechnung@hilfswerk.test.\n" in mail.text
    )
    assert "rufen Sie uns an" not in mail.text
    # Only channels the club configured are named; none, no sentence.
    no_mail = legal()
    object.__setattr__(no_mail.configuration.issuer, "email", " ")
    phone_only = render_delivery_day(day_facts(), no_mail, LINKS, now=noon).text
    assert (
        "Ist in dieser Zeit niemand da, rufen Sie uns bitte an: +49 821 123456.\n"
        in phone_only
    )
    assert "schreiben Sie uns" not in phone_only
    object.__setattr__(no_mail.configuration, "imprint_phone", None)
    silent = render_delivery_day(day_facts(), no_mail, LINKS, now=noon).text
    assert "Ist in dieser Zeit niemand da" not in silent
    assert "\n\n\n" not in silent
    # The window is shown in the action's zone, whatever zone the clock has.
    utc_now = DELIVERY_MORNING.astimezone(timezone.utc)
    assert (
        render_delivery_day(day_facts(), legal(), LINKS, now=utc_now).subject
        == "Ihre Lieferung kommt heute zwischen 09:00 und 11:00 Uhr"
    )


@pytest.mark.asyncio
async def test_handler_sends_the_delivery_day_mail_under_its_key() -> None:
    sender = RecordingSender()
    event = claimed_day()

    await day_handler(day_facts(), sender).handle(event)

    assert [sent.idempotency_key for sent in sender.events] == [DAY_KEY]
    assert sender.events[0].payload["to"] == "einkauf@musterwerk.invalid"
    assert "wird heute, Samstag, 14.02.2026" in str(sender.events[0].payload["text"])


@pytest.mark.parametrize(
    "value",
    [
        None,
        day_facts(delivery_day_mail=False),
        day_facts(order(status=CommitmentStatus.CANCELLED)),
        day_facts(drop_state="delivered"),
        day_facts(drop_state="missed"),
        day_facts(action_status="completed"),
        day_facts(action_status="archived"),
        day_facts(delivery_capability=False),
        day_facts(
            order(
                buyer=BuyerSnapshot(
                    party_kind=CommitmentPartyKind.COMPANY,
                    twenty_id=uuid4(),
                    display_name="Anonymisiert",
                    email=None,
                )
            )
        ),
    ],
    ids=[
        "order-gone",
        "switched-off",
        "cancelled",
        "delivered",
        "missed",
        "action-completed",
        "action-archived",
        "no-delivery-capability",
        "erased",
    ],
)
@pytest.mark.asyncio
async def test_handler_skips_a_delivery_day_mail_that_is_not_due_any_more(
    value: OrderMailFacts | None,
) -> None:
    sender = RecordingSender()

    await day_handler(value, sender).handle(claimed_day())

    assert sender.events == []


@pytest.mark.asyncio
async def test_handler_skips_the_job_of_a_window_the_order_has_left() -> None:
    sender = RecordingSender()

    # The job names another window than the order has now.
    await day_handler(day_facts(), sender).handle(claimed_day(uuid4()))

    assert sender.events == []


@pytest.mark.asyncio
async def test_handler_skips_a_delivery_day_job_that_waited_past_the_window() -> None:
    sender = RecordingSender()
    after = datetime(2026, 2, 14, 11, 1, tzinfo=BERLIN)

    # Not sent; the job completes (no dead letter that no retry can clear).
    # The order's mail status shows the missed mail as failed.
    await day_handler(day_facts(), sender, now=after).handle(claimed_day())

    assert sender.events == []


@pytest.mark.asyncio
async def test_delivery_day_job_without_its_window_is_invalid() -> None:
    event = claimed_day()
    broken = replace(
        event, payload={k: v for k, v in event.payload.items() if k != "windowId"}
    )

    with pytest.raises(OrderMailError) as captured:
        await day_handler(day_facts(), RecordingSender()).handle(broken)

    assert captured.value.code == "order_mail_payload_invalid"


@pytest.mark.asyncio
async def test_the_mailbox_limit_holds_for_the_delivery_day_mail_and_its_resend() -> (
    None
):
    sender = RecordingSender()

    for event in (claimed_day(), claimed_day(resend=1)):
        with pytest.raises(OrderMailError) as captured:
            await day_handler(day_facts(), sender, recent=RECIPIENT_LIMIT).handle(event)
        assert captured.value.code == "order_mail_recipient_limit"
        assert captured.value.retryable is False
    assert sender.events == []

    await day_handler(day_facts(), sender, recent=RECIPIENT_LIMIT - 1).handle(
        claimed_day(resend=1)
    )
    assert [sent.idempotency_key for sent in sender.events] == [f"{DAY_KEY}:resend:1"]


class SweepRepository:
    def __init__(self, result: int | None) -> None:
        self.result = result
        self.calls: list[tuple[datetime, int, OrderMailLinks]] = []

    async def queue_due(
        self, *, now: datetime, limit: int, links: OrderMailLinks
    ) -> int | None:
        self.calls.append((now, limit, links))
        return self.result


@pytest.mark.asyncio
async def test_the_sweep_queues_with_the_legal_links_of_the_public_host() -> None:
    repository = SweepRepository(3)
    links = LinkBuilder(
        admin_base_url="https://app.leonaid.invalid",
        site_base_url="https://club.leonaid.invalid",
    )
    sweep = DeliveryDayMailSweep(repository, links)

    assert await sweep.run_once(now=DELIVERY_MORNING, limit=50) == 3
    assert repository.calls == [
        (
            DELIVERY_MORNING,
            50,
            OrderMailLinks(
                campaign_url=None,
                privacy_url="https://club.leonaid.invalid/datenschutz",
                imprint_url="https://club.leonaid.invalid/impressum",
            ),
        )
    ]
    assert delivery_day_links(links).campaign_url is None
    with pytest.raises(ValueError):
        await sweep.run_once(now=datetime(2026, 2, 14, 7, 5))


@pytest.mark.asyncio
async def test_a_sweep_that_another_worker_runs_queues_nothing_here() -> None:
    sweep = DeliveryDayMailSweep(
        SweepRepository(None), LinkBuilder.single_host("https://app.leonaid.invalid")
    )

    assert await sweep.run_once(now=DELIVERY_MORNING) == 0


def test_the_sweep_writes_the_same_job_for_an_order_and_window() -> None:
    due = DueDeliveryDayMail(
        action_id=ACTION_ID, commitment_id=ORDER_ID, window_id=WINDOW_ID
    )
    links = replace(LINKS, campaign_url=None)

    first = delivery_day_event(due, links)
    assert first == delivery_day_event(due, links)
    assert first.idempotency_key == DAY_KEY
    assert first.payload == {
        "actionId": str(ACTION_ID),
        "commitmentId": str(ORDER_ID),
        "windowId": str(WINDOW_ID),
        "campaignUrl": None,
        "privacyUrl": LINKS.privacy_url,
        "imprintUrl": LINKS.imprint_url,
    }
    assert timedelta(0) < RECIPIENT_WINDOW
