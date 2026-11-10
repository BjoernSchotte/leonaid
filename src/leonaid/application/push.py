"""Push notifications of the PWA (specs/mails-documents-donations-push §10).

Behind the feature flag ``pwa.push``: switched off, every call answers 404
and the worker sends nothing. A member registers the push subscription of a
device, switches kinds on and can send a test push to that device. The
worker job ``push.notification.v1`` sends one push per member and kind, at
most one in 15 minutes; a daily job announces due follow-ups (ADR-0017).

Push is a hint. A job never fails because a device or a push service is out
of reach: it tries again a few times with its own later jobs, then records
the failure on the device and ends.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from leonaid.application.errors import Conflict, RateLimited, ResourceNotFound
from leonaid.application.feature_flags import FeatureFlagService
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.feature_flags import FeatureFlagKey, FeatureFlagSurface
from leonaid.domain.identity import ActionRole, IdentityPrincipal
from leonaid.domain.outbox import ClaimedOutboxEvent
from leonaid.domain.push import (
    MAX_DEVICES_PER_MEMBER,
    PUSH_EVENT_TYPE,
    PUSH_RETRY_DELAYS,
    TEST_KIND,
    PushEndpointPolicy,
    PushKind,
    PushMessage,
    PushOutcome,
    PushResult,
    PushSubscription,
    PushTarget,
    follow_up_push_due,
    require_push_keys,
)

# Per member, whatever browser, address or session the request comes from.
TEST_PUSH_LIMIT = 5
TEST_PUSH_WINDOW = timedelta(minutes=10)
SUBSCRIBE_LIMIT = 30
SUBSCRIBE_WINDOW = timedelta(hours=1)
# All devices of a member are sent to at once; what has not answered after
# this time counts as not reached. Mail and document jobs wait behind a push
# job for no longer than this.
PUSH_JOB_SECONDS = 15.0


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
        vapid_public_key: str,
        device_limit: int,
        request_id: str,
        occurred_at: datetime,
    ) -> UUID | None:
        """The device's id, or None when the member has ``device_limit``
        other devices already."""
        ...

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


class PushRateLimiter(Protocol):
    async def allow(
        self,
        *,
        scope: str,
        user_id: UUID,
        limit: int,
        window: timedelta,
        now: datetime,
    ) -> bool:
        """Count one attempt of the member; False when the limit is used up."""
        ...


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

    async def drop_pending(self, *, user_id: UUID, kind: PushKind) -> None:
        """Forget what was held back for a kind that is not sent any more."""
        ...

    async def kind_enabled(self, *, user_id: UUID, kind: PushKind) -> bool: ...

    async def subscriptions(
        self,
        *,
        user_id: UUID,
        now: datetime,
        vapid_public_key: str,
        except_event_id: UUID,
        device_ids: Sequence[UUID] | None = None,
    ) -> tuple[PushSubscription, ...]:
        """The member's devices whose session is valid, that subscribed with
        the installation's current key and did not get this job's message."""
        ...

    async def record_delivered(
        self, *, subscription_id: UUID, event_id: UUID, now: datetime
    ) -> None: ...

    async def record_failure(self, *, subscription_id: UUID, now: datetime) -> bool:
        """Count one message the push service did not take for the device.
        True: the device failed too often, on too many days, and was removed."""
        ...

    async def delete_device(self, *, subscription_id: UUID) -> None: ...

    async def enqueue_retry(
        self,
        *,
        source_event_id: UUID,
        user_id: UUID,
        kind: str,
        count: int,
        device_ids: Sequence[UUID],
        attempt: int,
        available_at: datetime,
        now: datetime,
    ) -> None: ...

    async def enqueue_due_follow_ups(self, *, now: datetime) -> int: ...

    async def purge_ended(self, *, now: datetime, vapid_public_key: str | None) -> int:
        """Delete devices whose session ended or, with a key given, that
        subscribed with another VAPID key."""
        ...


class PushTransport(Protocol):
    async def send(
        self,
        target: PushTarget,
        payload: bytes,
        *,
        topic: str,
        now: datetime,
    ) -> PushResult: ...


class PushObserver(Protocol):
    def __call__(
        self,
        *,
        kind: str,
        host: str,
        status: int | None,
        outcome: str,
        attempt: int,
        device_removed: bool,
    ) -> None:
        """One message that did not reach a device. Host and status only:
        the path of an endpoint is the device's token."""
        ...


