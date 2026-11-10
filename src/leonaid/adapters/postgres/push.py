"""PostgreSQL persistence for push notifications (ADR-0017).

``enqueue_push`` is the one way another area asks for a push: it runs in the
caller's transaction and writes a job only for members who switched the kind
on, have a device and while ``pwa.push`` is on. The job carries a member, a
kind and a count, nothing about the record that caused it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.domain.calendar import local_day, local_day_bounds
from leonaid.domain.push import (
    PUSH_EVENT_TYPE,
    TEST_KIND,
    DispatchState,
    PushKind,
    PushOutcome,
    PushSubscription,
    PushTarget,
    plan_dispatch,
)

_FLAG_ON = "EXISTS (SELECT 1 FROM feature_flag WHERE key = 'pwa.push' AND enabled)"
# A device counts while its session is neither revoked nor expired.
_LIVE_DEVICE = """
    EXISTS (
        SELECT 1
        FROM push_subscription AS device
        JOIN user_session AS session ON session.id = device.session_id
        WHERE device.user_id = preference.user_id
          AND session.revoked_at IS NULL
          AND session.expires_at > $1
    )
"""


async def enqueue_push(
    connection: asyncpg.Connection[Any],
    *,
    user_ids: Sequence[UUID],
    kind: PushKind,
    occurred_at: datetime,
    count: int = 1,
    except_user_id: UUID | None = None,
) -> None:
    """Ask for one push per member, in the caller's transaction.

    ``except_user_id`` is the person who caused the event: nobody is told
    about their own action.
    """

    if count < 1:
        raise ValueError("count must be positive")
    recipients = sorted({user for user in user_ids if user != except_user_id})
    if not recipients:
        return
    await connection.execute(
        f"""
        INSERT INTO outbox_event (
            id, aggregate_type, aggregate_id, event_type,
            idempotency_key, payload, available_at, created_at
        )
        SELECT
            job.event_id, 'user_account', preference.user_id, $5,
            'push:' || $2 || ':' || job.event_id::text,
            jsonb_build_object(
                'userId', preference.user_id::text, 'kind', $2::text, 'count', $6::int
            ),
            $1, $1
        FROM unnest($3::uuid[], $4::uuid[]) AS job (user_id, event_id)
        JOIN push_preference AS preference
          ON preference.user_id = job.user_id
         AND preference.kind = $2
         AND preference.enabled
        WHERE {_FLAG_ON}
          AND {_LIVE_DEVICE}
        """,
        occurred_at,
        kind.value,
        recipients,
        [uuid4() for _ in recipients],
        PUSH_EVENT_TYPE,
        count,
    )


async def _audit(
    connection: asyncpg.Connection[Any],
    *,
    user_id: UUID,
    event_type: str,
    entity_type: str,
    entity_id: UUID,
    request_id: str,
    payload: Mapping[str, object],
    occurred_at: datetime,
) -> None:
    await connection.execute(
        """
        INSERT INTO audit_event (
            id, actor_user_id, event_type, entity_type,
            entity_id, request_id, payload, occurred_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
        """,
        uuid4(),
        user_id,
        event_type,
        entity_type,
        entity_id,
        request_id,
        json.dumps(payload, separators=(",", ":")),
        occurred_at,
    )


class AsyncpgPushRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def preferences(self, user_id: UUID) -> Mapping[PushKind, bool]:
        rows = await self._pool.fetch(
            "SELECT kind, enabled FROM push_preference WHERE user_id = $1", user_id
        )
        return {PushKind(row["kind"]): bool(row["enabled"]) for row in rows}

    async def set_preferences(
        self,
        *,
        user_id: UUID,
        values: Mapping[PushKind, bool],
        request_id: str,
        occurred_at: datetime,
    ) -> None:
        if not values:
            return
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                changed: dict[str, bool] = {}
                for kind, enabled in sorted(values.items()):
                    stored = await connection.fetchval(
                        """
                        INSERT INTO push_preference (
                            user_id, kind, enabled, updated_at
                        )
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (user_id, kind) DO UPDATE
                        SET enabled = EXCLUDED.enabled,
                            updated_at = EXCLUDED.updated_at
                        WHERE push_preference.enabled <> EXCLUDED.enabled
                        RETURNING enabled
                        """,
                        user_id,
                        kind.value,
                        enabled,
                        occurred_at,
                    )
                    if stored is not None:
                        changed[kind.value] = enabled
                    if not enabled:
                        # What waited for a kind that is now off is dropped.
                        await connection.execute(
                            "UPDATE push_dispatch SET pending_count = 0 "
                            "WHERE user_id = $1 AND kind = $2",
                            user_id,
                            kind.value,
                        )
                if changed:
                    # The record of the consent and of taking it back.
                    await _audit(
                        connection,
                        user_id=user_id,
                        event_type="push.preferences.changed",
                        entity_type="user_account",
                        entity_id=user_id,
                        request_id=request_id,
                        payload={"kinds": changed},
                        occurred_at=occurred_at,
                    )

    async def save_subscription(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        target: PushTarget,
        user_agent: str,
        request_id: str,
        occurred_at: datetime,
    ) -> UUID:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                # One row per endpoint: a device that signs in again, also
                # as another member, moves its row to the new session.
                row = await connection.fetchrow(
                    """
                    INSERT INTO push_subscription (
                        id, user_id, session_id, endpoint, p256dh, auth,
                        user_agent, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (endpoint) DO UPDATE
                    SET user_id = EXCLUDED.user_id,
                        session_id = EXCLUDED.session_id,
                        p256dh = EXCLUDED.p256dh,
                        auth = EXCLUDED.auth,
                        user_agent = EXCLUDED.user_agent,
                        failure_count = 0
                    RETURNING id, (xmax = 0) AS created
                    """,
                    uuid4(),
                    user_id,
                    session_id,
                    target.endpoint,
                    target.p256dh,
                    target.auth,
                    user_agent,
                    occurred_at,
                )
                assert row is not None
                if row["created"]:
                    await _audit(
                        connection,
                        user_id=user_id,
                        event_type="push.subscription.created",
                        entity_type="push_subscription",
                        entity_id=row["id"],
                        request_id=request_id,
                        payload={},
                        occurred_at=occurred_at,
                    )
                return UUID(str(row["id"]))

    async def delete_subscription(
        self,
        *,
        user_id: UUID,
        subscription_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> bool:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                deleted = await connection.fetchval(
                    "DELETE FROM push_subscription "
                    "WHERE id = $1 AND user_id = $2 RETURNING id",
                    subscription_id,
                    user_id,
                )
                if deleted is None:
                    return False
                await _audit(
                    connection,
                    user_id=user_id,
                    event_type="push.subscription.deleted",
                    entity_type="push_subscription",
                    entity_id=subscription_id,
                    request_id=request_id,
                    payload={"reason": "member"},
                    occurred_at=occurred_at,
                )
                return True

    async def enqueue_test(
        self, *, user_id: UUID, subscription_id: UUID, occurred_at: datetime
    ) -> bool:
        event_id = uuid4()
        status = await self._pool.execute(
            """
            INSERT INTO outbox_event (
                id, aggregate_type, aggregate_id, event_type,
                idempotency_key, payload, available_at, created_at
            )
            SELECT
                $1, 'user_account', device.user_id, $2, $7,
                jsonb_build_object(
                    'userId', device.user_id::text,
                    'kind', $3::text,
                    'count', 1,
                    'subscriptionId', device.id::text
                ),
                $6, $6
            FROM push_subscription AS device
            WHERE device.id = $4 AND device.user_id = $5
            """,
            event_id,
            PUSH_EVENT_TYPE,
            TEST_KIND,
            subscription_id,
            user_id,
            occurred_at,
            f"push:test:{event_id}",
        )
        return str(status).endswith(" 1")

    async def claim_dispatch(
        self,
        *,
        user_id: UUID,
        kind: PushKind,
        event_id: UUID,
        count: int,
        now: datetime,
    ) -> int | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                wanted = await connection.fetchval(
                    """
                    SELECT preference.enabled
                    FROM push_preference AS preference
                    JOIN user_account AS account
                      ON account.id = preference.user_id
                     AND account.status = 'active'
                    WHERE preference.user_id = $1 AND preference.kind = $2
                    """,
                    user_id,
                    kind.value,
                )
                if wanted is not True:
                    # Switched off (or the account ended) since the event.
                    await connection.execute(
                        "UPDATE push_dispatch SET pending_count = 0 "
                        "WHERE user_id = $1 AND kind = $2",
                        user_id,
                        kind.value,
                    )
                    return None
                await connection.execute(
                    "INSERT INTO push_dispatch (user_id, kind) VALUES ($1, $2) "
                    "ON CONFLICT (user_id, kind) DO NOTHING",
                    user_id,
                    kind.value,
                )
                row = await connection.fetchrow(
                    """
                    SELECT last_sent_at, pending_count,
                           sending_event_id, sending_count
                    FROM push_dispatch
                    WHERE user_id = $1 AND kind = $2
                    FOR UPDATE
                    """,
                    user_id,
                    kind.value,
                )
                assert row is not None
                plan = plan_dispatch(
                    DispatchState(
                        last_sent_at=row["last_sent_at"],
                        pending_count=int(row["pending_count"]),
                        sending_event_id=row["sending_event_id"],
                        sending_count=int(row["sending_count"]),
                    ),
                    event_id=event_id,
                    count=count,
                    now=now,
                )
                await connection.execute(
                    """
                    UPDATE push_dispatch
                    SET last_sent_at = $3, pending_count = $4,
                        sending_event_id = $5, sending_count = $6
                    WHERE user_id = $1 AND kind = $2
                    """,
                    user_id,
                    kind.value,
                    plan.state.last_sent_at,
                    plan.state.pending_count,
                    plan.state.sending_event_id,
                    plan.state.sending_count,
                )
                if plan.flush_at is not None:
                    # The job that sends what is held back, once the 15
                    # minutes since the last push have passed.
                    await connection.execute(
                        """
                        INSERT INTO outbox_event (
                            id, aggregate_type, aggregate_id, event_type,
                            idempotency_key, payload, available_at, created_at
                        )
                        VALUES (
                            $1, 'user_account', $2, $3, $4,
                            jsonb_build_object(
                                'userId', $8::text, 'kind', $5::text, 'count', 0
                            ),
                            $6, $7
                        )
                        ON CONFLICT (idempotency_key) DO NOTHING
                        """,
                        uuid4(),
                        user_id,
                        PUSH_EVENT_TYPE,
                        f"push-flush:{kind.value}:{user_id}:"
                        f"{plan.flush_at.isoformat()}",
                        kind.value,
                        plan.flush_at,
                        now,
                        str(user_id),
                    )
                return plan.send_count

    async def subscriptions(
        self,
        *,
        user_id: UUID,
        now: datetime,
        subscription_id: UUID | None = None,
    ) -> tuple[PushSubscription, ...]:
        rows = await self._pool.fetch(
            """
            SELECT device.id, device.user_id, device.endpoint,
                   device.p256dh, device.auth
            FROM push_subscription AS device
            JOIN user_session AS session ON session.id = device.session_id
            JOIN user_account AS account
              ON account.id = device.user_id AND account.status = 'active'
            WHERE device.user_id = $1
              AND session.revoked_at IS NULL
              AND session.expires_at > $2
              AND ($3::uuid IS NULL OR device.id = $3)
            ORDER BY device.created_at, device.id
            """,
            user_id,
            now,
            subscription_id,
        )
        return tuple(
            PushSubscription(
                id=row["id"],
                user_id=row["user_id"],
                target=PushTarget(
                    endpoint=str(row["endpoint"]),
                    p256dh=bytes(row["p256dh"]),
                    auth=bytes(row["auth"]),
                ),
            )
            for row in rows
        )

    async def record_outcome(
        self, *, subscription_id: UUID, outcome: PushOutcome, now: datetime
    ) -> None:
        if outcome is PushOutcome.GONE:
            await self._pool.execute(
                "DELETE FROM push_subscription WHERE id = $1", subscription_id
            )
        elif outcome is PushOutcome.DELIVERED:
            await self._pool.execute(
                "UPDATE push_subscription "
                "SET last_success_at = $2, failure_count = 0 WHERE id = $1",
                subscription_id,
                now,
            )
        else:
            await self._pool.execute(
                "UPDATE push_subscription "
                "SET failure_count = failure_count + 1 WHERE id = $1",
                subscription_id,
            )

    async def enqueue_due_follow_ups(self, *, now: datetime) -> int:
        """One job per member with follow-ups due or overdue, once a day.

        The same rows as the "Wiedervorlagen" tab counts as overdue or due
        today: the member's own assignments that are not handed over, in
        actions where they are an active acquirer.
        """

        day = local_day(now)
        _, tomorrow = local_day_bounds(day)
        status = await self._pool.execute(
            f"""
            INSERT INTO outbox_event (
                id, aggregate_type, aggregate_id, event_type,
                idempotency_key, payload, available_at, created_at
            )
            SELECT
                gen_random_uuid(), 'user_account', preference.user_id, $2,
                'push:follow_ups:' || $3::text || ':' || preference.user_id::text,
                jsonb_build_object(
                    'userId', preference.user_id::text,
                    'kind', 'follow_ups',
                    'count', due.count
                ),
                $1, $1
            FROM (
                SELECT assignment.acquirer_user_id AS user_id,
                       count(*)::int AS count
                FROM acquisition_assignment AS assignment
                JOIN user_account AS account
                  ON account.id = assignment.acquirer_user_id
                 AND account.status = 'active'
                JOIN action_membership AS membership
                  ON membership.action_id = assignment.action_id
                 AND membership.user_id = assignment.acquirer_user_id
                 AND membership.role = 'acquirer'
                 AND membership.active_from <= $1
                 AND (
                    membership.active_until IS NULL
                    OR membership.active_until > $1
                 )
                JOIN charity_action_capability AS capability
                  ON capability.action_id = assignment.action_id
                 AND capability.capability = 'acquisition'
                WHERE assignment.status <> 'handed_over'
                  AND assignment.due_at < $4
                GROUP BY assignment.acquirer_user_id
            ) AS due
            JOIN push_preference AS preference
              ON preference.user_id = due.user_id
             AND preference.kind = 'follow_ups'
             AND preference.enabled
            WHERE {_FLAG_ON}
              AND {_LIVE_DEVICE}
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            now,
            PUSH_EVENT_TYPE,
            day.isoformat(),
            tomorrow,
        )
        return int(status.rsplit(" ", 1)[-1])

    async def purge_ended(self, *, now: datetime) -> int:
        """Delete devices whose session expired (revoked ones go at once)."""

        status = await self._pool.execute(
            """
            DELETE FROM push_subscription AS device
            USING user_session AS session
            WHERE session.id = device.session_id
              AND (session.revoked_at IS NOT NULL OR session.expires_at <= $1)
            """,
            now,
        )
        return int(status.rsplit(" ", 1)[-1])
