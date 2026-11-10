"""Push notifications of the PWA (specs/mails-documents-donations-push §10).

Rules that hold without a database or a network: which kinds exist, what a
message may carry, which push endpoints LeonAid ever calls, and how often a
user hears about one kind (ADR-0017).
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID

from leonaid.domain.calendar import INSTALLATION_TIME_ZONE
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import require_aware
from leonaid.platform.base_paths import PWA_BASE

PUSH_EVENT_TYPE: Final = "push.notification.v1"
# At most one push per user and kind in this time; later ones are counted
# and sent together when it has passed.
PUSH_THROTTLE: Final = timedelta(minutes=15)
# Follow-ups are announced once a day from this club time on. A worker that
# was down at 08:00 catches up until the evening, never at night.
FOLLOW_UP_PUSH_FROM: Final = time(8, 0)
FOLLOW_UP_PUSH_UNTIL: Final = time(20, 0)
MAX_ENDPOINT_LENGTH: Final = 2048
MAX_PUSH_COUNT: Final = 9999


class PushKind(StrEnum):
    """What a member can switch on; each kind is off until they do (D-P3)."""

    FOLLOW_UPS = "follow_ups"
    FEED = "feed"
    TASKS = "tasks"
    DELIVERY = "delivery"


# The test push of "Benachrichtigungen": no preference, no throttle.
TEST_KIND: Final = "test"

_TARGET_PATHS: Final = {
    PushKind.FOLLOW_UPS.value: f"{PWA_BASE}activities?view=contacts",
    PushKind.FEED.value: f"{PWA_BASE}activities",
    PushKind.TASKS.value: f"{PWA_BASE}tasks",
    PushKind.DELIVERY.value: f"{PWA_BASE}delivery",
    TEST_KIND: f"{PWA_BASE}notifications",
}


@dataclass(frozen=True, slots=True)
class PushMessage:
    """Everything a push carries: a kind, a count and a target path (D-P2).

    The text is written on the device from these three values. No name,
    address, amount or id of a record passes through the push services.
    """

    kind: str
    count: int

    def __post_init__(self) -> None:
        if self.kind not in _TARGET_PATHS:
            raise DomainInvariantError(
                "push_kind_unknown", "Diese Art von Benachrichtigung gibt es nicht."
            )
        if (
            isinstance(self.count, bool)
            or not isinstance(self.count, int)
            or self.count < 1
        ):
            raise DomainInvariantError(
                "push_count_invalid", "Eine Benachrichtigung zählt mindestens eins."
            )

    @property
    def path(self) -> str:
        return _TARGET_PATHS[self.kind]

    def payload(self) -> bytes:
        return json.dumps(
            {
                "kind": self.kind,
                "count": min(self.count, MAX_PUSH_COUNT),
                "path": self.path,
            },
            separators=(",", ":"),
        ).encode()


# Push services of the browser vendors. Exact hosts, and name suffixes where
# a vendor spreads its service over many hosts (ADR-0017).
PUSH_SERVICE_HOSTS: Final = frozenset(
    {
        # Chrome, Edge on Android, and other Chromium browsers (FCM).
        "fcm.googleapis.com",
        "jmt17.google.com",
        # Firefox.
        "updates.push.services.mozilla.com",
        # Safari and web apps on the iPhone home screen.
        "web.push.apple.com",
    }
)
PUSH_SERVICE_HOST_SUFFIXES: Final = (
    # Edge on Windows (WNS) names a data centre in the host.
    ".notify.windows.com",
)


@dataclass(frozen=True, slots=True)
class PushEndpointPolicy:
    """Decides which URL LeonAid may send a push to.

    A subscription's endpoint comes from the member's browser, so it is
    input: without this check a member could make the worker call any host
    it can reach. ``extra_origins`` are whole origins (scheme, host, port)
    for proofs against a local receiver; production composition passes none.
    """

    extra_origins: frozenset[str] = frozenset()

    def allows(self, endpoint: str) -> bool:
        if not endpoint or len(endpoint) > MAX_ENDPOINT_LENGTH:
            return False
        if any(character.isspace() for character in endpoint):
            return False
        try:
            parts = urlsplit(endpoint)
            port = parts.port
        except ValueError:
            return False
        host = (parts.hostname or "").casefold()
        if (
            not host
            or parts.username is not None
            or parts.password is not None
            or parts.fragment
        ):
            return False
        origin = f"{parts.scheme}://{host}" + (f":{port}" if port is not None else "")
        if origin in self.extra_origins:
            return True
        if parts.scheme != "https" or port not in (None, 443):
            return False
        return host in PUSH_SERVICE_HOSTS or host.endswith(PUSH_SERVICE_HOST_SUFFIXES)

    def require(self, endpoint: str) -> str:
        if not self.allows(endpoint):
            raise DomainInvariantError(
                "push_endpoint_not_allowed",
                "Dieser Benachrichtigungsdienst wird nicht unterstützt.",
            )
        return endpoint


# NIST P-256: y² = x³ − 3x + b over the prime field p.
_P256_P: Final = 2**256 - 2**224 + 2**192 + 2**96 - 1
_P256_B: Final = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B


def _b64url(value: str) -> bytes:
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError) as error:
        raise ValueError("not base64url") from error


def require_push_keys(p256dh: str, auth: str) -> tuple[bytes, bytes]:
    """The subscription's public key and authentication secret (RFC 8291 §3).

    The key is an uncompressed point on P-256, the secret 16 octets.
    """

    try:
        point = _b64url(p256dh)
        secret = _b64url(auth)
        if len(point) != 65 or point[0] != 4 or len(secret) != 16:
            raise ValueError("wrong length")
        x = int.from_bytes(point[1:33], "big")
        y = int.from_bytes(point[33:], "big")
        if x >= _P256_P or y >= _P256_P:
            raise ValueError("coordinate out of range")
        if (y * y - (x * x * x - 3 * x + _P256_B)) % _P256_P != 0:
            raise ValueError("not on the curve")
    except ValueError as error:
        raise DomainInvariantError(
            "push_subscription_keys_invalid",
            "Die Schlüssel dieses Geräts sind ungültig.",
        ) from error
    return point, secret


class PushOutcome(StrEnum):
    DELIVERED = "delivered"
    # The subscription no longer exists (404, 410) or LeonAid must not call
    # its endpoint: the row is deleted.
    GONE = "gone"
    # The push service refused this message; sending it again cannot help.
    REJECTED = "rejected"
    # The push service or the network failed; a later attempt may work.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class PushTarget:
    """Where one push goes and how it is encrypted for that device."""

    endpoint: str
    p256dh: bytes
    auth: bytes


@dataclass(frozen=True, slots=True)
class PushSubscription:
    id: UUID
    user_id: UUID
    target: PushTarget


@dataclass(frozen=True, slots=True)
class DispatchState:
    """What LeonAid remembers per user and kind between two pushes."""

    last_sent_at: datetime | None = None
    pending_count: int = 0
    # The job that sends right now, and the count it sends: its retry sends
    # the same count again instead of counting twice.
    sending_event_id: UUID | None = None
    sending_count: int = 0


@dataclass(frozen=True, slots=True)
class DispatchPlan:
    state: DispatchState
    # The count to push now; None: nothing is sent by this job.
    send_count: int | None = None
    # When a job must send what was held back; None: none is needed.
    flush_at: datetime | None = None


def plan_dispatch(
    state: DispatchState,
    *,
    event_id: UUID,
    count: int,
    now: datetime,
) -> DispatchPlan:
    """Decide what the job ``event_id`` does with ``count`` new events.

    ``count`` 0 is the job that sends what was held back. Within
    ``PUSH_THROTTLE`` of the last push the events are counted and one later
    job sends them together; that job is asked for with the first held-back
    event only.
    """

    require_aware(now, "now")
    if count < 0:
        raise ValueError("count must not be negative")
    if state.sending_event_id == event_id:
        # The outbox runs this job again: send what it claimed before.
        return DispatchPlan(state, send_count=state.sending_count or None)
    due_at = (
        state.last_sent_at + PUSH_THROTTLE if state.last_sent_at is not None else None
    )
    total = state.pending_count + count
    if due_at is not None and now < due_at:
        return DispatchPlan(
            DispatchState(
                last_sent_at=state.last_sent_at,
                pending_count=total,
                sending_event_id=state.sending_event_id,
                sending_count=state.sending_count,
            ),
            flush_at=due_at if state.pending_count == 0 and count > 0 else None,
        )
    if total == 0:
        return DispatchPlan(state)
    return DispatchPlan(
        DispatchState(
            last_sent_at=now,
            pending_count=0,
            sending_event_id=event_id,
            sending_count=total,
        ),
        send_count=total,
    )


def follow_up_push_due(now: datetime) -> bool:
    """Whether the daily follow-up push may go out at ``now`` (club time)."""

    require_aware(now, "now")
    local = now.astimezone(INSTALLATION_TIME_ZONE).time()
    return FOLLOW_UP_PUSH_FROM <= local < FOLLOW_UP_PUSH_UNTIL
