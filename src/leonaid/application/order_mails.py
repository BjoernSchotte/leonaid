"""Transactional mails to the buyer of a public order.

Two mails: the order confirmation after a public order is recorded and the
cancellation notice after ``cancelCommitment`` cancelled such an order. Both
are outbox jobs written in the same transaction as the order or the
cancellation. The job payload holds ids and the non-personal links only; the
worker reads the order from Core when it sends, so a privacy erasure that
ran in between leaves nothing to send, and no copy of the buyer's data waits
in the queue.

One job per order and kind: the job id and the idempotency key are derived
from the order id, and the HTTP replay of an order or a cancellation returns
before it writes a job. Delivery is at least once: the SMTP ledger
(``mail_delivery``) skips a key that was already sent when a job is retried
or claimed again, but a crash between the SMTP server accepting the mail and
the ledger write sends it a second time on the retry.

The order lines, prices, addresses and window of a public order cannot be
changed after it is placed (only drafts get a window later), so the order
read at send time is the order as placed. A confirmation whose order is
already cancelled is skipped; the cancellation notice covers it.

The text contains only what the buyer entered (items, quantities, delivery
window, addresses) and the club's details from the active legal
configuration. Internal data stays out: the order message, the delivery
contact, the cancellation reason and note, CRM names. Every stored text is
put on one line without control or format characters (``_clean``), so data
entered before the input check cannot forge a paragraph or hide text.

At most ``RECIPIENT_LIMIT`` order mails go to one address per
``RECIPIENT_WINDOW``: the unauthenticated form must not make the club flood
an address it does not own. A job over the limit is dead-lettered with
``order_mail_recipient_limit`` and shows in the operations view, where an
operator can retry it later.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from leonaid.application.links import LinkBuilder
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.calendar import INSTALLATION_TIME_ZONE
from leonaid.domain.commitments import (
    Commitment,
    CommitmentLine,
    CommitmentSource,
    CommitmentStatus,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
    Money,
)
from leonaid.domain.legal_configuration import LegalConfigurationVersion
from leonaid.domain.outbox import ClaimedOutboxEvent, JsonValue, PendingOutboxEvent
from leonaid.domain.text import single_line

ORDER_MAIL_NAMESPACE = UUID("f3b0c6a2-5d1e-4c8b-9a57-0e6d2b4f8c13")
ORDER_CONFIRMATION_MAIL = "order.confirmation.mail.v1"
ORDER_CANCELLATION_MAIL = "order.cancellation.mail.v1"
ORDER_MAIL_EVENT_TYPES = (ORDER_CONFIRMATION_MAIL, ORDER_CANCELLATION_MAIL)
ORDER_MAIL_KEY_PREFIXES = ("order-confirmation-mail:", "order-cancellation-mail:")
RECIPIENT_LIMIT = 10
RECIPIENT_WINDOW = timedelta(hours=1)

WEEKDAYS = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)


class OrderMailKind(StrEnum):
    CONFIRMATION = "confirmation"
    CANCELLATION = "cancellation"


EVENT_TYPES = {
    OrderMailKind.CONFIRMATION: ORDER_CONFIRMATION_MAIL,
    OrderMailKind.CANCELLATION: ORDER_CANCELLATION_MAIL,
}


class OrderMailError(RuntimeError):
    """A stable, payload-free failure code for the outbox ledger.

    ``retryable=False`` dead-letters the job at once (the worker reads it).
    """

    def __init__(self, code: str, *, retryable: bool = True) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class OrderMailLinks:
    """Absolute links of the mail; none of them carries personal data."""

    campaign_url: str | None
    privacy_url: str
    imprint_url: str

    def payload(self) -> dict[str, JsonValue]:
        return {
            "campaignUrl": self.campaign_url,
            "privacyUrl": self.privacy_url,
            "imprintUrl": self.imprint_url,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, JsonValue]) -> OrderMailLinks:
        campaign = payload.get("campaignUrl")
        privacy = payload.get("privacyUrl")
        imprint = payload.get("imprintUrl")
        if (
            not (campaign is None or isinstance(campaign, str))
            or not isinstance(privacy, str)
            or not isinstance(imprint, str)
        ):
            raise OrderMailError("order_mail_payload_invalid")
        return cls(campaign_url=campaign, privacy_url=privacy, imprint_url=imprint)


# The action's public page for the mail, or None for no link. Today this is
# the public host path (``PublicCampaignLinks``); with campaign hosts it is
# the permanent edition URL of decision D8 (``SiteDirectory.edition_link``).
CampaignLink = Callable[[UUID], Awaitable[str | None]]


class OrderMailLinkResolver:
    """Resolves the links when the job is written, before any transaction.

    The campaign link is a permanent URL (D8), so resolving it once at
    enqueue time is stable; the worker has no host configuration.
    """

    def __init__(self, links: LinkBuilder, campaign_link: CampaignLink) -> None:
        self._links = links
        self._campaign_link = campaign_link

    async def for_action(self, action_id: UUID) -> OrderMailLinks:
        return OrderMailLinks(
            campaign_url=await self._campaign_link(action_id),
            privacy_url=self._links.site_url("/datenschutz"),
            imprint_url=self._links.site_url("/impressum"),
        )


def order_mail_event(
    kind: OrderMailKind,
    *,
    action_id: UUID,
    commitment_id: UUID,
    links: OrderMailLinks,
) -> PendingOutboxEvent:
    """The single job of one mail kind for one order."""

    key = f"order-{kind.value}-mail:{commitment_id}"
    return PendingOutboxEvent(
        id=uuid5(ORDER_MAIL_NAMESPACE, key),
        aggregate_type="commitment",
        aggregate_id=commitment_id,
        event_type=EVENT_TYPES[kind],
        idempotency_key=key,
        payload={
            "actionId": str(action_id),
            "commitmentId": str(commitment_id),
            **links.payload(),
        },
    )


@dataclass(frozen=True, slots=True)
class OrderCancellationFacts:
    cancelled_at: datetime
    # The order's invoice that the cancellation cancelled with it, if any.
    invoice_number: str | None = None


@dataclass(frozen=True, slots=True)
class OrderMailFacts:
    """What Core knows about the order when the mail is sent."""

    action_name: str
    commitment: Commitment
    ordered_at: datetime
    cancellation: OrderCancellationFacts | None = None


@dataclass(frozen=True, slots=True)
class RenderedOrderMail:
    recipient: str
    subject: str
    text: str


def _clean(value: str) -> str:
    """Stored text on one line, without control or format characters."""

    return single_line(value)


def _money(value: Money) -> str:
    whole, fraction = divmod(value.amount_minor, 100)
    grouped = f"{whole:,}".replace(",", ".")
    symbol = "€" if value.currency == "EUR" else value.currency
    return f"{grouped},{fraction:02d} {symbol}"


def _quantity(line: CommitmentLine) -> str:
    count = line.quantity
    unit = line.unit_snapshot
    if unit is OfferingUnit.BOX:
        label = "Box" if count == 1 else "Boxen"
    elif unit is OfferingUnit.PACKAGE:
        label = "Paket" if count == 1 else "Pakete"
    elif unit is OfferingUnit.PIECE:
        label = "Stück"
    else:
        label = "Sponsoring"
    pieces = (
        f" ({count * line.pieces_per_unit_snapshot} Stück)"
        if unit is not OfferingUnit.PIECE and line.pieces_per_unit_snapshot
        else ""
    )
    return f"{count} {label}{pieces}"


def _local(moment: datetime, zone: ZoneInfo = INSTALLATION_TIME_ZONE) -> datetime:
    return moment.astimezone(zone)


def _day(moment: datetime) -> str:
    return f"{_local(moment):%d.%m.%Y}"


def delivery_window_label(snapshot: dict[str, str]) -> str:
    """ "Samstag, 14.02.2026, 09:00–11:00 Uhr" in the window's own zone."""

    zone_name = snapshot.get("timezone") or INSTALLATION_TIME_ZONE.key
    zone = ZoneInfo(zone_name)
    starts = datetime.fromisoformat(snapshot["startsAt"]).astimezone(zone)
    ends = datetime.fromisoformat(snapshot["endsAt"]).astimezone(zone)
    label = f"{WEEKDAYS[starts.weekday()]}, {starts:%d.%m.%Y}, {starts:%H:%M}–"
    if ends.date() != starts.date():
        label += f"{WEEKDAYS[ends.weekday()]}, {ends:%d.%m.%Y}, "
    return label + f"{ends:%H:%M} Uhr"


