"""Task-owned PostgreSQL transactions using shared command receipts and audit."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.action_progress import AsyncpgCommandReceiptRepository
from leonaid.application.errors import (
    ApplicationError,
    AuthenticationRequired,
    Conflict,
    PermissionDenied,
    ResourceNotFound,
)
from leonaid.domain.identity import IdentityPrincipal
from leonaid.modules.tasks.api import (
    Assignee,
    Assignees,
    SetListMember,
    SetListMemberByEmail,
    ListMember,
    ListMembers,
    CreateEpic,
    UpdateEpic,
    Epic,
    Epics,
    SearchPage,
    ListQuery,
    TaskQuery,
    TaskLists,
    Tasks,
    CreateList,
    CreateTask,
    UpdateTask,
    Task,
    TaskList,
)


# Same read policy for individual objects, lists, search and "for me".
_READ_ACCESS = """
    ((l.action_id IS NULL AND (l.owner_user_id=$1 OR EXISTS (
        SELECT 1 FROM task_list_member m WHERE m.list_id=l.id AND m.user_id=$1)))
    OR (l.action_id IS NOT NULL AND (
        EXISTS (SELECT 1 FROM user_global_role g WHERE g.user_id=$1 AND g.role='system_admin')
        OR EXISTS (SELECT 1 FROM action_membership m WHERE m.user_id=$1 AND m.action_id=l.action_id
            AND m.active_from <= now() AND (m.active_until IS NULL OR m.active_until > now())))))
