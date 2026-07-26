"""Recipient-scoped activity feed for public orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal, Mapping, Protocol
from uuid import UUID

from leonaid.application.policies import concealed_resource
from leonaid.domain.identity import ActionRole, IdentityPrincipal


class ActivityFeedStatus(StrEnum):
    ALL = "all"
    UNREAD = "unread"


@dataclass(frozen=True, slots=True)
class StoredActivityFeedItem:
    id: UUID
    action_id: UUID
    action_name: str
    event_type: str
    party_kind: Literal["company", "person"]
    party_id: UUID
    payload: Mapping[str, object]
    assignment_id: UUID | None
    occurred_at: datetime
    read_at: datetime | None


@dataclass(frozen=True, slots=True)
class ActivityFeedItem:
    id: UUID
    action_id: UUID
    action_name: str
    event_type: str
    party_kind: Literal["company", "person"]
    party_id: UUID
    party_display_name: str
    commitment_id: UUID
    public_reference: str
    total_minor: int
    currency: str
    total_boxes: int
    total_pieces: int
    next_action_label: str
    next_action_href: str
    occurred_at: datetime
    read_at: datetime | None

    @property
    def is_read(self) -> bool:
        return self.read_at is not None


@dataclass(frozen=True, slots=True)
class ActivityFeedPage:
    items: tuple[ActivityFeedItem, ...]
    total: int
    unread_count: int
    offset: int
    limit: int


class ActivityFeedRepository(Protocol):
    async def list_for_recipient(
        self,
        *,
        recipient_user_id: UUID,
        status: ActivityFeedStatus,
        offset: int,
        limit: int,
        evaluated_at: datetime,
    ) -> tuple[tuple[StoredActivityFeedItem, ...], int, int]: ...

    async def set_read_state(
        self,
        *,
        event_id: UUID,
        recipient_user_id: UUID,
        read_at: datetime | None,
        evaluated_at: datetime,
    ) -> StoredActivityFeedItem | None: ...


class ActivityFeedService:
    def __init__(self, repository: ActivityFeedRepository) -> None:
        self._repository = repository

    async def list(
        self,
        actor: IdentityPrincipal,
        *,
        status: ActivityFeedStatus,
        offset: int,
        limit: int,
    ) -> ActivityFeedPage:
        if not 0 <= offset:
            raise ValueError("Der Offset darf nicht negativ sein.")
        if not 1 <= limit <= 100:
            raise ValueError("Das Aktivitätslimit muss zwischen 1 und 100 liegen.")
        evaluated_at = datetime.now(timezone.utc)
        stored, total, unread_count = await self._repository.list_for_recipient(
            recipient_user_id=actor.account.id,
            status=status,
            offset=offset,
            limit=limit,
            evaluated_at=evaluated_at,
        )
        return ActivityFeedPage(
            items=tuple(self._present(actor, item) for item in stored),
            total=total,
            unread_count=unread_count,
            offset=offset,
            limit=limit,
        )

    async def set_read_state(
        self,
        actor: IdentityPrincipal,
        event_id: UUID,
        *,
        read: bool,
    ) -> ActivityFeedItem:
        evaluated_at = datetime.now(timezone.utc)
        stored = await self._repository.set_read_state(
            event_id=event_id,
            recipient_user_id=actor.account.id,
            read_at=evaluated_at if read else None,
            evaluated_at=evaluated_at,
        )
        if stored is None:
            raise concealed_resource()
        return self._present(actor, stored)

    @staticmethod
    def _present(
        actor: IdentityPrincipal,
        stored: StoredActivityFeedItem,
    ) -> ActivityFeedItem:
        roles = actor.roles_for(stored.action_id)
        if not roles.intersection({ActionRole.ACQUIRER, ActionRole.CHARITY_ADMIN}):
            raise concealed_resource()
        payload = stored.payload
        commitment_id = ActivityFeedService._payload_uuid(payload, "commitmentId")
        if ActionRole.ACQUIRER in roles and stored.assignment_id is not None:
            next_action_label = "Kontakt und Bestellung abstimmen"
            next_action_href = (
                f"/app/activities?view=contacts&assignment={stored.assignment_id}"
            )
        else:
            next_action_label = "Bestellung prüfen und zuordnen"
            next_action_href = f"/admin/orders?commitment={commitment_id}"
        return ActivityFeedItem(
            id=stored.id,
            action_id=stored.action_id,
            action_name=stored.action_name,
            event_type=stored.event_type,
            party_kind=stored.party_kind,
            party_id=stored.party_id,
            party_display_name=ActivityFeedService._payload_string(
                payload,
                "buyerDisplayName",
            ),
            commitment_id=commitment_id,
            public_reference=ActivityFeedService._payload_string(
                payload,
                "publicReference",
            ),
            total_minor=ActivityFeedService._payload_non_negative_int(
                payload,
                "totalMinor",
            ),
            currency=ActivityFeedService._payload_string(payload, "currency"),
            total_boxes=ActivityFeedService._payload_non_negative_int(
                payload,
                "totalBoxes",
            ),
            total_pieces=ActivityFeedService._payload_non_negative_int(
                payload,
                "totalPieces",
            ),
            next_action_label=next_action_label,
            next_action_href=next_action_href,
            occurred_at=stored.occurred_at,
            read_at=stored.read_at,
        )

    @staticmethod
    def _payload_string(payload: Mapping[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"ActivityEvent enthält kein gültiges Feld {key}.")
        return value

    @staticmethod
    def _payload_uuid(payload: Mapping[str, object], key: str) -> UUID:
        try:
            return UUID(ActivityFeedService._payload_string(payload, key))
        except ValueError as error:
            raise RuntimeError(
                f"ActivityEvent enthält keine gültige UUID in {key}."
            ) from error

    @staticmethod
    def _payload_non_negative_int(
        payload: Mapping[str, object],
        key: str,
    ) -> int:
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError(f"ActivityEvent enthält keinen gültigen Wert {key}.")
        return value
