"""Push notifications of the PWA (specs/mails-documents-donations-push §10).

Behind the feature flag ``pwa.push``: switched off, every call answers 404
and the worker sends nothing. A member registers the push subscription of a
device, switches kinds on and can send a test push to that device. The
worker job ``push.notification.v1`` sends one push per member and kind, at
most one in 15 minutes; a daily job announces due follow-ups (ADR-0017).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.feature_flags import FeatureFlagService
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.feature_flags import FeatureFlagKey, FeatureFlagSurface
from leonaid.domain.identity import ActionRole, IdentityPrincipal
from leonaid.domain.outbox import ClaimedOutboxEvent
from leonaid.domain.push import (
    PUSH_EVENT_TYPE,
    TEST_KIND,
    PushEndpointPolicy,
    PushKind,
    PushMessage,
    PushOutcome,
    PushSubscription,
    PushTarget,
    follow_up_push_due,
    require_push_keys,
)

MAX_USER_AGENT_LENGTH = 320


@dataclass(frozen=True, slots=True)
class PushConfiguration:
    # False: the operator has set no VAPID key; nothing can be switched on.
    configured: bool
    # The application server key for ``PushManager.subscribe`` (base64url).
    public_key: str | None
    # The kinds this member can use, and whether each is switched on.
    kinds: tuple[tuple[PushKind, bool], ...]


class PushRepository(Protocol):
    async def preferences(self, user_id: UUID) -> Mapping[PushKind, bool]: ...

    async def set_preferences(
        self,
        *,
        user_id: UUID,
        values: Mapping[PushKind, bool],
        request_id: str,
        occurred_at: datetime,
    ) -> None: ...

    async def save_subscription(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        target: PushTarget,
        user_agent: str,
        request_id: str,
        occurred_at: datetime,
    ) -> UUID: ...

    async def delete_subscription(
        self,
        *,
        user_id: UUID,
        subscription_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> bool: ...

    async def enqueue_test(
        self, *, user_id: UUID, subscription_id: UUID, occurred_at: datetime
    ) -> bool: ...


class PushDispatchRepository(Protocol):
    async def claim_dispatch(
        self,
        *,
        user_id: UUID,
        kind: PushKind,
        event_id: UUID,
        count: int,
        now: datetime,
    ) -> int | None:
        """The count to push now, or None when nothing is sent by this job."""
        ...

    async def subscriptions(
        self,
        *,
        user_id: UUID,
        now: datetime,
        subscription_id: UUID | None = None,
    ) -> tuple[PushSubscription, ...]:
        """The member's devices whose session is still valid."""
        ...

    async def record_outcome(
        self, *, subscription_id: UUID, outcome: PushOutcome, now: datetime
    ) -> None: ...

    async def enqueue_due_follow_ups(self, *, now: datetime) -> int: ...

    async def purge_ended(self, *, now: datetime) -> int: ...


class PushTransport(Protocol):
    async def send(
        self,
        target: PushTarget,
        payload: bytes,
        *,
        topic: str,
        now: datetime,
    ) -> PushOutcome: ...


def available_kinds(
    actor: IdentityPrincipal, *, tasks_enabled: bool
) -> tuple[PushKind, ...]:
    """The kinds that can ever reach this member.

    Follow-ups belong to acquirers, deliveries to drivers, "Neues" to every
    member of an action; tasks need the tasks module.
    """

    roles = {membership.role for membership in actor.action_memberships}
    kinds: list[PushKind] = []
    if ActionRole.ACQUIRER in roles:
        kinds.append(PushKind.FOLLOW_UPS)
    if roles:
        kinds.append(PushKind.FEED)
    if tasks_enabled:
        kinds.append(PushKind.TASKS)
    if ActionRole.DRIVER in roles:
        kinds.append(PushKind.DELIVERY)
    return tuple(kinds)