"""


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
            f"SELECT l.id,l.title,l.action_id,l.owner_user_id,l.revision FROM task_list l WHERE l.id=$2 AND {_READ_ACCESS} FOR SHARE OF l",
            user_id,
            list_id,
        )
        if row is None:
            raise ResourceNotFound("not_found", "Liste nicht gefunden.")
        allowed = not write or row["owner_user_id"] == user_id
        if not allowed and row["action_id"] is not None:
            allowed = await self._action_access(
                conn, user_id, row["action_id"], write=True
            )
        if not allowed:
            allowed = bool(
                await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM task_list_member WHERE list_id=$1 AND user_id=$2 AND access='editor')",
                    list_id,
                    user_id,
                )
            )
        if not allowed:
            raise ResourceNotFound("not_found", "Liste nicht gefunden.")
        return TaskList.model_validate(dict(row))

    async def list_assignees(
        self, actor: IdentityPrincipal, list_id: UUID, query: SearchPage
    ) -> Assignees:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            await self._list(conn, actor.account.id, list_id, write=True)
            # Apply the identical list-read policy to each prospective assignee.
            access = _READ_ACCESS.replace("$1", "u.id")
            rows = await conn.fetch(
                f"""
                SELECT u.id AS user_id,u.display_name FROM user_account u
                CROSS JOIN task_list l WHERE l.id=$1 AND u.status='active'
                    AND {access} AND strpos(lower(u.display_name), lower($2)) > 0
                ORDER BY lower(u.display_name),u.id LIMIT $3 OFFSET $4
                """,
                list_id,
                query.search,
                query.limit + 1,
                query.offset,
            )
            return Assignees(
                items=[
                    Assignee.model_validate(dict(row)) for row in rows[: query.limit]
                ],
                next_offset=query.offset + query.limit
                if len(rows) > query.limit and query.offset + query.limit <= 5000
                else None,
            )

    async def list_lists(self, actor: IdentityPrincipal, query: ListQuery) -> TaskLists:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            rows = await conn.fetch(
                f"""
                SELECT l.id,l.title,l.action_id,l.owner_user_id,l.revision FROM task_list l
                WHERE {_READ_ACCESS} AND ($2::uuid IS NULL OR l.action_id=$2)
                    AND strpos(lower(l.title), lower($3)) > 0
                ORDER BY l.created_at,l.id LIMIT $4 OFFSET $5
            """,
                actor.account.id,
                query.action_id,
                query.search,
                query.limit + 1,
                query.offset,
            )
            return TaskLists(
                items=[
                    TaskList.model_validate(dict(row)) for row in rows[: query.limit]
                ],
                next_offset=query.offset + query.limit
                if len(rows) > query.limit and query.offset + query.limit <= 5000
                else None,
            )

    async def list_tasks(self, actor: IdentityPrincipal, query: TaskQuery) -> Tasks:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            if query.list_id is not None:
                await self._list(conn, actor.account.id, query.list_id, write=False)
            rows = await conn.fetch(
                f"""
                SELECT t.* FROM task t JOIN task_list l ON l.id=t.list_id
                WHERE {_READ_ACCESS} AND ($2::uuid IS NULL OR t.list_id=$2)
                    AND (NOT $3 OR t.assignee_user_id=$1)
                    AND ($4::text IS NULL OR t.status=$4)
                    AND ($5 OR t.deferred_until IS NULL OR t.deferred_until<=now())
                    AND strpos(lower(t.title), lower($6)) > 0
                ORDER BY t.created_at,t.id LIMIT $7 OFFSET $8
            """,
                actor.account.id,
                query.list_id,
                query.for_me,
                query.status,
                query.include_deferred,
                query.search,
                query.limit + 1,
                query.offset,
            )
            return Tasks(
                items=[Task.model_validate(dict(row)) for row in rows[: query.limit]],
                next_offset=query.offset + query.limit
                if len(rows) > query.limit and query.offset + query.limit <= 5000
                else None,
            )

    async def _receipt(
        self,
        conn: asyncpg.Connection[Any],
        actor: UUID,
        context: UUID,
        operation: str,
        command: CreateList
        | CreateTask
        | UpdateTask
        | CreateEpic
        | UpdateEpic
        | SetListMember
        | SetListMemberByEmail,
    ) -> tuple[str, dict[str, str] | None]:
        key = f"tasks:{actor}:{operation}:{context}:{command.idempotency_key}"
        digest = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
        try:
            replay = await AsyncpgCommandReceiptRepository(conn).reserve(
                idempotency_key=key, command_type=operation, request_hash=digest
            )
        except ApplicationError as error:
            if error.code == "idempotency_conflict":
                raise Conflict(error.code, error.message) from error
            raise
        return key, replay

    async def _finish(
        self,
        conn: asyncpg.Connection[Any],
        *,
        key: str,
        operation: str,
        actor: UUID,
        action_id: UUID | None,
        result: Task | TaskList | Epic,
        details: dict[str, str] | None = None,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO audit_event (id,action_id,actor_user_id,event_type,entity_type,entity_id,request_id,payload)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
        """,
            uuid4(),
            action_id,
            actor,
            operation,
            "task_list"
            if isinstance(result, TaskList)
            else "task_epic"
            if isinstance(result, Epic)
            else "task",
            result.id,
            key,
            json.dumps(details or {}),
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

    async def create_epic(
        self, actor: IdentityPrincipal, list_id: UUID, command: CreateEpic
    ) -> Epic:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            listing = await self._list(conn, actor.account.id, list_id, write=True)
            key, replay = await self._receipt(
                conn, actor.account.id, list_id, "tasks.epic.created", command
            )
            if replay:
                return Epic.model_validate_json(replay["document"])
            row = await conn.fetchrow(
                "INSERT INTO task_epic (id,list_id,title) VALUES ($1,$2,$3) RETURNING id,list_id,title,revision",
                uuid4(),
                list_id,
                command.title,
            )
            assert row is not None
            result = Epic.model_validate(dict(row))
            await self._finish(
                conn,
                key=key,
                operation="tasks.epic.created",
                actor=actor.account.id,
                action_id=listing.action_id,
                result=result,
            )
            return result

    async def update_epic(
        self, actor: IdentityPrincipal, epic_id: UUID, command: UpdateEpic
    ) -> Epic:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            row = await conn.fetchrow(
                "SELECT id,list_id,title,revision FROM task_epic WHERE id=$1 FOR UPDATE",
                epic_id,
            )
            if row is None:
                raise ResourceNotFound("not_found", "Epic nicht gefunden.")
            listing = await self._list(
                conn, actor.account.id, row["list_id"], write=True
            )
            key, replay = await self._receipt(
                conn, actor.account.id, epic_id, "tasks.epic.updated", command
            )
            if replay:
                return Epic.model_validate_json(replay["document"])
            if row["revision"] != command.expected_revision:
                raise Conflict("revision_conflict", "Epic wurde inzwischen geändert.")
            updated = await conn.fetchrow(
                "UPDATE task_epic SET title=$2,revision=revision+1,updated_at=now() WHERE id=$1 RETURNING id,list_id,title,revision",
                epic_id,
                command.title,
            )
            assert updated is not None
            result = Epic.model_validate(dict(updated))
            await self._finish(
                conn,
                key=key,
                operation="tasks.epic.updated",
                actor=actor.account.id,
                action_id=listing.action_id,
                result=result,
            )
            return result

    async def list_epics(
        self, actor: IdentityPrincipal, list_id: UUID, query: SearchPage
    ) -> Epics:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            await self._list(conn, actor.account.id, list_id, write=False)
            rows = await conn.fetch(
                "SELECT id,list_id,title,revision FROM task_epic WHERE list_id=$1 AND strpos(lower(title),lower($2))>0 ORDER BY created_at,id LIMIT $3 OFFSET $4",
                list_id,
                query.search,
                query.limit + 1,
                query.offset,
            )
            return Epics(
                items=[Epic.model_validate(dict(row)) for row in rows[: query.limit]],
                next_offset=query.offset + query.limit
                if len(rows) > query.limit and query.offset + query.limit <= 5000
                else None,
            )

    async def _manage_list(
        self, conn: asyncpg.Connection[Any], user_id: UUID, list_id: UUID
    ) -> TaskList:
        listing = await self._list(conn, user_id, list_id, write=False)
        if listing.owner_user_id != user_id and not (
            listing.action_id is not None
            and await self._action_access(conn, user_id, listing.action_id, write=True)
        ):
            raise PermissionDenied(
                "permission_denied",
                "Nur die Listen- oder Aktionsverwaltung darf Zugriffsrechte verwalten.",
            )
        return listing

    async def set_list_member(
        self, actor: IdentityPrincipal, list_id: UUID, command: SetListMember
    ) -> TaskList:
        return await self._set_list_member(actor, list_id, command)

    async def set_list_member_by_email(
        self, actor: IdentityPrincipal, list_id: UUID, command: SetListMemberByEmail
    ) -> TaskList:
        return await self._set_list_member(actor, list_id, command)

    async def _set_list_member(
        self,
        actor: IdentityPrincipal,
        list_id: UUID,
        command: SetListMember | SetListMemberByEmail,
    ) -> TaskList:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            # Lock before the read-policy check to avoid upgrading concurrent shared locks.
            await conn.fetchval(
                "SELECT id FROM task_list WHERE id=$1 FOR UPDATE", list_id
            )
            listing = await self._manage_list(conn, actor.account.id, list_id)
            key, replay = await self._receipt(
                conn, actor.account.id, list_id, "tasks.list.member.changed", command
            )
            if replay:
                return TaskList.model_validate_json(replay["document"])
            if listing.revision != command.expected_revision:
                raise Conflict(
                    "revision_conflict", "Listenrechte wurden inzwischen geändert."
                )
            if isinstance(command, SetListMemberByEmail):
                user_id = await conn.fetchval(
                    "SELECT id FROM user_account WHERE lower(email)=lower($1) AND status='active'",
                    str(command.email),
                )
                if user_id is None:
                    raise Conflict(
                        "list_member_invalid",
                        "Dieses Konto kann nicht hinzugefügt werden.",
                    )
            else:
                user_id = command.user_id
            if user_id == listing.owner_user_id:
                raise Conflict(
                    "list_owner_protected",
                    "Der Eigentümer behält den Zugriff auf die Liste.",
                )
            if command.access is not None:
                if not await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM user_account WHERE id=$1 AND status='active')",
                    user_id,
                ):
                    raise Conflict(
                        "list_member_invalid", "Dieses Konto ist nicht verfügbar."
                    )
                if listing.action_id is not None and not await self._action_access(
                    conn, user_id, listing.action_id, write=False
                ):
                    raise Conflict(
                        "list_member_invalid", "Aktionszugriff erforderlich."
                    )
                await conn.execute(
                    "INSERT INTO task_list_member (list_id,user_id,access) VALUES ($1,$2,$3) ON CONFLICT (list_id,user_id) DO UPDATE SET access=EXCLUDED.access",
                    list_id,
                    user_id,
                    command.access,
                )
            else:
                await conn.execute(
                    "DELETE FROM task_list_member WHERE list_id=$1 AND user_id=$2",
                    list_id,
                    user_id,
                )
            row = await conn.fetchrow(
                "UPDATE task_list SET revision=revision+1,updated_at=now() WHERE id=$1 RETURNING id,title,action_id,owner_user_id,revision",
                list_id,
            )
            assert row is not None
            result = TaskList.model_validate(dict(row))
            await self._finish(
                conn,
                key=key,
                operation="tasks.list.member.changed",
                actor=actor.account.id,
                action_id=listing.action_id,
                result=result,
                details={
                    "userId": str(user_id),
                    "access": command.access or "removed",
                },
            )
            return result

    async def list_members(
        self, actor: IdentityPrincipal, list_id: UUID, query: SearchPage
    ) -> ListMembers:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            listing = await self._manage_list(conn, actor.account.id, list_id)
            rows = await conn.fetch(
                "SELECT m.user_id,u.display_name,m.access,(u.status='active') AS active FROM task_list_member m JOIN user_account u ON u.id=m.user_id WHERE m.list_id=$1 AND strpos(lower(u.display_name),lower($2))>0 ORDER BY m.user_id LIMIT $3 OFFSET $4",
                list_id,
                query.search,
                query.limit + 1,
                query.offset,
            )
            return ListMembers(
                items=[
                    ListMember.model_validate(dict(row)) for row in rows[: query.limit]
                ],
                owner_user_id=listing.owner_user_id,
                revision=listing.revision,
                next_offset=query.offset + query.limit
                if len(rows) > query.limit and query.offset + query.limit <= 5000
                else None,
            )