def _address(
    recipient: DeliveryRecipientSnapshot | InvoiceRecipientSnapshot,
) -> list[str]:
    city = f"{recipient.postal_code} {recipient.city}"
    if recipient.country_code != "DE":
        city += f" ({recipient.country_code})"
    return [
        f"  {_clean(recipient.recipient_name)}",
        f"  {_clean(recipient.street_line_1)}",
        f"  {_clean(city)}",
    ]


def _lines(commitment: Commitment) -> list[str]:
    rows = [
        f"- {_clean(line.description_snapshot)}: {_quantity(line)} × "
        f"{_money(line.unit_price)} = {_money(line.line_total)}"
        for line in commitment.lines
    ]
    return [*rows, f"Gesamtbetrag: {_money(commitment.total)}"]


def _provider(legal: LegalConfigurationVersion, links: OrderMailLinks) -> list[str]:
    """The club's details as in the Impressum (§ 5 DDG), from Core."""

    configuration = legal.configuration
    issuer = configuration.issuer
    address = f"{issuer.street_line_1}, {issuer.postal_code} {issuer.city}"
    if issuer.country_code != "DE":
        address += f" ({issuer.country_code})"
    lines = [
        "Anbieter",
        _clean(issuer.legal_name),
        _clean(address),
    ]
    if configuration.imprint_representatives:
        lines.append(
            f"Vertreten durch: {_clean(configuration.imprint_representatives)}"
        )
    register = configuration.register_label()
    if configuration.imprint_register_number and configuration.imprint_register_court:
        lines.append(
            _clean(
                f"{register or 'Registereintrag'}: "
                f"{configuration.imprint_register_court}, "
                f"{configuration.imprint_register_number}"
            )
        )
    if configuration.imprint_vat_id:
        lines.append(f"USt-IdNr.: {_clean(configuration.imprint_vat_id)}")
    lines.append(f"E-Mail: {_clean(issuer.email)}")
    if configuration.imprint_phone:
        lines.append(f"Telefon: {_clean(configuration.imprint_phone)}")
    lines.extend(
        [
            f"Impressum: {links.imprint_url}",
            f"Datenschutz: {links.privacy_url}",
        ]
    )
    return lines


