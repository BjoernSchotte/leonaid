"""Transactional mails to the buyer of an order.

Two mails: the order confirmation and the cancellation notice after
``cancelCommitment`` cancelled the order. A public order is confirmed when it
is recorded. An order that a member or acquirer entered is confirmed when it
becomes ``review_ready`` (at creation or by ``completeCommitment``), and only
while the action has ``internal_order_mails`` switched on
(``mail_not_due_reason``). Both are outbox jobs written in the same
transaction as the order, its completion or the cancellation. The job payload
holds ids and the non-personal links only; the worker reads the order from
Core when it sends, so a privacy erasure that ran in between leaves nothing
to send, and no copy of the buyer's data waits in the queue.

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

A confirmation is never sent late (``confirmation_not_due_reason``), for an
order of any source. A job that was queued while the confirmation was due
and that the worker reaches too late (worker or SMTP down past the delivery
window, for example) is not sent and its job completes: a dead letter
could never be cleared (a retry would be late again) and would keep the
dead-letter alert firing for good. It is not silent either: the order's mail
status derives "failed" with the reason from a completed job without a sent
mail whose confirmation is late (``application.buyer_mails``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
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
KEY_PREFIXES = {kind: f"order-{kind.value}-mail:" for kind in OrderMailKind}
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
    kind: OrderMailKind, commitment_id: UUID, *, resend: int | None = None
) -> str:
    """``order-{kind}-mail:{order id}``, plus ``:resend:{n}`` for a resend."""

    key = f"{KEY_PREFIXES[kind]}{commitment_id}"
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
) -> PendingOutboxEvent:
    """The single job of one mail kind for one order, or its n-th resend."""

    key = order_mail_key(kind, commitment_id, resend=resend)
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

    def not_due_reason(
        self, kind: OrderMailKind, *, now: datetime
    ) -> MailNotDueReason | None:
        """Why this order gets no mail of the kind now; ``None`` when due."""

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
    # Confirmation only: it would come too late or tell the buyer nothing.
    ORDER_CANCELLED = "order_cancelled"
    DELIVERY_RECORDED = "delivery_recorded"
    WINDOW_OVER = "window_over"
    ACTION_CLOSED = "action_closed"


# An action whose order period is over: orders are only recorded afterwards.
CLOSED_ACTION_STATUSES = frozenset({"completed", "archived"})

# Why a confirmation that was due when it was queued can come too late.
LATE_REASONS = frozenset(
    {
        MailNotDueReason.DELIVERY_RECORDED,
        MailNotDueReason.WINDOW_OVER,
        MailNotDueReason.ACTION_CLOSED,
    }
)


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
    status: CommitmentStatus | None = None,
) -> MailNotDueReason | None:
    """The rule of the order confirmation, at any moment it could go out.

    Orders of every source follow it, public orders included. ``status``
    judges the order as if it had that status (a draft about to be
    completed).

    On top of ``mail_not_due_reason``: a confirmation is no news for an order
    that is cancelled (the cancellation notice covers it), whose delivery the
    board already recorded, whose delivery window is over, or whose action is
    completed or archived. That keeps a late sync from the PWA queue, a
    manager who records a delivery afterwards and "send again" from thanking
    a buyer for an order that is long done.
    """

    reason = mail_not_due_reason(
        commitment, internal_order_mails=internal_order_mails, status=status
    )
    if reason is not None:
        return reason
    if (status or commitment.status) is CommitmentStatus.CANCELLED:
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
        if facts is None:
            # The order is gone.
            return
        not_due = facts.not_due_reason(self._kind, now=self._clock())
        if await self._reader.was_sent(event.idempotency_key):
            # A re-run of a sent job (lost completion): nothing to send, and
            # the limit must not dead-letter it.
            return
        if await self._superseded(event.idempotency_key):
            # An operator retried an old failed job after a manager already
            # sent the mail again: the buyer has it.
            return
        if not_due is not None:
            # Nothing to send: the buyer is erased, the action switched the
            # mails for internal orders off meanwhile, the order is
            # cancelled, or the confirmation comes too late now
            # (``LATE_REASONS``). The job completes in every case: a late
            # one must not stay a dead letter that no retry can clear. The
            # order's mail status still shows a late confirmation as failed.
            return
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
