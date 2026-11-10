"""Transactional mails to the buyer of an order.

Three mails: the order confirmation, the cancellation notice after
``cancelCommitment`` cancelled the order, and the mail on the delivery day
(``application.delivery_day_mails`` queues it, see below). A public order is confirmed when it
is recorded. An order that a member or acquirer entered is confirmed when it
becomes ``review_ready`` (at creation or by ``completeCommitment``), and only
while the action has ``internal_order_mails`` switched on
(``mail_not_due_reason``). Both are outbox jobs written in the same
transaction as the order, its completion or the cancellation. The job payload
holds ids and the non-personal links only; the worker reads the order from
Core when it sends, so a privacy erasure that ran in between leaves nothing
to send, and no copy of the buyer's data waits in the queue.

The delivery-day mail tells the buyer the window on the day of the delivery,
for orders of every source, while the action has ``delivery_day_mail`` on. A
sweep in the worker queues it (``delivery_day_not_due_reason`` is the rule);
its key also names the window, so an order that moved to another window gets
the mail for the new one. The worker checks the rule again when it sends: a
cancelled, delivered, erased or moved order gets nothing, and neither does a
job that was held up until the window was over.

One job per order and kind: the job id and the idempotency key are derived
from the order id, and the HTTP replay of an order or a cancellation returns
before it writes a job. A manager can send a mail again
(``application.buyer_mails``); that job's key ends in ``:resend:{n}``, and
the order id stays the second key segment, which the mailbox limit's ledger
join relies on. Delivery is at least once: the SMTP ledger
(``mail_delivery``) skips a key that was already sent when a job is retried
or claimed again, but a crash between the SMTP server accepting the mail and
the ledger write sends it a second time on the retry.

The order lines, prices, addresses and window of a public order cannot be
changed after it is placed, so the order read at send time is the order as
placed. A manager may still correct the address of an internal order
(``completeCommitmentDelivery``); the mail shows the order as it is when it
is sent, and a later change sends no second confirmation. A confirmation
whose order is already cancelled is skipped; the cancellation notice covers
it.

The text contains only what the buyer entered (items, quantities, delivery
window, addresses) and the club's details from the active legal
configuration. Internal data stays out: the order message, the delivery
contact, the cancellation reason and note, CRM names. Every stored text is
put on one line without control or format characters (``_clean``), so data
entered before the input check cannot forge a paragraph or hide text.

At most ``RECIPIENT_LIMIT`` order mails go to one mailbox per
``RECIPIENT_WINDOW`` (``+tags`` and Gmail dots count as one mailbox, and an
advisory lock per mailbox keeps parallel workers under the limit): neither
the unauthenticated form nor a repeated "send again" must make the club
flood an address it does not own. A job over the limit is dead-lettered with
``order_mail_recipient_limit`` and shows in the operations view, where an
operator can retry it later.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta, timezone
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
ORDER_DELIVERY_DAY_MAIL = "order.delivery_day.mail.v1"
ORDER_MAIL_EVENT_TYPES = (
    ORDER_CONFIRMATION_MAIL,
    ORDER_CANCELLATION_MAIL,
    ORDER_DELIVERY_DAY_MAIL,
)
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
    DELIVERY_DAY = "delivery_day"


EVENT_TYPES = {
    OrderMailKind.CONFIRMATION: ORDER_CONFIRMATION_MAIL,
    OrderMailKind.CANCELLATION: ORDER_CANCELLATION_MAIL,
    OrderMailKind.DELIVERY_DAY: ORDER_DELIVERY_DAY_MAIL,
}
KEY_PREFIXES = {
    OrderMailKind.CONFIRMATION: "order-confirmation-mail:",
    OrderMailKind.CANCELLATION: "order-cancellation-mail:",
    OrderMailKind.DELIVERY_DAY: "order-delivery-day-mail:",
}
RESEND_MARKER = ":resend:"
ORDER_MAIL_KEY_PREFIXES = tuple(KEY_PREFIXES.values())


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


# The action's public page for the mail, or None for no link: the permanent
# edition URL of decision D8 on its campaign host, else the public host page
# (``AsyncpgSiteDirectory.edition_link``).
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


def order_mail_key(
    kind: OrderMailKind,
    commitment_id: UUID,
    *,
    window_id: UUID | None = None,
    resend: int | None = None,
) -> str:
    """``order-{kind}-mail:{order id}``, plus ``:resend:{n}`` for a resend.

    The delivery-day mail also names its window, after the order id:
    ``order-delivery-day-mail:{order id}:{window id}``. The order id is the
    second segment of every key (``recent_order_mails`` joins on it).
    """

    if (kind is OrderMailKind.DELIVERY_DAY) != (window_id is not None):
        raise ValueError("Only the delivery-day mail is keyed by a window.")
    key = f"{KEY_PREFIXES[kind]}{commitment_id}"
    if window_id is not None:
        key = f"{key}:{window_id}"
    if resend is None:
        return key
    if resend < 1:
        raise ValueError("A resend is numbered from 1.")
    return f"{key}{RESEND_MARKER}{resend}"


def order_mail_event(
    kind: OrderMailKind,
    *,
    action_id: UUID,
    commitment_id: UUID,
    links: OrderMailLinks,
    resend: int | None = None,
    window_id: UUID | None = None,
) -> PendingOutboxEvent:
    """The single job of one mail kind for one order, or its n-th resend."""

    key = order_mail_key(kind, commitment_id, window_id=window_id, resend=resend)
    return PendingOutboxEvent(
        id=uuid5(ORDER_MAIL_NAMESPACE, key),
        aggregate_type="commitment",
        aggregate_id=commitment_id,
        event_type=EVENT_TYPES[kind],
        idempotency_key=key,
        payload={
            "actionId": str(action_id),
            "commitmentId": str(commitment_id),
            **({"windowId": str(window_id)} if window_id is not None else {}),
            **links.payload(),
        },
    )


@dataclass(frozen=True, slots=True)
class OrderCancellationFacts:
    cancelled_at: datetime
    # The order's invoice that the cancellation cancelled with it, if any.
    invoice_number: str | None = None
    # The status the order left: an internal draft was never confirmed.
    previous_status: CommitmentStatus = CommitmentStatus.REVIEW_READY


@dataclass(frozen=True, slots=True)
class OrderMailFacts:
    """What Core knows about the order when the mail is sent."""

    action_name: str
    commitment: Commitment
    ordered_at: datetime
    cancellation: OrderCancellationFacts | None = None
    # The action's switch for orders that members and acquirers enter.
    internal_order_mails: bool = False
    # The action's status and whether it issues invoices; what the delivery
    # board recorded for the order ("delivered" or "missed").
    action_status: str = "active"
    invoicing: bool = True
    drop_state: str | None = None
    # The action's switch for the mail on the delivery day, whether it still
    # has the delivery capability, and the zone its delivery days are
    # counted in.
    delivery_day_mail: bool = False
    delivery_capability: bool = True
    delivery_zone: ZoneInfo = INSTALLATION_TIME_ZONE

    def delivery_day_not_due_reason(self, *, now: datetime) -> MailNotDueReason | None:
        """Why the delivery-day mail is not sent now; ``None`` when it is."""

        return delivery_day_not_due_reason(
            self.commitment,
            delivery_day_mail=self.delivery_day_mail and self.delivery_capability,
            drop_state=self.drop_state,
            action_status=self.action_status,
            zone=self.delivery_zone,
            now=now,
        )

    def not_due_reason(
        self, kind: OrderMailKind, *, now: datetime
    ) -> MailNotDueReason | None:
        """Why this order gets no mail of the kind now; ``None`` when due."""

        if kind is OrderMailKind.DELIVERY_DAY:
            return self.delivery_day_not_due_reason(now=now)

        if kind is OrderMailKind.CONFIRMATION:
            return confirmation_not_due_reason(
                self.commitment,
                internal_order_mails=self.internal_order_mails,
                drop_state=self.drop_state,
                action_status=self.action_status,
                now=now,
            )
        return mail_not_due_reason(
            self.commitment,
            internal_order_mails=self.internal_order_mails,
            status=(
                self.cancellation.previous_status
                if self.cancellation is not None
                else None
            ),
        )


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
    thanks = (
        f"vielen Dank für Ihre Bestellung bei der Aktion „{_clean(facts.action_name)}“."
    )
    if commitment.source is CommitmentSource.PUBLIC_FORM:
        opening = [
            f"{thanks} Wir haben sie am {_day(facts.ordered_at)} um "
            f"{_local(facts.ordered_at):%H:%M} Uhr erhalten."
        ]
    else:
        # The buyer filled in no form: say who recorded the order. The time
        # of a draft or of a queued capture is not the buyer's order time.
        issuer = legal.configuration.issuer
        opening = [
            thanks,
            "",
            "Ihre Bestellung wurde von einem Mitglied des "
            f"{_clean(issuer.legal_name)} für Sie erfasst. Stimmt etwas "
            f"nicht, schreiben Sie uns bitte an {_clean(issuer.email)}.",
        ]
    lines = [
        "Guten Tag,",
        "",
        *opening,
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
    next_steps = _next_steps(facts)
    if next_steps:
        lines.extend(["", "Wie es weitergeht", next_steps])
    if links.campaign_url is not None:
        lines.extend(["", f"Zur Aktion: {links.campaign_url}"])
    lines.extend(["", _contact(legal, "zu Ihrer Bestellung"), *_footer(legal, links)])
    return RenderedOrderMail(
        recipient=recipient,
        subject=f"Ihre Bestellung bei {_clean(facts.action_name)} · {reference}",
        text="\n".join(lines) + "\n",
    )


def _next_steps(facts: OrderMailFacts) -> str:
    """What is still to come for this order, as it is when the mail goes out.

    The mail may be sent, or sent again, at any later status: it must not
    promise a review that is done or an invoice that the action never
    issues or has issued already.
    """

    status = facts.commitment.status
    if status is CommitmentStatus.INVOICED:
        return (
            "Die Rechnung zu dieser Bestellung ist ausgestellt."
            if facts.invoicing
            else ""
        )
    if status is CommitmentStatus.CONFIRMED:
        return (
            "Ihre Bestellung ist bestätigt. Die Rechnung erhalten Sie separat."
            if facts.invoicing
            else "Ihre Bestellung ist bestätigt."
        )
    if facts.invoicing:
        return (
            "Ein Clubmitglied prüft Ihre Bestellung. Die Rechnung erhalten Sie "
            "separat, sobald der Club die Bestellung geprüft hat."
        )
    return "Ein Clubmitglied prüft Ihre Bestellung."


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


def render_delivery_day(
    facts: OrderMailFacts,
    legal: LegalConfigurationVersion,
    links: OrderMailLinks,
    *,
    now: datetime,
) -> RenderedOrderMail:
    """ "Your delivery comes today between 10:00 and 12:00."

    The window, the delivery address, the quantities and the club's contact.
    Nothing about the tour: no driver, no phone of a driver, no note for the
    driver and no delivery contact.
    """

    commitment = facts.commitment
    snapshot = commitment.delivery_window_snapshot
    if snapshot is None:
        raise OrderMailError("order_mail_window_missing")
    recipient = _recipient(commitment)
    zone = facts.delivery_zone
    starts = datetime.fromisoformat(snapshot["startsAt"]).astimezone(zone)
    ends = datetime.fromisoformat(snapshot["endsAt"]).astimezone(zone)
    between = f"zwischen {starts:%H:%M} und {ends:%H:%M} Uhr"
    lines = [
        "Guten Morgen," if now.astimezone(zone).hour < 11 else "Guten Tag,",
        "",
        f"Ihre Bestellung {_reference(commitment)} bei der Aktion "
        f"„{_clean(facts.action_name)}“ wird heute, "
        f"{WEEKDAYS[starts.weekday()]}, {starts:%d.%m.%Y}, {between} geliefert.",
    ]
    if commitment.delivery_recipient is not None:
        lines.extend(["", "Lieferadresse:", *_address(commitment.delivery_recipient)])
    lines.extend(
        [
            "",
            "Bestellt:",
            *(
                f"- {_clean(line.description_snapshot)}: {_quantity(line)}"
                for line in commitment.lines
            ),
            *_delivery_day_contact(legal),
            *_footer(legal, links),
        ]
    )
    return RenderedOrderMail(
        recipient=recipient,
        subject=f"Ihre Lieferung kommt heute {between}",
        text="\n".join(lines) + "\n",
    )


def _delivery_day_contact(legal: LegalConfigurationVersion) -> list[str]:
    """What to do when nobody is home: only channels the club configured.

    No sentence at all when the legal configuration names neither an e-mail
    address nor a phone number.
    """

    email = _clean(legal.configuration.issuer.email or "")
    phone = _clean(legal.configuration.imprint_phone or "")
    opening = "Ist in dieser Zeit niemand da, "
    if email and phone:
        sentence = (
            f"{opening}schreiben Sie uns bitte an {email} "
            f"oder rufen Sie uns an: {phone}."
        )
    elif email:
        sentence = f"{opening}schreiben Sie uns bitte an {email}."
    elif phone:
        sentence = f"{opening}rufen Sie uns bitte an: {phone}."
    else:
        return []
    return ["", sentence]


def _recipient(commitment: Commitment) -> str:
    email = commitment.buyer.email
    if email is None or not email.strip():
        raise OrderMailError("order_mail_recipient_missing")
    return email.strip()


def _reference(commitment: Commitment) -> str:
    return commitment.public_reference


def recipient_sha256(address: str) -> str:
    """The ledger's recipient digest (``SmtpMailHandler``)."""

    return hashlib.sha256(address.strip().casefold().encode()).hexdigest()