def _contact(legal: LegalConfigurationVersion, topic: str) -> str:
    configuration = legal.configuration
    phone = (
        f" oder telefonisch unter {_clean(configuration.imprint_phone)}"
        if configuration.imprint_phone
        else ""
    )
    return (
        f"Bei Fragen {topic} erreichen Sie uns unter "
        f"{_clean(configuration.issuer.email)}{phone}. Bitte nennen Sie dabei "
        "Ihre Bestellnummer."
    )


def _footer(legal: LegalConfigurationVersion, links: OrderMailLinks) -> list[str]:
    privacy = (
        "Informationen zur Verarbeitung Ihrer Daten finden Sie in unserer "
        f"Datenschutzerklärung: {links.privacy_url}"
    )
    return [
        "",
        "Freundliche Grüße",
        _clean(legal.configuration.issuer.legal_name),
        "",
        "-- ",
        privacy,
        "",
        *_provider(legal, links),
    ]


def render_order_confirmation(
    facts: OrderMailFacts,
    legal: LegalConfigurationVersion,
    links: OrderMailLinks,
) -> RenderedOrderMail:
    commitment = facts.commitment
    recipient = _recipient(commitment)
    reference = _reference(commitment)
    lines = [
        "Guten Tag,",
        "",
        f"vielen Dank für Ihre Bestellung bei der Aktion „{_clean(facts.action_name)}“. "
        f"Wir haben sie am {_day(facts.ordered_at)} um "
        f"{_local(facts.ordered_at):%H:%M} Uhr erhalten.",
        "",
        f"Bestellnummer: {reference}",
        "",
        "Ihre Bestellung",
        *_lines(commitment),
    ]
    if commitment.delivery_window_snapshot is not None:
        lines.extend(
            [
                "",
                "Lieferfenster: "
                + delivery_window_label(commitment.delivery_window_snapshot),
            ]
        )
    if commitment.delivery_recipient is not None:
        lines.extend(["", "Lieferanschrift:", *_address(commitment.delivery_recipient)])
    if commitment.invoice_recipient is not None:
        lines.extend(
            ["", "Rechnungsanschrift:", *_address(commitment.invoice_recipient)]
        )
    lines.extend(
        [
            "",
            "Wie es weitergeht",
            "Ein Clubmitglied prüft Ihre Bestellung. Die Rechnung erhalten Sie "
            "separat, sobald der Club die Bestellung geprüft hat.",
        ]
    )
    if links.campaign_url is not None:
        lines.extend(["", f"Zur Aktion: {links.campaign_url}"])
    lines.extend(["", _contact(legal, "zu Ihrer Bestellung"), *_footer(legal, links)])
    return RenderedOrderMail(
        recipient=recipient,
        subject=f"Ihre Bestellung bei {_clean(facts.action_name)} · {reference}",
        text="\n".join(lines) + "\n",
    )


