"""Task-owned PostgreSQL transactions using shared command receipts and audit."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.action_progress import AsyncpgCommandReceiptRepository
from leonaid.application.errors import (
    AuthenticationRequired,
    Conflict,
    PermissionDenied,
    ResourceNotFound,
)
from leonaid.domain.identity import IdentityPrincipal
from leonaid.modules.tasks.api import CreateList, CreateTask, UpdateTask, Task, TaskList


class AsyncpgTaskRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self.pool = pool

    async def _active(self, conn: asyncpg.Connection[Any], user_id: UUID) -> None:
        status = await conn.fetchval(
            "SELECT status FROM user_account WHERE id=$1 FOR SHARE", user_id
        )
        if status != "active":
            raise AuthenticationRequired(
                "authentication_required", "Aktives Konto erforderlich."
            )

    async def _action_access(
        self,
        conn: asyncpg.Connection[Any],
        user_id: UUID,
        action_id: UUID,
        *,
        write: bool,
    ) -> bool:
        return bool(
            await conn.fetchval(
                """
            SELECT EXISTS (SELECT 1 FROM user_global_role WHERE user_id=$1 AND role='system_admin')
            OR EXISTS (SELECT 1 FROM action_membership WHERE user_id=$1 AND action_id=$2
                AND active_from <= now() AND (active_until IS NULL OR active_until > now())
                AND (NOT $3 OR role='charity_admin'))
        """,
                user_id,
                action_id,
                write,
            )
        )

    async def _list(
        self,
        conn: asyncpg.Connection[Any],
        user_id: UUID,
        list_id: UUID,
        *,
        write: bool,
    ) -> TaskList:
        row = await conn.fetchrow(
            "SELECT id,title,action_id,owner_user_id,revision FROM task_list WHERE id=$1 FOR SHARE",
            list_id,
        )
        if row is None:
            raise ResourceNotFound("not_found", "Liste nicht gefunden.")
        if row["action_id"] is not None:
            # Explicit grants do not bypass a revoked action membership.
            allowed = await self._action_access(
                conn, user_id, row["action_id"], write=write
            )
            if not allowed and not write:
                raise ResourceNotFound("not_found", "Liste nicht gefunden.")
            if not allowed and await self._action_access(
                conn, user_id, row["action_id"], write=False
            ):
                allowed = row["owner_user_id"] == user_id or await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM task_list_member WHERE list_id=$1 AND user_id=$2 AND access='editor')",
                    list_id,
                    user_id,
                )
        else:
            allowed = row["owner_user_id"] == user_id or await conn.fetchval(
                """
                SELECT EXISTS (SELECT 1 FROM task_list_member WHERE list_id=$1 AND user_id=$2
                    AND (NOT $3 OR access='editor'))
            """,
                list_id,
                user_id,
                write,
            )
        if not allowed:
            raise ResourceNotFound("not_found", "Liste nicht gefunden.")
        return TaskList.model_validate(dict(row))

    async def _receipt(
        self,
        conn: asyncpg.Connection[Any],
        actor: UUID,
        context: UUID,
        operation: str,
        command: CreateList | CreateTask | UpdateTask,
    ) -> tuple[str, dict[str, str] | None]:
        key = f"tasks:{actor}:{operation}:{context}:{command.idempotency_key}"
        digest = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
        replay = await AsyncpgCommandReceiptRepository(conn).reserve(
            idempotency_key=key, command_type=operation, request_hash=digest
        )
        return key, replay

    async def _finish(
        self,
        conn: asyncpg.Connection[Any],
        *,
        key: str,
        operation: str,
        actor: UUID,
        action_id: UUID | None,
        result: Task | TaskList,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO audit_event (id,action_id,actor_user_id,event_type,entity_type,entity_id,request_id,payload)
            VALUES ($1,$2,$3,$4,$5,$6,$7,'{}'::jsonb)
        """,
            uuid4(),
            action_id,
            actor,
            operation,
            "task_list" if isinstance(result, TaskList) else "task",
            result.id,
            key,
        )
        await AsyncpgCommandReceiptRepository(conn).complete(
            idempotency_key=key, result={"document": result.model_dump_json()}
        )

    async def create_list(
        self, actor: IdentityPrincipal, command: CreateList
    ) -> TaskList:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            if command.action_id is not None:
                if not await self._action_access(
                    conn, actor.account.id, command.action_id, write=True
                ):
                    raise PermissionDenied(
                        "permission_denied", "Aktionsverwaltung erforderlich."
                    )
                if not await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM charity_action WHERE id=$1)",
                    command.action_id,
                ):
                    raise ResourceNotFound("not_found", "Aktion nicht gefunden.")
            key, replay = await self._receipt(
                conn,
                actor.account.id,
                command.action_id or actor.account.id,
                "tasks.list.created",
                command,
            )
            if replay:
                result = TaskList.model_validate_json(replay["document"])
                await self._list(conn, actor.account.id, result.id, write=True)
                return result
            row = await conn.fetchrow(
                """
                INSERT INTO task_list (id,title,action_id,owner_user_id) VALUES ($1,$2,$3,$4)
                RETURNING id,title,action_id,owner_user_id,revision
            """,
                uuid4(),
                command.title,
                command.action_id,
                actor.account.id,
            )
            assert row is not None
            result = TaskList.model_validate(dict(row))
            await self._finish(
                conn,
                key=key,
                operation="tasks.list.created",
                actor=actor.account.id,
                action_id=command.action_id,
                result=result,
            )
            return result

    async def get_list(self, actor: IdentityPrincipal, list_id: UUID) -> TaskList:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            return await self._list(conn, actor.account.id, list_id, write=False)

    async def _validate_references(
        self,
        conn: asyncpg.Connection[Any],
        list_id: UUID,
        command: CreateTask | UpdateTask,
    ) -> None:
        if command.epic_id is not None and not await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM task_epic WHERE id=$1 AND list_id=$2)",
            command.epic_id,
            list_id,
        ):
            raise Conflict("task_epic_invalid", "Epic gehört nicht zu dieser Liste.")
        if command.assignee_user_id is not None:
            if not await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM user_account WHERE id=$1 AND status='active')",
                command.assignee_user_id,
            ):
                raise Conflict(
                    "task_assignee_invalid", "Zuständige Person ist nicht verfügbar."
                )
            await self._list(conn, command.assignee_user_id, list_id, write=False)

    async def create_task(
        self, actor: IdentityPrincipal, list_id: UUID, command: CreateTask
    ) -> Task:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            listing = await self._list(conn, actor.account.id, list_id, write=True)
            key, replay = await self._receipt(
                conn, actor.account.id, list_id, "tasks.task.created", command
            )
            if replay:
                return Task.model_validate_json(replay["document"])
            await self._validate_references(conn, list_id, command)
            row = await conn.fetchrow(
                """
                INSERT INTO task (id,list_id,title,description,epic_id,assignee_user_id,due_at,deferred_until,created_by)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *
            """,
                uuid4(),
                list_id,
                command.title,
                command.description,
                command.epic_id,
                command.assignee_user_id,
                command.due_at,
                command.deferred_until,
                actor.account.id,
            )
            assert row is not None
            result = Task.model_validate(dict(row))
            await self._finish(
                conn,
                key=key,
                operation="tasks.task.created",
                actor=actor.account.id,
                action_id=listing.action_id,
                result=result,
            )
            return result

    async def get_task(self, actor: IdentityPrincipal, task_id: UUID) -> Task:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            row = await conn.fetchrow("SELECT * FROM task WHERE id=$1", task_id)
            if row is None:
                raise ResourceNotFound("not_found", "Task nicht gefunden.")
            await self._list(conn, actor.account.id, row["list_id"], write=False)
            return Task.model_validate(dict(row))

    async def update_task(
        self, actor: IdentityPrincipal, task_id: UUID, command: UpdateTask
    ) -> Task:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            row = await conn.fetchrow(
                "SELECT * FROM task WHERE id=$1 FOR UPDATE", task_id
            )
            if row is None:
                raise ResourceNotFound("not_found", "Task nicht gefunden.")
            listing = await self._list(
                conn, actor.account.id, row["list_id"], write=True
            )
            key, replay = await self._receipt(
                conn, actor.account.id, task_id, "tasks.task.updated", command
            )
            if replay:
                return Task.model_validate_json(replay["document"])
            if row["revision"] != command.expected_revision:
                raise Conflict("revision_conflict", "Task wurde inzwischen geändert.")
            await self._validate_references(conn, row["list_id"], command)
            updated = await conn.fetchrow(
                """
                UPDATE task SET title=$2,description=$3,epic_id=$4,assignee_user_id=$5,due_at=$6,
                    deferred_until=$7,status=$8,revision=revision+1,updated_at=now() WHERE id=$1 RETURNING *
            """,
                task_id,
                command.title,
                command.description,
                command.epic_id,
                command.assignee_user_id,
                command.due_at,
                command.deferred_until,
                command.status,
            )
            assert updated is not None
            result = Task.model_validate(dict(updated))
            await self._finish(
                conn,
                key=key,
                operation="tasks.task.updated",
                actor=actor.account.id,
                action_id=listing.action_id,
                result=result,
            )
            return result