# Providers that ignore dots in the local part of an address.
DOTLESS_DOMAINS = {"gmail.com": "gmail.com", "googlemail.com": "gmail.com"}


def mailbox_key(address: str) -> str:
    """The mailbox an address reaches, for the per-recipient limit only.

    ``victim+1@…`` and ``victim+2@…`` reach the same mailbox, and Gmail
    ignores dots (``v.ictim@gmail.com``). The mail still goes to the address
    as entered; only the limit counts them together.
    """

    normalized = address.strip().casefold()
    local, separator, domain = normalized.rpartition("@")
    if not separator:
        return normalized
    local = local.split("+", 1)[0]
    if domain in DOTLESS_DOMAINS:
        domain = DOTLESS_DOMAINS[domain]
        local = local.replace(".", "")
    return f"{local}@{domain}"


def limit_digest(address: str) -> str:
    return hashlib.sha256(mailbox_key(address).encode()).hexdigest()


class MailNotDueReason(StrEnum):
    NO_EMAIL = "no_email"
    SWITCHED_OFF = "switched_off"
    ORDER_DRAFT = "order_draft"
    # Confirmation and delivery-day mail: it would come too late or tell the
    # buyer nothing.
    ORDER_CANCELLED = "order_cancelled"
    DELIVERY_RECORDED = "delivery_recorded"
    WINDOW_OVER = "window_over"
    ACTION_CLOSED = "action_closed"
    # Delivery-day mail only: it goes out on the delivery day; the window
    # ends before the action's send time, so no mail goes out for it.
    SCHEDULED = "scheduled"
    WINDOW_BEFORE_SEND_TIME = "window_before_send_time"


