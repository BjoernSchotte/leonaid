"""Order confirmation and cancellation notice: jobs, texts and handler rules."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from leonaid.adapters.postgres.order_mails import PublicCampaignLinks
from leonaid.application.links import LinkBuilder
from leonaid.application.order_mails import (
    ORDER_CANCELLATION_MAIL,
    ORDER_CONFIRMATION_MAIL,
    OrderCancellationFacts,
    OrderMailError,
    OrderMailFacts,
    OrderMailHandler,
    OrderMailKind,
    OrderMailLinkResolver,
    OrderMailLinks,
    delivery_window_label,
    order_mail_event,
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
from leonaid.domain.outbox import ClaimedOutboxEvent
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
            name="Pforte Herr Geheim", phone="+49 821 999999"
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
) -> OrderMailFacts:
    return OrderMailFacts(
        action_name="Krapfentaxi 2026",
        commitment=commitment or order(),
        ordered_at=ORDERED_AT,
        cancellation=cancellation,
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
    def __init__(self, value: OrderMailFacts | None) -> None:
        self.value = value
        self.calls: list[tuple[UUID, OrderMailKind]] = []

    async def facts(
        self, commitment_id: UUID, kind: OrderMailKind
    ) -> OrderMailFacts | None:
        self.calls.append((commitment_id, kind))
        return self.value


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
        facts(order(source=CommitmentSource.ADMIN, public_reference=None)),
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
    ids=["order-gone", "not-public", "erased"],
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


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            {
                "archive_slug": "krapfentaxi-2026",
                "alias": "krapfentaxi",
                "campaign_page": True,
            },
            "https://site.leonaid.invalid/campaigns/krapfentaxi-2026/",
        ),
        (
            {
                "archive_slug": "krapfentaxi-2026",
                "alias": "krapfentaxi",
                "campaign_page": False,
            },
            "https://site.leonaid.invalid/krapfentaxi",
        ),
        (
            {"archive_slug": "krapfentaxi-2026", "alias": None, "campaign_page": False},
            "https://site.leonaid.invalid/archive/krapfentaxi-2026",
        ),
        (None, None),
    ],
    ids=["campaign-page", "alias", "archive", "missing"],
)
@pytest.mark.asyncio
async def test_public_campaign_link_follows_the_public_host_rule(
    row: dict[str, object] | None, expected: str | None
) -> None:
    links = LinkBuilder(
        admin_base_url="https://app.leonaid.invalid",
        site_base_url="https://site.leonaid.invalid",
    )

    assert (
        await PublicCampaignLinks(cast(Any, Pool(row)), links).campaign_link(ACTION_ID)
        == expected
    )


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
