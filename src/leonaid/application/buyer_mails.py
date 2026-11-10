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
from datetime import datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from leonaid.application.commitments import IDEMPOTENCY_KEY
from leonaid.application.delivery_day_mails import SWEEP_INTERVAL_SECONDS
from leonaid.application.errors import Conflict
from leonaid.application.order_mails import (
    KEY_PREFIXES,
    RESEND_MARKER,
    MailNotDueReason,
    OrderMailKind,
    OrderMailLinkResolver,
    OrderMailLinks,
    delivery_day_not_due_reason,
    confirmation_not_due_reason,
    LATE_REASONS_BY_KIND,
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
# The time the sweep needs at least to queue a mail that became due.
MISSED_MARGIN = timedelta(seconds=SWEEP_INTERVAL_SECONDS)


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
    # A confirmation that would come too late: the order is cancelled, its
    # delivery is recorded, its window is over or its action is closed.
    ORDER_CANCELLED = MailNotDueReason.ORDER_CANCELLED.value
    DELIVERY_RECORDED = MailNotDueReason.DELIVERY_RECORDED.value
    WINDOW_OVER = MailNotDueReason.WINDOW_OVER.value
    ACTION_CLOSED = MailNotDueReason.ACTION_CLOSED.value
    # The mail is due now, but no job exists (for example the switch was off
    # when the order was recorded). A manager can send it.
    NOT_REQUESTED = "not_requested"
    # The newest job ended without a mail and the mail is due now. A manager
    # can send it.
    NOT_SENT = "not_sent"
    RECIPIENT_LIMIT = "recipient_limit"
    DELIVERY_FAILED = "delivery_failed"
    # Delivery-day mail: it goes out on the delivery day at the send time
    # (the sweep queues it), or never because the window ends before the
    # send time of its day.
    SCHEDULED = MailNotDueReason.SCHEDULED.value
    WINDOW_BEFORE_SEND_TIME = MailNotDueReason.WINDOW_BEFORE_SEND_TIME.value


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
    # The action's status and what the delivery board recorded for the order
    # ("delivered" or "missed").
    action_status: str = "active"
    drop_state: str | None = None
    # Delivery-day mail: the action's switch (false also when the action
    # lost the delivery capability), its send time and the zone its delivery
    # days are counted in.
    delivery_day_mail: bool = False
    delivery_day_send_time: time = DEFAULT_DELIVERY_DAY_SEND_TIME
    delivery_zone: ZoneInfo = INSTALLATION_TIME_ZONE
    # Since when the sweep could have queued the delivery-day mail of this
    # order: the later of "the action switched the mail on" and "the order
    # became ready for review". ``None`` when Core cannot tell (no record of
    # the switch).
    delivery_day_eligible_since: datetime | None = None


@dataclass(frozen=True, slots=True)
class BuyerMailStatus:
    kind: OrderMailKind
    state: BuyerMailState
    sent_at: datetime | None = None
    reason: BuyerMailReason | None = None
    # A manager can send the mail now: it is due and no job waits. That is a
    # resend of a mail that went out or failed, and the first send of one
    # that was never queued or whose job ended without a mail.
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
            action_status=ledger.action_status,
            zone=ledger.delivery_zone,
            now=now,
            send_time=ledger.delivery_day_send_time,
        )
        return BuyerMailReason(day_reason.value) if day_reason is not None else None
    reason = (
        confirmation_not_due_reason(
            ledger.commitment,
            internal_order_mails=ledger.internal_order_mails,
            drop_state=ledger.drop_state,
            action_status=ledger.action_status,
            now=now,
        )
        if kind is OrderMailKind.CONFIRMATION
        else mail_not_due_reason(
            ledger.commitment,
            internal_order_mails=ledger.internal_order_mails,
            status=ledger.previous_status,
        )
    )
    return BuyerMailReason(reason.value) if reason is not None else None