# An action whose order period is over: orders are only recorded afterwards.
CLOSED_ACTION_STATUSES = frozenset({"completed", "archived"})


def mail_not_due_reason(
    commitment: Commitment,
    *,
    internal_order_mails: bool,
    status: CommitmentStatus | None = None,
) -> MailNotDueReason | None:
    """The one rule for confirmation and cancellation notice.

    A mail needs the buyer's address (a privacy erasure clears it). A public
    order always gets its mails. An order that a member or acquirer entered
    gets them only while the action has ``internal_order_mails``, and never
    as a draft: a draft was not confirmed, so its cancellation is no news to
    the buyer. ``status`` is the status to judge by when the order's own is
    not it: the status a cancelled order left.
    """

    if commitment.buyer.email is None or not commitment.buyer.email.strip():
        return MailNotDueReason.NO_EMAIL
    if commitment.source is CommitmentSource.PUBLIC_FORM:
        return None
    if not internal_order_mails:
        return MailNotDueReason.SWITCHED_OFF
    if (status or commitment.status) is CommitmentStatus.DRAFT:
        return MailNotDueReason.ORDER_DRAFT
    return None


def confirmation_not_due_reason(
    commitment: Commitment,
    *,
    internal_order_mails: bool,
    drop_state: str | None,
    action_status: str,
    now: datetime,
) -> MailNotDueReason | None:
    """The rule of the order confirmation, at any moment it could go out.

    On top of ``mail_not_due_reason``: a confirmation is no news for an order
    that is cancelled (the cancellation notice covers it), whose delivery the
    board already recorded, whose delivery window is over, or whose action is
    completed or archived. That keeps a late sync from the PWA queue, a
    manager who records a delivery afterwards and "send again" from thanking
    a buyer for an order that is long done.
    """

    reason = mail_not_due_reason(commitment, internal_order_mails=internal_order_mails)
    if reason is not None:
        return reason
    if commitment.status is CommitmentStatus.CANCELLED:
        return MailNotDueReason.ORDER_CANCELLED
    if drop_state is not None:
        return MailNotDueReason.DELIVERY_RECORDED
    snapshot = commitment.delivery_window_snapshot
    if snapshot is not None and now >= datetime.fromisoformat(snapshot["endsAt"]):
        return MailNotDueReason.WINDOW_OVER
    if action_status in CLOSED_ACTION_STATUSES:
        return MailNotDueReason.ACTION_CLOSED
    return None


