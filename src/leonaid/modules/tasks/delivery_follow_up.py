""" "Nachliefern" tasks for missed deliveries (the board's follow-up port).

The delivery board calls ``sync`` inside its own transaction while the tasks
module is enabled. One task per missed order, in a list "Nachliefern" per
action and assignee. The task mirrors the drop: a missed drop means an open
task, a delivered one (or a reopened window) a done task. Changes are
audited. Board actors may be drivers without task rights, so this module
writes its own rows directly instead of going through ``TaskService``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.modules.tasks.ordering import POSITION_STEP

FOLLOW_UP_LIST_TITLE = "Nachliefern"


class TaskDeliveryFollowUp:
    async def _list(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        owner_user_id: UUID,
    ) -> UUID:
        existing = await connection.fetchval(
            """
            SELECT list_id FROM task_delivery_follow_up_list
            WHERE action_id = $1 AND owner_user_id = $2
            """,
            action_id,
            owner_user_id,
        )
        if existing is not None:
            return UUID(str(existing))
        list_id = uuid4()
        await connection.execute(
            """
            INSERT INTO task_list (id, title, action_id, owner_user_id)
            VALUES ($1, $2, $3, $4)
            """,
            list_id,
            FOLLOW_UP_LIST_TITLE,
            action_id,
            owner_user_id,
        )
        await connection.execute(
            """
            INSERT INTO task_delivery_follow_up_list (action_id, owner_user_id, list_id)
            VALUES ($1, $2, $3)
            """,
            action_id,
            owner_user_id,
            list_id,
        )
        return list_id

    async def _audit(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        actor_user_id: UUID,
        event_type: str,
        task_id: UUID,
        commitment_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type, entity_type,
                entity_id, request_id, payload, occurred_at
            )
            VALUES ($1, $2, $3, $4, 'task', $5, $6, $7::jsonb, $8)
            """,
            uuid4(),
            action_id,
            actor_user_id,
            event_type,
            task_id,
            request_id,
            json.dumps({"commitmentId": str(commitment_id)}),
            occurred_at,
        )

    async def sync(
        self,
        connection: Any,
        *,
        action_id: UUID,
        commitment_id: UUID,
        title: str,
        description: str,
        needed: bool,
        assignee_user_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> None:
        current = await connection.fetchrow(
            """
            SELECT follow_up.task_id, task.status, task.list_id
            FROM task_delivery_follow_up AS follow_up
            JOIN task ON task.id = follow_up.task_id
            WHERE follow_up.commitment_id = $1
            FOR UPDATE OF task
            """,
            commitment_id,
        )
        if current is None:
            if not needed:
                return
            list_id = await self._list(
                connection, action_id=action_id, owner_user_id=assignee_user_id
            )
            await connection.fetchval(
                "SELECT id FROM task_list WHERE id = $1 FOR UPDATE", list_id
            )
            task_id = uuid4()
            await connection.execute(
                """
                INSERT INTO task (
                    id, list_id, title, description, assignee_user_id,
                    created_by, manual_position, created_at, updated_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6,
                    (SELECT coalesce(max(manual_position), 0) + $7
                     FROM task WHERE list_id = $2 AND epic_id IS NULL),
                    $8, $8
                )
                """,
                task_id,
                list_id,
                title,
                description,
                assignee_user_id,
                actor_user_id,
                POSITION_STEP,
                occurred_at,
            )
            await connection.execute(
                "UPDATE task_list SET order_revision = order_revision + 1 WHERE id = $1",
                list_id,
            )
            await connection.execute(
                """
                INSERT INTO task_delivery_follow_up (commitment_id, task_id)
                VALUES ($1, $2)
                """,
                commitment_id,
                task_id,
            )
            await self._audit(
                connection,
                action_id=action_id,
                actor_user_id=actor_user_id,
                event_type="tasks.delivery_follow_up_created",
                task_id=task_id,
                commitment_id=commitment_id,
                request_id=request_id,
                occurred_at=occurred_at,
            )
            return
        target = "open" if needed else "done"
        if current["status"] == target:
            return
        await connection.execute(
            """
            UPDATE task SET status = $2, revision = revision + 1, updated_at = $3
            WHERE id = $1
            """,
            current["task_id"],
            target,
            occurred_at,
        )
        await self._audit(
            connection,
            action_id=action_id,
            actor_user_id=actor_user_id,
            event_type=(
                "tasks.delivery_follow_up_reopened"
                if needed
                else "tasks.delivery_follow_up_closed"
            ),
            task_id=current["task_id"],
            commitment_id=commitment_id,
            request_id=request_id,
            occurred_at=occurred_at,
        )
