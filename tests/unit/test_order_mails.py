"""Order confirmation and cancellation notice: jobs, texts and handler rules."""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from leonaid.application.links import LinkBuilder
from leonaid.application.order_mails import (
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
    delivery_window_label,
    limit_digest,
    mail_due,
    mail_not_due_reason,
    mailbox_key,
    order_mail_event,
    order_mail_key,
    render_order_cancellation,
    render_order_confirmation,
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
) -> OrderMailFacts:
    return OrderMailFacts(
        action_name="Krapfentaxi 2026",
        commitment=commitment or order(),
        ordered_at=ORDERED_AT,
        cancellation=cancellation,
        internal_order_mails=internal_order_mails,
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

    async def facts(
        self, commitment_id: UUID, kind: OrderMailKind
    ) -> OrderMailFacts | None:
        self.calls.append((commitment_id, kind))
        return self.value

    async def was_sent(self, idempotency_key: str) -> bool:
        return self.sent

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