def mail_key_sequence(idempotency_key: str) -> tuple[str, int]:
    """The first key of a mail and the job's place in its resends.

    ``("order-confirmation-mail:{order id}", 0)`` for the first job and
    ``(…, n)`` for ``…:resend:{n}``.
    """

    base, marker, number = idempotency_key.partition(RESEND_MARKER)
    if not marker:
        return idempotency_key, 0
    if not (number.isascii() and number.isdigit()):
        raise OrderMailError("order_mail_payload_invalid")
    return base, int(number)


def mail_due(
    commitment: Commitment,
    *,
    internal_order_mails: bool,
    status: CommitmentStatus | None = None,
) -> bool:
    return (
        mail_not_due_reason(
            commitment, internal_order_mails=internal_order_mails, status=status
        )
        is None
    )


def delivery_day_not_due_reason(
    commitment: Commitment,
    *,
    delivery_day_mail: bool,
    drop_state: str | None,
    zone: ZoneInfo,
    now: datetime,
    action_status: str = "active",
    send_time: time | None = None,
) -> MailNotDueReason | None:
    """The rule of the delivery-day mail; ``None`` when it is due now.

    Due: the buyer has an address, the action has ``delivery_day_mail`` (and
    still the delivery capability; the caller folds that in), the order is
    review-ready, confirmed or invoiced, the board recorded nothing for it
    yet, the action is not completed or archived, its window starts today in
    the action's zone and is not over. With ``send_time`` (the sweep and the
    status) the mail is also not due before that local time, and a window
    that ends at or before the send time of its day never gets the mail
    (``WINDOW_BEFORE_SEND_TIME``); the worker, which sends a job that the
    sweep already queued, passes none. Orders of every source follow this
    rule.
    """

    snapshot = commitment.delivery_window_snapshot
    if snapshot is None:
        raise ValueError("The delivery-day mail needs an order with a window.")
    if commitment.buyer.email is None or not commitment.buyer.email.strip():
        return MailNotDueReason.NO_EMAIL
    if not delivery_day_mail:
        return MailNotDueReason.SWITCHED_OFF
    if commitment.status is CommitmentStatus.CANCELLED:
        return MailNotDueReason.ORDER_CANCELLED
    if commitment.status is CommitmentStatus.DRAFT:
        return MailNotDueReason.ORDER_DRAFT
    if drop_state is not None:
        return MailNotDueReason.DELIVERY_RECORDED
    if action_status in CLOSED_ACTION_STATUSES:
        return MailNotDueReason.ACTION_CLOSED
    ends_at = datetime.fromisoformat(snapshot["endsAt"])
    delivery_day = datetime.fromisoformat(snapshot["startsAt"]).astimezone(zone).date()
    if send_time is not None and ends_at <= datetime.combine(
        delivery_day, send_time, tzinfo=zone
    ):
        return MailNotDueReason.WINDOW_BEFORE_SEND_TIME
    if now >= ends_at:
        return MailNotDueReason.WINDOW_OVER
    today = now.astimezone(zone)
    if today.date() < delivery_day:
        return MailNotDueReason.SCHEDULED
    if (
        send_time is not None
        and today.date() == delivery_day
        and today.time().replace(tzinfo=None) < send_time
    ):
        return MailNotDueReason.SCHEDULED
    return None