class PushService:
    def __init__(
        self,
        repository: PushRepository,
        flags: FeatureFlagService,
        *,
        public_key: str | None,
        endpoints: PushEndpointPolicy,
        tasks_enabled: bool,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._flags = flags
        self._public_key = public_key
        self._endpoints = endpoints
        self._tasks_enabled = tasks_enabled
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def _enabled(self, actor: IdentityPrincipal) -> None:
        await self._flags.require_enabled(
            actor, FeatureFlagKey.PWA_PUSH, surface=FeatureFlagSurface.PWA
        )

    def _require_configured(self) -> None:
        if self._public_key is None:
            raise Conflict(
                "push_not_configured",
                "Benachrichtigungen sind für diese Installation nicht eingerichtet.",
            )

    async def configuration(self, actor: IdentityPrincipal) -> PushConfiguration:
        await self._enabled(actor)
        stored = await self._repository.preferences(actor.account.id)
        return PushConfiguration(
            configured=self._public_key is not None,
            public_key=self._public_key,
            kinds=tuple(
                (kind, stored.get(kind, False))
                for kind in available_kinds(actor, tasks_enabled=self._tasks_enabled)
            ),
        )

    async def subscribe(
        self,
        actor: IdentityPrincipal,
        *,
        session_id: UUID,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str,
        request_id: str,
    ) -> UUID:
        await self._enabled(actor)
        self._require_configured()
        try:
            self._endpoints.require(endpoint)
            point, secret = require_push_keys(p256dh, auth)
        except DomainInvariantError as error:
            raise Conflict(error.code, error.message) from error
        return await self._repository.save_subscription(
            user_id=actor.account.id,
            session_id=session_id,
            target=PushTarget(endpoint=endpoint, p256dh=point, auth=secret),
            user_agent=" ".join(user_agent.split())[:MAX_USER_AGENT_LENGTH],
            request_id=request_id,
            occurred_at=self._clock(),
        )

    async def unsubscribe(
        self,
        actor: IdentityPrincipal,
        subscription_id: UUID,
        *,
        request_id: str,
    ) -> None:
        """Remove a device. Also works while the flag is off: taking back
        a consent must never depend on a switch."""

        deleted = await self._repository.delete_subscription(
            user_id=actor.account.id,
            subscription_id=subscription_id,
            request_id=request_id,
            occurred_at=self._clock(),
        )
        if not deleted:
            raise ResourceNotFound(
                "push_subscription_not_found",
                "Dieses Gerät ist nicht für Benachrichtigungen angemeldet.",
            )

    async def set_preferences(
        self,
        actor: IdentityPrincipal,
        values: Mapping[PushKind, bool],
        *,
        request_id: str,
    ) -> PushConfiguration:
        await self._enabled(actor)
        available = available_kinds(actor, tasks_enabled=self._tasks_enabled)
        # Switching off is always possible; switching on needs the kind.
        refused = [
            kind
            for kind, enabled in values.items()
            if enabled and kind not in available
        ]
        if refused:
            raise Conflict(
                "push_kind_unavailable",
                "Diese Benachrichtigung steht für dieses Konto nicht zur Verfügung.",
            )
        await self._repository.set_preferences(
            user_id=actor.account.id,
            values=values,
            request_id=request_id,
            occurred_at=self._clock(),
        )
        return await self.configuration(actor)

    async def send_test(self, actor: IdentityPrincipal, subscription_id: UUID) -> None:
        await self._enabled(actor)
        self._require_configured()
        queued = await self._repository.enqueue_test(
            user_id=actor.account.id,
            subscription_id=subscription_id,
            occurred_at=self._clock(),
        )
        if not queued:
            raise ResourceNotFound(
                "push_subscription_not_found",
                "Dieses Gerät ist nicht für Benachrichtigungen angemeldet.",
            )


class PushServiceUnavailable(RuntimeError):
    """No device could be reached; the outbox runs the job again."""

    code = "push_service_unavailable"
    retryable = True


class PushNotificationHandler:
    """Worker job ``push.notification.v1``: one push per member and kind.

    Payload: ``userId``, ``kind``, ``count`` (0: send what was held back),
    and for a test push ``subscriptionId``. Without a transport (no VAPID
    key) and while the flag is off the job ends without sending.
    """

    def __init__(
        self,
        repository: PushDispatchRepository,
        transport: PushTransport | None,
        flags: FeatureFlagService,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._transport = transport
        self._flags = flags
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        if event.event_type != PUSH_EVENT_TYPE:
            raise ValueError(f"Unexpected push event type: {event.event_type}")
        user_id = self._uuid(event, "userId")
        kind = event.payload.get("kind")
        count = event.payload.get("count")
        if (
            not isinstance(kind, str)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            raise ValueError("Push payload needs a kind and a count.")
        if self._transport is None or not await self._flags.installation_enabled(
            FeatureFlagKey.PWA_PUSH
        ):
            return
        now = self._clock()
        if kind == TEST_KIND:
            message = PushMessage(TEST_KIND, 1)
            subscriptions = await self._repository.subscriptions(
                user_id=user_id,
                now=now,
                subscription_id=self._uuid(event, "subscriptionId"),
            )
        else:
            send_count = await self._repository.claim_dispatch(
                user_id=user_id,
                kind=PushKind(kind),
                event_id=event.id,
                count=count,
                now=now,
            )
            if send_count is None:
                return
            message = PushMessage(kind, send_count)
            subscriptions = await self._repository.subscriptions(
                user_id=user_id, now=now
            )
        payload = message.payload()
        outcomes: list[PushOutcome] = []
        for subscription in subscriptions:
            outcome = await self._transport.send(
                subscription.target, payload, topic=message.kind, now=now
            )
            await self._repository.record_outcome(
                subscription_id=subscription.id, outcome=outcome, now=now
            )
            outcomes.append(outcome)
        if outcomes and all(outcome is PushOutcome.UNAVAILABLE for outcome in outcomes):
            raise PushServiceUnavailable(
                "No push service could be reached for this message."
            )

    @staticmethod
    def _uuid(event: ClaimedOutboxEvent, key: str) -> UUID:
        value = event.payload.get(key)
        if not isinstance(value, str):
            raise ValueError(f"Push payload field {key} is missing.")
        return UUID(value)


class FollowUpPushJob:
    """The daily follow-up push and the cleanup of ended devices.

    Runs every few minutes. From 08:00 club time it asks for one push per
    member who has follow-ups due or overdue; the job key holds the day, so
    each member is asked once a day however often this runs.
    """

    def __init__(
        self,
        repository: PushDispatchRepository,
        flags: FeatureFlagService,
        *,
        configured: bool,
    ) -> None:
        self._repository = repository
        self._flags = flags
        self._configured = configured

    async def run_once(self, *, now: datetime) -> int:
        # Devices whose session ended are removed whatever the switches say.
        await self._repository.purge_ended(now=now)
        if (
            not self._configured
            or not follow_up_push_due(now)
            or not await self._flags.installation_enabled(FeatureFlagKey.PWA_PUSH)
        ):
            return 0
        return await self._repository.enqueue_due_follow_ups(now=now)
