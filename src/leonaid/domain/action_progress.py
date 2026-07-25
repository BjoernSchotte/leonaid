"""Action-progress command values."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid5

from leonaid.domain.outbox import PendingOutboxEvent

EVENT_NAMESPACE = UUID("fbd7675e-5dca-43cb-8a76-6f01da78a309")
AUDIT_NAMESPACE = UUID("555e8f8e-8b0c-4c55-839c-bf8c4bf8e7d4")


@dataclass(frozen=True, slots=True)
class RecordActionProgressCommand:
    command_id: UUID
    action_id: UUID
    actor_user_id: UUID
    actual_value: Decimal
    request_id: str

    def __post_init__(self) -> None:
        if self.actual_value < 0:
            raise ValueError("Der Ist-Wert darf nicht negativ sein.")
        exponent = self.actual_value.as_tuple().exponent
        if not isinstance(exponent, int) or exponent < -4:
            raise ValueError("Der Ist-Wert darf höchstens vier Nachkommastellen haben.")
        if not self.request_id.strip():
            raise ValueError("request_id darf nicht leer sein.")

    @property
    def idempotency_key(self) -> str:
        return f"action-progress:{self.action_id}:{self.command_id}"

    @property
    def request_hash(self) -> str:
        canonical = json.dumps(
            {
                "actionId": str(self.action_id),
                "actorUserId": str(self.actor_user_id),
                "actualValue": str(self.actual_value),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @property
    def audit_event_id(self) -> UUID:
        return uuid5(AUDIT_NAMESPACE, self.idempotency_key)

    def outbox_event(self) -> PendingOutboxEvent:
        return PendingOutboxEvent(
            id=uuid5(EVENT_NAMESPACE, self.idempotency_key),
            aggregate_type="charity_action",
            aggregate_id=self.action_id,
            event_type="charity_action.progress.recorded.v1",
            idempotency_key=self.idempotency_key,
            payload={
                "actionId": str(self.action_id),
                "actorUserId": str(self.actor_user_id),
                "actualValue": str(self.actual_value),
                "requestId": self.request_id,
            },
        )


@dataclass(frozen=True, slots=True)
class ActionProgressResult:
    action_id: UUID
    actual_value: Decimal
    outbox_event_id: UUID
    replayed: bool