def available_kinds(
    actor: IdentityPrincipal, *, tasks_enabled: bool
) -> tuple[PushKind, ...]:
    """The kinds that can ever reach this member.

    Follow-ups belong to acquirers and deliveries to drivers. "Neues" lists
    public orders for the acquirers of the buyer, or for the action's
    admins when nobody is assigned. Tasks need the tasks module.
    """

    roles = {membership.role for membership in actor.action_memberships}
    kinds: list[PushKind] = []
    if ActionRole.ACQUIRER in roles:
        kinds.append(PushKind.FOLLOW_UPS)
    if roles & {ActionRole.ACQUIRER, ActionRole.CHARITY_ADMIN}:
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
        limiter: PushRateLimiter,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._flags = flags
        self._public_key = public_key
        self._endpoints = endpoints
        self._tasks_enabled = tasks_enabled
        self._limiter = limiter
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def _enabled(self, actor: IdentityPrincipal) -> None:
        await self._flags.require_enabled(
            actor, FeatureFlagKey.PWA_PUSH, surface=FeatureFlagSurface.PWA
        )

    def _configured_key(self) -> str:
        if self._public_key is None:
            raise Conflict(
                "push_not_configured",
                "Benachrichtigungen sind für diese Installation nicht eingerichtet.",
            )
        return self._public_key

    async def _limit(
        self, actor: IdentityPrincipal, scope: str, limit: int, window: timedelta
    ) -> None:
        if not await self._limiter.allow(
            scope=scope,
            user_id=actor.account.id,
            limit=limit,
            window=window,
            now=self._clock(),
        ):
            raise RateLimited(
                "push_rate_limited",
                "Das waren zu viele Versuche in kurzer Zeit. Bitte später erneut.",
            )

    async def _configuration(self, actor: IdentityPrincipal) -> PushConfiguration:
        stored = await self._repository.preferences(actor.account.id)
        return PushConfiguration(
            configured=self._public_key is not None,
            public_key=self._public_key,
            kinds=tuple(
                (kind, stored.get(kind, False))
                for kind in available_kinds(actor, tasks_enabled=self._tasks_enabled)
            ),
        )

    async def configuration(self, actor: IdentityPrincipal) -> PushConfiguration:
        await self._enabled(actor)
        return await self._configuration(actor)

    async def subscribe(
        self,
        actor: IdentityPrincipal,
        *,
        session_id: UUID,
        endpoint: str,
        p256dh: str,
        auth: str,
        application_server_key: str,
        request_id: str,
    ) -> UUID:
        await self._enabled(actor)
        public_key = self._configured_key()
        await self._limit(actor, "push.subscribe", SUBSCRIBE_LIMIT, SUBSCRIBE_WINDOW)
        if application_server_key != public_key:
            # The browser subscribed with an earlier key of the installation:
            # no push signed with the current key can reach it.
            raise Conflict(
                "push_key_replaced",
                "Dieses Gerät muss Benachrichtigungen neu einschalten.",
            )
        try:
            self._endpoints.require(endpoint)
            point, secret = require_push_keys(p256dh, auth)
        except DomainInvariantError as error:
            raise Conflict(error.code, error.message) from error
        subscription_id = await self._repository.save_subscription(
            user_id=actor.account.id,
            session_id=session_id,
            target=PushTarget(endpoint=endpoint, p256dh=point, auth=secret),
            vapid_public_key=public_key,
            device_limit=MAX_DEVICES_PER_MEMBER,
            request_id=request_id,
            occurred_at=self._clock(),
        )
        if subscription_id is None:
            raise Conflict(
                "push_device_limit",
                f"Es sind schon {MAX_DEVICES_PER_MEMBER} Geräte angemeldet. "
                "Bitte zuerst auf einem anderen Gerät ausschalten.",
            )
        return subscription_id

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
        # Switching off is always possible, also while the flag is off;
        # switching on needs the flag and a kind that can reach the member.
        if any(values.values()):
            await self._enabled(actor)
        available = available_kinds(actor, tasks_enabled=self._tasks_enabled)
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
        return await self._configuration(actor)

    async def send_test(self, actor: IdentityPrincipal, subscription_id: UUID) -> None:
        await self._enabled(actor)
        self._configured_key()
        # Each test is a request to a browser vendor signed with the
        # installation's key: counted per member.
        await self._limit(actor, "push.test", TEST_PUSH_LIMIT, TEST_PUSH_WINDOW)
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


