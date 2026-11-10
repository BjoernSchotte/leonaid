"""Buyer mail settings of an action, mail status of an order, "send again".

Managers only. The status of a mail is derived, never stored: the SMTP ledger
(``mail_delivery``) says what was sent, the outbox says what waits or failed,
and ``mail_not_due_reason`` (for the delivery-day mail
``delivery_day_not_due_reason``) says why nothing is due. A resend is a new outbox
job of the same kind whose key ends in ``:resend:{n}``; the worker applies
the same rules to it as to the first mail (order read at send time, mailbox
limit, erased buyer), so a resend can never reach a buyer the first mail
would not reach now.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from leonaid.application.commitments import IDEMPOTENCY_KEY
from leonaid.application.errors import Conflict
from leonaid.application.order_mails import (
    KEY_PREFIXES,
    RESEND_MARKER,
    MailNotDueReason,
    OrderMailKind,
    OrderMailLinkResolver,
    OrderMailLinks,
    delivery_day_not_due_reason,
    mail_not_due_reason,
    order_mail_key,
)
from leonaid.application.policies import require_action_manager
from leonaid.domain.buyer_mails import (
    DEFAULT_DELIVERY_DAY_SEND_TIME,
    BuyerMailConfiguration,
)
from leonaid.domain.calendar import INSTALLATION_TIME_ZONE
from leonaid.domain.commitments import Commitment, CommitmentStatus
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal

RECIPIENT_LIMIT_ERROR = "order_mail_recipient_limit"


class BuyerMailState(StrEnum):
    NOT_DUE = "not_due"
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class BuyerMailReason(StrEnum):
    """Why a mail is not due, was skipped or failed."""

    NO_EMAIL = MailNotDueReason.NO_EMAIL.value
    SWITCHED_OFF = MailNotDueReason.SWITCHED_OFF.value
    ORDER_DRAFT = MailNotDueReason.ORDER_DRAFT.value
    # A confirmation of an order that is cancelled meanwhile.
    ORDER_CANCELLED = "order_cancelled"
    # The mail would be due now, but no job was written when the order was
    # recorded or cancelled (for example the switch was off then).
    NOT_REQUESTED = "not_requested"
    # The job ended without a mail and the reason no longer holds.
    NOT_SENT = "not_sent"
    RECIPIENT_LIMIT = "recipient_limit"
    DELIVERY_FAILED = "delivery_failed"
    # Delivery-day mail: the board already recorded the delivery (delivered
    # or missed), the mail goes out on the delivery day, the window is over.
    DELIVERY_RECORDED = MailNotDueReason.DELIVERY_RECORDED.value
    SCHEDULED = MailNotDueReason.SCHEDULED.value
    WINDOW_OVER = MailNotDueReason.WINDOW_OVER.value


@dataclass(frozen=True, slots=True)
class BuyerMailJob:
    """One outbox job of an order mail, without its payload."""

    key: str
    status: str
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class BuyerMailLedger:
    """What Core knows about the mails of one order."""

    commitment: Commitment
    internal_order_mails: bool
    # The status a cancelled order left; ``None`` while it is not cancelled.
    previous_status: CommitmentStatus | None = None
    jobs: tuple[BuyerMailJob, ...] = ()
    # Ledger rows: job key and send time.
    sent: tuple[tuple[str, datetime], ...] = ()
    # Delivery-day mail: the action's switch and send time, the zone its
    # delivery days are counted in, and what the board recorded for the
    # order ("delivered" or "missed").
    delivery_day_mail: bool = False
    delivery_day_send_time: time = DEFAULT_DELIVERY_DAY_SEND_TIME
    delivery_zone: ZoneInfo = INSTALLATION_TIME_ZONE
    drop_state: str | None = None


@dataclass(frozen=True, slots=True)
class BuyerMailStatus:
    kind: OrderMailKind
    state: BuyerMailState
    sent_at: datetime | None = None
    reason: BuyerMailReason | None = None
    can_resend: bool = False


def _sequence(kind: OrderMailKind, commitment: Commitment, key: str) -> int | None:
    """0 for the first job of the kind, n for its n-th resend, else ``None``.

    The delivery-day mail counts per window: jobs for a window the order has
    left do not belong to the mail of its window now.
    """

    if kind is OrderMailKind.DELIVERY_DAY:
        if commitment.delivery_window_id is None:
            return None
        base = order_mail_key(
            kind, commitment.id, window_id=commitment.delivery_window_id
        )
    else:
        base = f"{KEY_PREFIXES[kind]}{commitment.id}"
    if key == base:
        return 0
    prefix = f"{base}{RESEND_MARKER}"
    number = key.removeprefix(prefix)
    if key.startswith(prefix) and number.isascii() and number.isdigit():
        return int(number)
    return None


def last_sequence(kind: OrderMailKind, ledger: BuyerMailLedger) -> int | None:
    """The newest job or ledger row of the kind; ``None`` without any."""

    numbers = [
        number
        for key in (
            *(job.key for job in ledger.jobs),
            *(key for key, _ in ledger.sent),
        )
        if (number := _sequence(kind, ledger.commitment, key)) is not None
    ]
    return max(numbers, default=None)


def _not_due(
    kind: OrderMailKind, ledger: BuyerMailLedger, now: datetime
) -> BuyerMailReason | None:
    if kind is OrderMailKind.DELIVERY_DAY:
        day_reason = delivery_day_not_due_reason(
            ledger.commitment,
            delivery_day_mail=ledger.delivery_day_mail,
            drop_state=ledger.drop_state,
            zone=ledger.delivery_zone,
            now=now,
            send_time=ledger.delivery_day_send_time,
        )
        return BuyerMailReason(day_reason.value) if day_reason is not None else None
    reason = mail_not_due_reason(
        ledger.commitment,
        internal_order_mails=ledger.internal_order_mails,
        status=ledger.previous_status,
    )
    if reason is not None:
        return BuyerMailReason(reason.value)
    if (
        kind is OrderMailKind.CONFIRMATION
        and ledger.commitment.status is CommitmentStatus.CANCELLED
    ):
        return BuyerMailReason.ORDER_CANCELLED
    return None


def buyer_mail_status(
    kind: OrderMailKind, ledger: BuyerMailLedger, *, now: datetime
) -> BuyerMailStatus:
    """The state of one mail kind: its newest job decides."""

    order = ledger.commitment
    sent = {
        number: sent_at
        for key, sent_at in ledger.sent
        if (number := _sequence(kind, order, key)) is not None
    }
    jobs = {
        number: job
        for job in ledger.jobs
        if (number := _sequence(kind, order, job.key)) is not None
    }
    sent_at = max(sent.values(), default=None)
    not_due = _not_due(kind, ledger, now)
    latest = last_sequence(kind, ledger)
    if latest is None:
        return BuyerMailStatus(
            kind,
            BuyerMailState.NOT_DUE,
            # No job yet. A confirmation or notice that would be due was
            # never requested; a delivery-day mail that is due is picked up
            # by the next sweep.
            reason=not_due
            or (
                BuyerMailReason.SCHEDULED
                if kind is OrderMailKind.DELIVERY_DAY
                else BuyerMailReason.NOT_REQUESTED
            ),
        )
    if latest in sent:
        return BuyerMailStatus(
            kind, BuyerMailState.SENT, sent_at=sent_at, can_resend=not_due is None
        )
    job = jobs[latest]
    if job.status in {"pending", "processing"}:
        return BuyerMailStatus(kind, BuyerMailState.QUEUED, sent_at=sent_at)
    if job.status == "dead_letter":
        return BuyerMailStatus(
            kind,
            BuyerMailState.FAILED,
            sent_at=sent_at,
            reason=(
                BuyerMailReason.RECIPIENT_LIMIT
                if job.error_code == RECIPIENT_LIMIT_ERROR
                else BuyerMailReason.DELIVERY_FAILED
            ),
            can_resend=not_due is None,
        )
    # Completed without a ledger row: the worker found nothing to send.
    return BuyerMailStatus(
        kind,
        BuyerMailState.SKIPPED,
        sent_at=sent_at,
        reason=not_due or BuyerMailReason.NOT_SENT,
    )


def applicable_kinds(ledger: BuyerMailLedger) -> tuple[OrderMailKind, ...]:
    """The confirmation always; the cancellation notice once cancelled; the
    delivery-day mail for an order with a window, while the action sends it
    or once a job for this window exists."""

    kinds = [OrderMailKind.CONFIRMATION]
    if ledger.commitment.delivery_window_id is not None and (
        ledger.delivery_day_mail
        or last_sequence(OrderMailKind.DELIVERY_DAY, ledger) is not None
    ):
        kinds.append(OrderMailKind.DELIVERY_DAY)
    if ledger.commitment.status is CommitmentStatus.CANCELLED:
        kinds.append(OrderMailKind.CANCELLATION)
    return tuple(kinds)


def buyer_mail_statuses(
    ledger: BuyerMailLedger, *, now: datetime
) -> tuple[BuyerMailStatus, ...]:
    return tuple(
        buyer_mail_status(kind, ledger, now=now) for kind in applicable_kinds(ledger)
    )


def resend_refusal(
    kind: OrderMailKind, ledger: BuyerMailLedger, *, now: datetime
) -> Conflict | None:
    """Why the mail cannot be sent again now; ``None`` when it can."""

    if kind not in applicable_kinds(ledger):
        return Conflict(
            "buyer_mail_not_applicable",
            "Diese E-Mail gibt es für die Bestellung nicht.",
        )
    status = buyer_mail_status(kind, ledger, now=now)
    if status.can_resend:
        return None
    if status.state is BuyerMailState.QUEUED:
        return Conflict(
            "buyer_mail_already_queued",
            "Diese E-Mail wartet bereits auf den Versand.",
        )
    if status.state in {BuyerMailState.SENT, BuyerMailState.FAILED}:
        return Conflict(
            "buyer_mail_not_due",
            "Diese E-Mail kann nicht mehr gesendet werden: Die Bestellung ist "
            "storniert oder geliefert, hat keine E-Mail-Adresse mehr, das "
            "Lieferfenster ist vorbei oder die E-Mails der Aktion sind "
            "ausgeschaltet.",
        )
    return Conflict(
        "buyer_mail_resend_not_allowed",
        "Nur eine gesendete oder fehlgeschlagene E-Mail kann erneut gesendet werden.",
    )


def resend_fingerprint(
    *, action_id: UUID, commitment_id: UUID, kind: OrderMailKind, actor_user_id: UUID
) -> str:
    canonical = f"{action_id}:{commitment_id}:{kind.value}:{actor_user_id}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class BuyerMailRepository(Protocol):
    async def configuration(self, action_id: UUID) -> BuyerMailConfiguration: ...

    async def save_configuration(
        self,
        configuration: BuyerMailConfiguration,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> BuyerMailConfiguration:
        """Compare-and-swap on ``configuration.revision``."""
        ...

    async def ledger(
        self, *, action_id: UUID, commitment_id: UUID
    ) -> BuyerMailLedger: ...

    async def resend(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        kind: OrderMailKind,
        actor_user_id: UUID,
        links: OrderMailLinks,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> BuyerMailLedger:
        """Queue the next resend job, or replay the stored command."""
        ...


class BuyerMailService:
    def __init__(
        self,
        repository: BuyerMailRepository,
        *,
        mail_links: OrderMailLinkResolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._mail_links = mail_links
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def configuration(
        self, actor: IdentityPrincipal, action_id: UUID
    ) -> BuyerMailConfiguration:
        require_action_manager(actor, action_id)
        return await self._repository.configuration(action_id)

    async def save_configuration(
        self,
        actor: IdentityPrincipal,
        configuration: BuyerMailConfiguration,
        *,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> BuyerMailConfiguration:
        require_action_manager(actor, configuration.action_id)
        return await self._repository.save_configuration(
            configuration,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )

    async def statuses(
        self, actor: IdentityPrincipal, action_id: UUID, commitment_id: UUID
    ) -> tuple[BuyerMailStatus, ...]:
        require_action_manager(actor, action_id)
        return buyer_mail_statuses(
            await self._repository.ledger(
                action_id=action_id, commitment_id=commitment_id
            ),
            now=self._clock(),
        )

    async def resend(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        commitment_id: UUID,
        kind: OrderMailKind,
        *,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> BuyerMailStatus:
        require_action_manager(actor, action_id)
        if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise DomainInvariantError(
                "commitment_idempotency_key_invalid",
                "Die Vorgangs-ID besitzt ein ungültiges Format.",
            )
        # Resolved before the transaction holds a connection.
        links = await self._mail_links.for_action(action_id)
        moment = occurred_at or self._clock()
        ledger = await self._repository.resend(
            action_id=action_id,
            commitment_id=commitment_id,
            kind=kind,
            actor_user_id=actor.account.id,
            links=links,
            idempotency_key=idempotency_key,
            request_hash=resend_fingerprint(
                action_id=action_id,
                commitment_id=commitment_id,
                kind=kind,
                actor_user_id=actor.account.id,
            ),
            request_id=request_id,
            occurred_at=moment,
        )
        return buyer_mail_status(kind, ledger, now=moment)