class OrderMailReader(Protocol):
    async def facts(
        self, commitment_id: UUID, kind: OrderMailKind
    ) -> OrderMailFacts | None: ...

    async def was_sent(self, idempotency_key: str) -> bool: ...

    async def sent_keys(self, first_key: str) -> tuple[str, ...]:
        """The ledger's keys of one mail: its first key and its resends."""
        ...

    async def recent_order_mails(
        self, *, recipient_sha256: str, mailbox: str, since: datetime
    ) -> int:
        """Order mails sent since the moment to this exact address (ledger
        digest) or to any address of the same mailbox (``mailbox_key``)."""
        ...

    def recipient_lock(self, digest: str) -> AbstractAsyncContextManager[None]:
        """Serializes the limit check and the send per mailbox, so parallel
        workers cannot each see room below the limit."""
        ...


class ActiveLegalConfiguration(Protocol):
    async def active_configuration(self) -> LegalConfigurationVersion | None: ...


class MailSender(Protocol):
    """Sends ``to``/``subject``/``text`` once per idempotency key."""

    async def handle(self, event: ClaimedOutboxEvent) -> None: ...


class OrderMailHandler:
    """Outbox handler for the order mail kinds, first mail and resend alike."""

    def __init__(
        self,
        kind: OrderMailKind,
        *,
        reader: OrderMailReader,
        legal_configuration: ActiveLegalConfiguration,
        sender: MailSender,
        clock: Callable[[], datetime] | None = None,
        recipient_limit: int = RECIPIENT_LIMIT,
    ) -> None:
        self._kind = kind
        self._recipient_limit = recipient_limit
        self._reader = reader
        self._legal_configuration = legal_configuration
        self._sender = sender
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _window_id(event: ClaimedOutboxEvent) -> UUID:
        value = event.payload.get("windowId")
        if not isinstance(value, str):
            raise OrderMailError("order_mail_payload_invalid")
        try:
            return UUID(value)
        except ValueError as error:
            raise OrderMailError("order_mail_payload_invalid") from error

    async def _superseded(self, idempotency_key: str) -> bool:
        """A newer job of this mail (a later resend) is already sent."""

        first_key, sequence = mail_key_sequence(idempotency_key)
        return any(
            mail_key_sequence(key)[1] > sequence
            for key in await self._reader.sent_keys(first_key)
        )

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
        if self._kind is OrderMailKind.DELIVERY_DAY and (
            facts is not None
            and facts.commitment.delivery_window_id != self._window_id(event)
        ):
            # The order moved to another window; the sweep queues the mail
            # for that one under its own key.
            return
        if (
            facts is None
            or facts.not_due_reason(self._kind, now=self._clock()) is not None
        ):
            # Nothing to send: the order is gone or erased, the action
            # switched the mails for internal orders off meanwhile, or (a
            # confirmation) the order is cancelled, delivered or closed.
            return
        if await self._reader.was_sent(event.idempotency_key):
            # A re-run of a sent job (lost completion): nothing to send, and
            # the limit must not dead-letter it.
            return
        if await self._superseded(event.idempotency_key):
            # An operator retried an old failed job after a manager already
            # sent the mail again: the buyer has it.
            return
        legal = await self._legal_configuration.active_configuration()
        if legal is None:
            # Retried: the mail must name the club; it waits for a version.
            raise OrderMailError("order_mail_legal_configuration_missing")
        if self._kind is OrderMailKind.DELIVERY_DAY:
            mail = render_delivery_day(facts, legal, links, now=self._clock())
        elif self._kind is OrderMailKind.CONFIRMATION:
            mail = render_order_confirmation(facts, legal, links)
        else:
            mail = render_order_cancellation(facts, legal, links)
        async with self._reader.recipient_lock(limit_digest(mail.recipient)):
            if await self._reader.was_sent(
                event.idempotency_key
            ) or await self._superseded(event.idempotency_key):
                return
            recent = await self._reader.recent_order_mails(
                recipient_sha256=recipient_sha256(mail.recipient),
                mailbox=mailbox_key(mail.recipient),
                since=self._clock() - RECIPIENT_WINDOW,
            )
            if recent >= self._recipient_limit:
                raise OrderMailError("order_mail_recipient_limit", retryable=False)
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