@dataclass(frozen=True, slots=True)
class BuyerMailOverview:
    """The mails of one order and, for a draft, what completing it sends."""

    statuses: tuple[BuyerMailStatus, ...]
    draft: bool
    # Why completing the draft now would send no confirmation; ``None`` when
    # it would send one. Only meaningful while ``draft``.
    confirmation_on_completion: BuyerMailReason | None


def _failure_reason(error_code: str | None) -> BuyerMailReason:
    """Why a dead-lettered job failed: the mailbox limit or the delivery."""

    if error_code == RECIPIENT_LIMIT_ERROR:
        return BuyerMailReason.RECIPIENT_LIMIT
    return BuyerMailReason.DELIVERY_FAILED


# A job is only queued while its mail is due. So a job that ended without a
# mail while the confirmation is late now was reached too late by the worker
# (an outage past the delivery window, a retry after it): the buyer got
# nothing, and the order says so. The job itself is completed, not a dead
# letter, because no retry could ever clear it.
# What "late" means differs per kind (``LATE_REASONS_BY_KIND``): a
# delivery-day mail is only missed when its job waited past the window.
_LATE = {
    kind: frozenset(BuyerMailReason(reason.value) for reason in reasons)
    for kind, reasons in LATE_REASONS_BY_KIND.items()
}


def _missed_without_job(
    ledger: BuyerMailLedger, not_due: BuyerMailReason | None
) -> bool:
    """The delivery-day mail was due while its window ran and no job exists.

    Only when the window is over now and nothing else speaks against the
    mail (``WINDOW_OVER`` is the last reason the rule gives), and only when
    the sweep had at least one full interval to queue it: the order was
    eligible (switch on, ready for review) that long before the window
    ended. A window that ended before the switch was turned on, or an order
    recorded afterwards, is no missed mail.
    """

    since = ledger.delivery_day_eligible_since
    snapshot = ledger.commitment.delivery_window_snapshot
    if not_due is not BuyerMailReason.WINDOW_OVER or since is None or snapshot is None:
        return False
    starts_at = datetime.fromisoformat(snapshot["startsAt"])
    ends_at = datetime.fromisoformat(snapshot["endsAt"])
    send_at = datetime.combine(
        starts_at.astimezone(ledger.delivery_zone).date(),
        ledger.delivery_day_send_time,
        tzinfo=ledger.delivery_zone,
    )
    return max(since, send_at) + MISSED_MARGIN <= ends_at


def confirmation_on_completion(
    ledger: BuyerMailLedger, *, now: datetime
) -> BuyerMailReason | None:
    """Why completing this draft now would send no confirmation.

    ``None`` when the confirmation would go out. The same rule as the status
    and the enqueue, judged as if the draft were ready for review.
    """

    reason = confirmation_not_due_reason(
        ledger.commitment,
        internal_order_mails=ledger.internal_order_mails,
        drop_state=ledger.drop_state,
        action_status=ledger.action_status,
        now=now,
        status=CommitmentStatus.REVIEW_READY,
    )
    return BuyerMailReason(reason.value) if reason is not None else None


