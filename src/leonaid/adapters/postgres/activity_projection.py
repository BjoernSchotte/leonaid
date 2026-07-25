"""Exactly-once PostgreSQL projection handlers for durable events."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid5

import asyncpg

from leonaid.domain.outbox import ClaimedOutboxEvent

ACTIVITY_NAMESPACE = UUID("9dad66c0-e325-410b-a9c3-1dfaf0f329d3")


class ActionProgressActivityHandler:
    """Project an action-progress event into the member activity feed once."""

    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        action_id = self._required_uuid(event, "actionId")
        if action_id != event.aggregate_id:
            raise ValueError(
                "Payload und Aggregate referenzieren verschiedene Aktionen."
            )
        activity_id = uuid5(ACTIVITY_NAMESPACE, str(event.id))
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                inserted = await connection.fetchval(
                    """
                    INSERT INTO activity_event (
                        id, action_id, event_type, payload,
                        source_outbox_event_id
                    )
                    VALUES (
                        $1, $2, 'charity_action.progress.recorded',
                        $3::jsonb, $4
                    )
                    ON CONFLICT (source_outbox_event_id) DO NOTHING
                    RETURNING true
                    """,
                    activity_id,
                    action_id,
                    self._json_payload(event),
                    event.id,
                )
                if inserted:
                    await connection.execute(
                        """
                        INSERT INTO activity_event_recipient (
                            activity_event_id, user_id
                        )
                        SELECT $1, membership.user_id
                        FROM action_membership AS membership
                        JOIN user_account AS account
                          ON account.id = membership.user_id
                        WHERE membership.action_id = $2
                          AND account.status = 'active'
                          AND (
                              membership.active_until IS NULL
                              OR membership.active_until > CURRENT_TIMESTAMP
                          )
                        ON CONFLICT DO NOTHING
                        """,
                        activity_id,
                        action_id,
                    )

    @staticmethod
    def _required_uuid(event: ClaimedOutboxEvent, key: str) -> UUID:
        value = event.payload.get(key)
        if not isinstance(value, str):
            raise ValueError(f"Payload-Feld {key} fehlt.")
        return UUID(value)

    @staticmethod
    def _json_payload(event: ClaimedOutboxEvent) -> str:
        return json.dumps(event.payload, separators=(",", ":"))