def render_order_cancellation(
    facts: OrderMailFacts,
    legal: LegalConfigurationVersion,
    links: OrderMailLinks,
) -> RenderedOrderMail:
    commitment = facts.commitment
    cancellation = facts.cancellation
    if cancellation is None:
        raise OrderMailError("order_mail_cancellation_missing")
    recipient = _recipient(commitment)
    reference = _reference(commitment)
    lines = [
        "Guten Tag,",
        "",
        f"Ihre Bestellung vom {_day(facts.ordered_at)} bei der Aktion "
        f"„{_clean(facts.action_name)}“ wurde am {_day(cancellation.cancelled_at)} "
        "storniert. Sie wird nicht geliefert.",
        "",
        f"Bestellnummer: {reference}",
        "",
        "Stornierte Bestellung",
        *_lines(commitment),
    ]
    if cancellation.invoice_number is not None:
        lines.extend(
            [
                "",
                f"Die Rechnung {cancellation.invoice_number} zu dieser Bestellung "
                "wurde ebenfalls storniert. Bitte überweisen Sie den Betrag nicht.",
            ]
        )
    if links.campaign_url is not None:
        lines.extend(["", f"Zur Aktion: {links.campaign_url}"])
    lines.extend(["", _contact(legal, "zur Stornierung"), *_footer(legal, links)])
    return RenderedOrderMail(
        recipient=recipient,
        subject=f"Stornierung Ihrer Bestellung bei {_clean(facts.action_name)} · {reference}",
        text="\n".join(lines) + "\n",
    )


def _recipient(commitment: Commitment) -> str:
    email = commitment.buyer.email
    if email is None or not email.strip():
        raise OrderMailError("order_mail_recipient_missing")
    return email.strip()


def _reference(commitment: Commitment) -> str:
    if commitment.public_reference is None:
        raise OrderMailError("order_mail_reference_missing")
    return commitment.public_reference


def recipient_sha256(address: str) -> str:
    """The ledger's recipient digest (``SmtpMailHandler``)."""

    return hashlib.sha256(address.strip().casefold().encode()).hexdigest()


def mail_due(commitment: Commitment) -> bool:
    """Only public orders whose buyer address still exists get a mail.

    Orders entered by members or acquirers never got a confirmation, so they
    get no cancellation notice either; a privacy erasure clears the address.
    """

    return (
        commitment.source is CommitmentSource.PUBLIC_FORM
        and commitment.buyer.email is not None
        and bool(commitment.buyer.email.strip())
    )


class OrderMailReader(Protocol):
    async def facts(
        self, commitment_id: UUID, kind: OrderMailKind
    ) -> OrderMailFacts | None: ...

    async def was_sent(self, idempotency_key: str) -> bool: ...

    async def recent_order_mails(self, recipient_sha256: str, since: datetime) -> int:
        """Order mails sent to this recipient digest since the moment."""
        ...


class ActiveLegalConfiguration(Protocol):
    async def active_configuration(self) -> LegalConfigurationVersion | None: ...


class MailSender(Protocol):
    """Sends ``to``/``subject``/``text`` once per idempotency key."""

    async def handle(self, event: ClaimedOutboxEvent) -> None: ...


class OrderMailHandler:
    """Outbox handler for both order mail kinds."""

    def __init__(
        self,
        kind: OrderMailKind,
        *,
        reader: OrderMailReader,
        legal_configuration: ActiveLegalConfiguration,
        sender: MailSender,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._kind = kind
        self._reader = reader
        self._legal_configuration = legal_configuration
        self._sender = sender
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        commitment_value = event.payload.get("commitmentId")
        if not isinstance(commitment_value, str):
            raise OrderMailError("order_mail_payload_invalid")
        try:
            commitment_id = UUID(commitment_value)
        except ValueError as error:
            raise OrderMailError("order_mail_payload_invalid") from error
        if commitment_id != event.aggregate_id:
            raise OrderMailError("order_mail_payload_invalid")
        links = OrderMailLinks.from_payload(event.payload)
        facts = await self._reader.facts(commitment_id, self._kind)
        if facts is None or not mail_due(facts.commitment):
            # Nothing to send: the order is gone, not public or erased.
            return
        if (
            self._kind is OrderMailKind.CONFIRMATION
            and facts.commitment.status is CommitmentStatus.CANCELLED
        ):
            # Cancelled before the confirmation went out: the cancellation
            # notice tells the buyer everything.
            return
        if await self._reader.was_sent(event.idempotency_key):
            # A re-run of a sent job (lost completion): nothing to send, and
            # the limit must not dead-letter it.
            return
        recent = await self._reader.recent_order_mails(
            recipient_sha256(_recipient(facts.commitment)),
            self._clock() - RECIPIENT_WINDOW,
        )
        if recent >= RECIPIENT_LIMIT:
            raise OrderMailError("order_mail_recipient_limit", retryable=False)
        legal = await self._legal_configuration.active_configuration()
        if legal is None:
            # Retried: the mail must name the club; it waits for a version.
            raise OrderMailError("order_mail_legal_configuration_missing")
        render = (
            render_order_confirmation
            if self._kind is OrderMailKind.CONFIRMATION
            else render_order_cancellation
        )
        mail = render(facts, legal, links)
        # The rendered text lives only in memory; the stored job keeps ids.
        await self._sender.handle(
            replace(
                event,
                payload={
                    "to": mail.recipient,
                    "subject": mail.subject,
                    "text": mail.text,
                },
            )
        )