@dataclass(frozen=True, slots=True)
class _Job:
    user_id: UUID
    kind: str
    count: int
    # 0: the first try of a message; n: its n-th later try.
    attempt: int
    # The devices of a test push or of a later try; None: all devices.
    device_ids: tuple[UUID, ...] | None


class PushNotificationHandler:
    """Worker job ``push.notification.v1``: one push per member and kind.

    Payload: ``userId``, ``kind``, ``count`` (0: send what was held back);
    a test push names its device in ``subscriptionId``; a later try of a
    message carries ``attempt`` and ``deviceIds``. Without a transport (no
    VAPID key) and while the flag is off the job ends without sending.

    The job sends to all devices at once and ends within
    ``PUSH_JOB_SECONDS``. It never fails because a device was not reached:
    such devices get the message again from a later job (``PUSH_RETRY_
    DELAYS``), and after the last try the failure is counted on the device.
    Run again by the outbox, the job skips the devices it reached before.
    """

    def __init__(
        self,
        repository: PushDispatchRepository,
        transport: PushTransport | None,
        flags: FeatureFlagService,
        *,
        vapid_public_key: str | None,
        observer: PushObserver | None = None,
        clock: Callable[[], datetime] | None = None,
        job_seconds: float = PUSH_JOB_SECONDS,
    ) -> None:
        self._repository = repository
        self._transport = transport
        self._flags = flags
        self._vapid_public_key = vapid_public_key
        self._observer = observer
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._job_seconds = job_seconds

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        if event.event_type != PUSH_EVENT_TYPE:
            raise ValueError(f"Unexpected push event type: {event.event_type}")
        job = self._job(event)
        transport = self._transport
        if (
            transport is None
            or self._vapid_public_key is None
            or not await self._flags.installation_enabled(FeatureFlagKey.PWA_PUSH)
        ):
            # Nothing is sent now, and nothing held back is sent later.
            if job.kind != TEST_KIND:
                await self._repository.drop_pending(
                    user_id=job.user_id, kind=PushKind(job.kind)
                )
            return
        now = self._clock()
        count = await self._count(job, event.id, now)
        if count is None:
            return
        message = PushMessage(job.kind, count)
        devices = await self._repository.subscriptions(
            user_id=job.user_id,
            now=now,
            vapid_public_key=self._vapid_public_key,
            except_event_id=event.id,
            device_ids=job.device_ids,
        )
        results = await self._send_all(transport, devices, message, event.id, now)
        unreached = [
            (device, result)
            for device, result in results
            if result.outcome is PushOutcome.UNAVAILABLE
        ]
        last_try = job.attempt >= len(PUSH_RETRY_DELAYS)
        for device, result in results:
            if result.outcome is PushOutcome.GONE:
                await self._repository.delete_device(subscription_id=device.id)
            elif result.outcome is PushOutcome.REJECTED or (
                result.outcome is PushOutcome.UNAVAILABLE and last_try
            ):
                # Counted on the device only when the push service refused
                # the message: an outage on our side or at the service (no
                # answer, 429, 5xx) must not remove anybody's device.
                removed = result.blames_device and (
                    await self._repository.record_failure(
                        subscription_id=device.id, now=now
                    )
                )
                self._observe(message.kind, result, job.attempt, removed)
            elif result.outcome is PushOutcome.UNAVAILABLE:
                self._observe(message.kind, result, job.attempt, False)
        if unreached and not last_try:
            await self._repository.enqueue_retry(
                source_event_id=event.id,
                user_id=job.user_id,
                kind=job.kind,
                count=count,
                device_ids=[device.id for device, _ in unreached],
                attempt=job.attempt + 1,
                available_at=now + PUSH_RETRY_DELAYS[job.attempt],
                now=now,
            )

    async def _count(self, job: _Job, event_id: UUID, now: datetime) -> int | None:
        """The count this job pushes, or None when it pushes nothing."""

        if job.kind == TEST_KIND:
            return 1
        kind = PushKind(job.kind)
        if job.attempt == 0:
            return await self._repository.claim_dispatch(
                user_id=job.user_id,
                kind=kind,
                event_id=event_id,
                count=job.count,
                now=now,
            )
        # A later try of a message that was claimed before; the member may
        # have switched the kind off meanwhile.
        if not await self._repository.kind_enabled(user_id=job.user_id, kind=kind):
            return None
        return job.count

    async def _send_all(
        self,
        transport: PushTransport,
        devices: Sequence[PushSubscription],
        message: PushMessage,
        event_id: UUID,
        now: datetime,
    ) -> list[tuple[PushSubscription, PushResult]]:
        payload = message.payload()

        async def send(device: PushSubscription) -> PushResult:
            result = await transport.send(
                device.target, payload, topic=message.kind, now=now
            )
            if result.outcome is PushOutcome.DELIVERED:
                # Noted at once, so a second run of this job skips the device.
                await self._repository.record_delivered(
                    subscription_id=device.id, event_id=event_id, now=now
                )
            return result

        if not devices:
            return []
        tasks = [asyncio.create_task(send(device)) for device in devices]
        _, late = await asyncio.wait(tasks, timeout=self._job_seconds)
        for task in late:
            task.cancel()
        await asyncio.gather(*late, return_exceptions=True)
        results: list[tuple[PushSubscription, PushResult]] = []
        for device, task in zip(devices, tasks, strict=True):
            if task.cancelled():
                results.append((device, PushResult(PushOutcome.UNAVAILABLE, host="")))
            else:
                # A database or programming error fails the job; the outbox
                # runs it again and the devices reached so far are skipped.
                results.append((device, task.result()))
        return results

    def _observe(
        self, kind: str, result: PushResult, attempt: int, removed: bool
    ) -> None:
        if self._observer is not None:
            self._observer(
                kind=kind,
                host=result.host,
                status=result.status,
                outcome=result.outcome.value,
                attempt=attempt,
                device_removed=removed,
            )

    @staticmethod
    def _job(event: ClaimedOutboxEvent) -> _Job:
        payload = event.payload
        kind = payload.get("kind")
        count = payload.get("count")
        attempt = payload.get("attempt", 0)
        if (
            not isinstance(kind, str)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            or isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or attempt < 0
        ):
            raise ValueError("Push payload needs a kind, a count and an attempt.")
        if kind != TEST_KIND:
            PushKind(kind)
        user_id = PushNotificationHandler._uuid(payload.get("userId"), "userId")
        device_ids: tuple[UUID, ...] | None = None
        raw_devices = payload.get("deviceIds")
        if raw_devices is not None:
            if not isinstance(raw_devices, list):
                raise ValueError("Push payload field deviceIds must be a list.")
            device_ids = tuple(
                PushNotificationHandler._uuid(item, "deviceIds") for item in raw_devices
            )
        elif kind == TEST_KIND:
            device_ids = (
                PushNotificationHandler._uuid(
                    payload.get("subscriptionId"), "subscriptionId"
                ),
            )
        elif attempt > 0:
            raise ValueError("A later try of a push names its devices.")
        return _Job(user_id, kind, count, attempt, device_ids)

    @staticmethod
    def _uuid(value: object, key: str) -> UUID:
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
        vapid_public_key: str | None,
    ) -> None:
        self._repository = repository
        self._flags = flags
        self._vapid_public_key = vapid_public_key

    async def run_once(self, *, now: datetime) -> int:
        # Devices whose session ended, and devices of a replaced VAPID key,
        # are removed whatever the switches say.
        await self._repository.purge_ended(
            now=now, vapid_public_key=self._vapid_public_key
        )
        if (
            self._vapid_public_key is None
            or not follow_up_push_due(now)
            or not await self._flags.installation_enabled(FeatureFlagKey.PWA_PUSH)
        ):
            return 0
        return await self._repository.enqueue_due_follow_ups(now=now)