def buyer_mail_status(
    kind: OrderMailKind, ledger: BuyerMailLedger, *, now: datetime
) -> BuyerMailStatus:
    """The state of one mail kind: its newest job decides.

    ``can_resend`` follows one rule in every state: the mail is due now and
    no job of it waits. So a mail that was never queued, or whose newest job
    ended without a mail, is no dead end.
    """

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
    due = not_due is None
    latest = last_sequence(kind, ledger)
    if latest is None:
        if kind is OrderMailKind.DELIVERY_DAY and _missed_without_job(ledger, not_due):
            # Due through its window and never queued (worker down, sweep
            # failing): the buyer got nothing, and the order says so.
            return BuyerMailStatus(
                kind, BuyerMailState.FAILED, reason=BuyerMailReason.WINDOW_OVER
            )
        return BuyerMailStatus(
            kind,
            BuyerMailState.NOT_DUE,
            # No job yet. A mail that is due can be sent by a manager at
            # once; a delivery-day mail is otherwise queued by the next
            # sweep, which then finds the manager's job and adds none.
            reason=not_due or BuyerMailReason.NOT_REQUESTED,
            can_resend=due,
        )
    if latest in sent:
        return BuyerMailStatus(
            kind, BuyerMailState.SENT, sent_at=sent_at, can_resend=due
        )
    job = jobs[latest]
    if job.status in {"pending", "processing"}:
        return BuyerMailStatus(kind, BuyerMailState.QUEUED, sent_at=sent_at)
    if job.status == "dead_letter":
        return BuyerMailStatus(
            kind,
            BuyerMailState.FAILED,
            sent_at=sent_at,
            reason=_failure_reason(job.error_code),
            can_resend=due,
        )
    if not_due in _LATE[kind]:
        # Completed without a ledger row and late: the buyer got nothing.
        return BuyerMailStatus(
            kind, BuyerMailState.FAILED, sent_at=sent_at, reason=not_due
        )
    if kind is OrderMailKind.DELIVERY_DAY and due:
        # Completed without a ledger row although the mail is due: the
        # worker completes a delivery-day job over the mailbox limit instead
        # of dead-lettering it. (A switch or a tick that was taken back
        # after the job ran ends here too; "send it" is right then as well.)
        return BuyerMailStatus(
            kind,
            BuyerMailState.FAILED,
            sent_at=sent_at,
            reason=BuyerMailReason.RECIPIENT_LIMIT,
            can_resend=True,
        )
    # Completed without a ledger row: the worker found nothing to send.
    return BuyerMailStatus(
        kind,
        BuyerMailState.SKIPPED,
        sent_at=sent_at,
        reason=not_due or BuyerMailReason.NOT_SENT,
        can_resend=due,
    )


def next_sequence(kind: OrderMailKind, ledger: BuyerMailLedger) -> int:
    """The number of the job a manager's send writes: 0 is the first key
    (the mail was never queued), n the n-th resend."""

    latest = last_sequence(kind, ledger)
    return 0 if latest is None else latest + 1


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
    """Why the mail cannot be sent now; ``None`` when it can."""

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
    return Conflict(
        "buyer_mail_not_due",
        "Diese E-Mail kann jetzt nicht gesendet werden: Die Bestellung ist "
        "ein Entwurf, storniert oder schon geliefert, hat keine "
        "E-Mail-Adresse, ihr Lieferfenster ist vorbei, die Aktion ist "
        "abgeschlossen oder die E-Mails der Aktion sind ausgeschaltet. Die "
        "Liefertags-E-Mail geht nur am Liefertag ab der Versandzeit hinaus.",
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
    ) -> tuple[BuyerMailLedger, bool]:
        """Queue the next job of the mail, or replay the stored command.

        Returns the order's ledger afterwards and whether the command was a
        replay (no new job).
        """
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
        return (await self.overview(actor, action_id, commitment_id)).statuses

    async def overview(
        self, actor: IdentityPrincipal, action_id: UUID, commitment_id: UUID
    ) -> BuyerMailOverview:
        require_action_manager(actor, action_id)
        ledger = await self._repository.ledger(
            action_id=action_id, commitment_id=commitment_id
        )
        now = self._clock()
        return BuyerMailOverview(
            statuses=buyer_mail_statuses(ledger, now=now),
            draft=ledger.commitment.status is CommitmentStatus.DRAFT,
            confirmation_on_completion=confirmation_on_completion(ledger, now=now),
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
    ) -> tuple[BuyerMailStatus, bool]:
        """Send the mail (again); the status afterwards and whether the
        command was a replay that wrote no new job."""

        require_action_manager(actor, action_id)
        if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise DomainInvariantError(
                "commitment_idempotency_key_invalid",
                "Die Vorgangs-ID besitzt ein ungültiges Format.",
            )
        # Resolved before the transaction holds a connection.
        links = await self._mail_links.for_action(action_id)
        moment = occurred_at or self._clock()
        ledger, replayed = await self._repository.resend(
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
        return buyer_mail_status(kind, ledger, now=moment), replayed
