"""PostgreSQL recipient projection for the member activity feed."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from leonaid.application.activity_feed import (
    ActivityFeedStatus,
    StoredActivityFeedItem,
)


def _payload(value: object) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError("ActivityEvent besitzt kein gültiges JSON-Payload.")
    return {str(key): item for key, item in value.items()}


class AsyncpgActivityFeedRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def list_for_recipient(
        self,
        *,
        recipient_user_id: UUID,
        status: ActivityFeedStatus,
        offset: int,
        limit: int,
        evaluated_at: datetime,
    ) -> tuple[tuple[StoredActivityFeedItem, ...], int, int]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                counts = await connection.fetchrow(
                    """
                    SELECT
                        count(*) AS total,
                        count(*) FILTER (
                            WHERE recipient.read_at IS NULL
                        ) AS unread_count
                    FROM activity_event AS event
                    JOIN activity_event_recipient AS recipient
                      ON recipient.activity_event_id = event.id
                    JOIN action_membership AS membership
                      ON membership.action_id = event.action_id
                     AND membership.user_id = recipient.user_id
                     AND membership.role IN ('acquirer', 'charity_admin')
                     AND membership.active_from <= $2
                     AND (
                        membership.active_until IS NULL
                        OR membership.active_until > $2
                     )
                    WHERE recipient.user_id = $1
                      AND event.event_type = 'public_order_received'
                      AND (
                        (event.twenty_company_id IS NOT NULL
                         AND event.twenty_person_id IS NULL)
                        OR
                        (event.twenty_company_id IS NULL
                         AND event.twenty_person_id IS NOT NULL)
                      )
                    """,
                    recipient_user_id,
                    evaluated_at,
                )
                rows = await connection.fetch(
                    """
                    SELECT
                        event.id,
                        event.action_id,
                        action.name AS action_name,
                        event.event_type,
                        event.twenty_company_id,
                        event.twenty_person_id,
                        event.payload,
                        event.occurred_at,
                        recipient.read_at,
                        assignment.id AS assignment_id
                    FROM activity_event AS event
                    JOIN activity_event_recipient AS recipient
                      ON recipient.activity_event_id = event.id
                    JOIN charity_action AS action
                      ON action.id = event.action_id
                    JOIN action_membership AS membership
                      ON membership.action_id = event.action_id
                     AND membership.user_id = recipient.user_id
                     AND membership.role IN ('acquirer', 'charity_admin')
                     AND membership.active_from <= $3
                     AND (
                        membership.active_until IS NULL
                        OR membership.active_until > $3
                     )
                    LEFT JOIN acquisition_assignment AS assignment
                      ON assignment.action_id = event.action_id
                     AND assignment.acquirer_user_id = recipient.user_id
                     AND assignment.status <> 'handed_over'
                     AND assignment.twenty_company_id
                         IS NOT DISTINCT FROM event.twenty_company_id
                     AND assignment.twenty_person_id
                         IS NOT DISTINCT FROM event.twenty_person_id
                    WHERE recipient.user_id = $1
                      AND event.event_type = 'public_order_received'
                      AND (
                        (event.twenty_company_id IS NOT NULL
                         AND event.twenty_person_id IS NULL)
                        OR
                        (event.twenty_company_id IS NULL
                         AND event.twenty_person_id IS NOT NULL)
                      )
                      AND ($2 = 'all' OR recipient.read_at IS NULL)
                    ORDER BY event.occurred_at DESC, event.id DESC
                    OFFSET $4
                    LIMIT $5
                    """,
                    recipient_user_id,
                    status.value,
                    evaluated_at,
                    offset,
                    limit,
                )
        return (
            tuple(self._stored(row) for row in rows),
            int(counts["total"]) if counts is not None else 0,
            int(counts["unread_count"]) if counts is not None else 0,
        )

    async def set_read_state(
        self,
        *,
        event_id: UUID,
        recipient_user_id: UUID,
        read_at: datetime | None,
        evaluated_at: datetime,
    ) -> StoredActivityFeedItem | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                updated = await connection.fetchval(
                    """
                    UPDATE activity_event_recipient AS recipient
                    SET read_at = $3
                    FROM activity_event AS event
                    WHERE recipient.activity_event_id = $1
                      AND recipient.user_id = $2
                      AND event.id = recipient.activity_event_id
                      AND event.event_type = 'public_order_received'
                      AND EXISTS (
                        SELECT 1
                        FROM action_membership AS membership
                        WHERE membership.action_id = event.action_id
                          AND membership.user_id = recipient.user_id
                          AND membership.role IN (
                            'acquirer',
                            'charity_admin'
                          )
                          AND membership.active_from <= $4
                          AND (
                            membership.active_until IS NULL
                            OR membership.active_until > $4
                          )
                      )
                    RETURNING true
                    """,
                    event_id,
                    recipient_user_id,
                    read_at,
                    evaluated_at,
                )
                if not updated:
                    return None
                row = await connection.fetchrow(
                    """
                    SELECT
                        event.id,
                        event.action_id,
                        action.name AS action_name,
                        event.event_type,
                        event.twenty_company_id,
                        event.twenty_person_id,
                        event.payload,
                        event.occurred_at,
                        recipient.read_at,
                        assignment.id AS assignment_id
                    FROM activity_event AS event
                    JOIN activity_event_recipient AS recipient
                      ON recipient.activity_event_id = event.id
                     AND recipient.user_id = $2
                    JOIN charity_action AS action
                      ON action.id = event.action_id
                    LEFT JOIN acquisition_assignment AS assignment
                      ON assignment.action_id = event.action_id
                     AND assignment.acquirer_user_id = recipient.user_id
                     AND assignment.status <> 'handed_over'
                     AND assignment.twenty_company_id
                         IS NOT DISTINCT FROM event.twenty_company_id
                     AND assignment.twenty_person_id
                         IS NOT DISTINCT FROM event.twenty_person_id
                    WHERE event.id = $1
                    """,
                    event_id,
                    recipient_user_id,
                )
        return self._stored(row) if row is not None else None

    @staticmethod
    def _stored(row: asyncpg.Record) -> StoredActivityFeedItem:
        company_id = row["twenty_company_id"]
        person_id = row["twenty_person_id"]
        if (company_id is None) == (person_id is None):
            raise RuntimeError(
                "ActivityEvent muss genau eine Twenty-Partei referenzieren."
            )
        return StoredActivityFeedItem(
            id=row["id"],
            action_id=row["action_id"],
            action_name=str(row["action_name"]),
            event_type=str(row["event_type"]),
            party_kind="company" if company_id is not None else "person",
            party_id=company_id if company_id is not None else person_id,
            payload=_payload(row["payload"]),
            assignment_id=row["assignment_id"],
            occurred_at=row["occurred_at"],
            read_at=row["read_at"],
        )
