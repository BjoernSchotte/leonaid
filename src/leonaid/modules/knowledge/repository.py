"""Knowledge-owned transactions, revisions and authorized object references."""

from __future__ import annotations

from collections.abc import Callable

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4, uuid5

import asyncpg
from pydantic import ValidationError

from leonaid.adapters.postgres.action_progress import AsyncpgCommandReceiptRepository
from leonaid.application.errors import (
    ApplicationError,
    AuthenticationRequired,
    Conflict,
    ResourceNotFound,
)
from leonaid.domain.identity import IdentityPrincipal
from leonaid.modules.tasks.api import TaskService, CreateTask
from leonaid.modules.knowledge.api import (
    MemberQuery,
    SetPageMember,
    SetPageMemberByEmail,
    PageAccess,
    PagePermissions,
    PageMember,
    PageMembers,
    CreatePage,
    CreateTaskFromPage,
    TaskFromPage,
    UpdatePage,
    Page,
    Pages,
    PageSummary,
    PageQuery,
)
from leonaid.modules.knowledge.document import task_references

_READ_ACCESS = """
    ((p.action_id IS NULL AND (p.owner_user_id=$1 OR EXISTS (
        SELECT 1 FROM knowledge_page_member m WHERE m.page_id=p.id AND m.user_id=$1)))
    OR (p.action_id IS NOT NULL AND (
        EXISTS (SELECT 1 FROM user_global_role g WHERE g.user_id=$1 AND g.role='system_admin')
        OR EXISTS (SELECT 1 FROM action_membership m WHERE m.user_id=$1 AND m.action_id=p.action_id
            AND m.active_from<=now() AND (m.active_until IS NULL OR m.active_until>now())))))
"""


class AsyncpgKnowledgeRepository:
    def __init__(
        self,
        pool: asyncpg.Pool[Any],
        tasks: Callable[[asyncpg.Connection[Any]], TaskService],
    ) -> None:
        self.pool = pool
        self.tasks = tasks

    async def _active(
        self, conn: asyncpg.Connection[Any], actor: IdentityPrincipal
    ) -> None:
        if (
            await conn.fetchval(
                "SELECT status FROM user_account WHERE id=$1 FOR SHARE",
                actor.account.id,
            )
            != "active"
        ):
            raise AuthenticationRequired(
                "authentication_required", "Aktives Konto erforderlich."
            )

    async def _action_write(
        self, conn: asyncpg.Connection[Any], user_id: UUID, action_id: UUID
    ) -> bool:
        return bool(
            await conn.fetchval(
                """
            SELECT EXISTS (SELECT 1 FROM charity_action a WHERE a.id=$2 AND (
                EXISTS (SELECT 1 FROM user_global_role WHERE user_id=$1 AND role='system_admin')
                OR EXISTS (SELECT 1 FROM action_membership WHERE user_id=$1 AND action_id=a.id
                    AND role='charity_admin' AND active_from<=now()
                    AND (active_until IS NULL OR active_until>now()))))
        """,
                user_id,
                action_id,
            )
        )

    async def _page(
        self,
        conn: asyncpg.Connection[Any],
        actor: IdentityPrincipal,
        page_id: UUID,
        *,
        write: bool,
    ) -> Page:
        lock = "UPDATE" if write else "SHARE"
        row = await conn.fetchrow(
            f"""
            SELECT p.id,p.action_id,p.owner_user_id,p.revision
            FROM knowledge_page p
            WHERE p.id=$2 AND {_READ_ACCESS} FOR {lock} OF p
        """,
            actor.account.id,
            page_id,
        )
        if row is None:
            raise ResourceNotFound("not_found", "Seite nicht gefunden.")
        if (
            write
            and not (
                await self._permissions(
                    conn,
                    actor.account.id,
                    page_id,
                    row["owner_user_id"],
                    row["action_id"],
                )
            ).can_edit
        ):
            raise ResourceNotFound("not_found", "Seite nicht gefunden.")
        revision = await conn.fetchrow(
            "SELECT title,content FROM knowledge_page_revision WHERE page_id=$1 AND revision=$2",
            page_id,
            row["revision"],
        )
        assert revision is not None
        return Page.model_validate(
            {
                **dict(row),
                "title": revision["title"],
                "content": json.loads(revision["content"]),
            }
        )

    async def _receipt(
        self,
        conn: asyncpg.Connection[Any],
        actor: IdentityPrincipal,
        context: UUID,
        operation: str,
        command: CreatePage
        | UpdatePage
        | CreateTaskFromPage
        | SetPageMember
        | SetPageMemberByEmail,
    ) -> tuple[str, dict[str, str] | None]:
        key = f"knowledge:{actor.account.id}:{operation}:{context}:{command.idempotency_key}"
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

    async def _revision(
        self, conn: asyncpg.Connection[Any], actor: IdentityPrincipal, page: Page
    ) -> None:
        references = task_references(page.content)
        # Read-only public module operations: linking never creates or modifies a task.
        for task_id in sorted(references):
            await self.tasks(conn).get_task(actor, task_id)
        await conn.execute(
            "INSERT INTO knowledge_page_revision(page_id,revision,title,content,created_by) VALUES ($1,$2,$3,$4::jsonb,$5)",
            page.id,
            page.revision,
            page.title,
            json.dumps(page.content, ensure_ascii=False),
            actor.account.id,
        )
        for task_id in sorted(references):
            await conn.execute(
                "INSERT INTO knowledge_page_task(page_id,revision,task_id) VALUES ($1,$2,$3)",
                page.id,
                page.revision,
                task_id,
            )

    async def _finish(
        self,
        conn: asyncpg.Connection[Any],
        actor: IdentityPrincipal,
        page: Page,
        key: str,
        operation: str,
        result: dict[str, str] | None = None,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO audit_event(id,action_id,actor_user_id,event_type,entity_type,entity_id,request_id,payload)
            VALUES ($1,$2,$3,$4,'knowledge_page',$5,$6,'{}'::jsonb)
        """,
            uuid4(),
            page.action_id,
            actor.account.id,
            operation,
            page.id,
            key,
        )
        await AsyncpgCommandReceiptRepository(conn).complete(
            idempotency_key=key, result=result or {"document": page.model_dump_json()}
        )

    async def create_page(self, actor: IdentityPrincipal, command: CreatePage) -> Page:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor)
            if command.action_id is not None and not await self._action_write(
                conn, actor.account.id, command.action_id
            ):
                raise ResourceNotFound("not_found", "Aktion nicht verfügbar.")
            operation = "knowledge.page.created"
            key, replay = await self._receipt(
                conn, actor, command.action_id or actor.account.id, operation, command
            )
            if replay:
                page = Page.model_validate_json(replay["document"])
                await self._page(conn, actor, page.id, write=True)
                return page
            page = Page(
                id=uuid4(),
                action_id=command.action_id,
                owner_user_id=actor.account.id,
                revision=1,
                title=command.title,
                content=command.content,
            )
            await conn.execute(
                "INSERT INTO knowledge_page(id,action_id,owner_user_id) VALUES ($1,$2,$3)",
                page.id,
                page.action_id,
                page.owner_user_id,
            )
            await self._revision(conn, actor, page)
            await self._finish(conn, actor, page, key, operation)
            return page

    async def update_page(
        self, actor: IdentityPrincipal, page_id: UUID, command: UpdatePage
    ) -> Page:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor)
            current = await self._page(conn, actor, page_id, write=True)
            operation = "knowledge.page.updated"
            key, replay = await self._receipt(conn, actor, page_id, operation, command)
            if replay:
                return Page.model_validate_json(replay["document"])
            if current.revision != command.expected_revision:
                raise Conflict(
                    "revision_conflict", "Die Seite wurde inzwischen geändert."
                )
            page = Page(
                id=current.id,
                action_id=current.action_id,
                owner_user_id=current.owner_user_id,
                revision=current.revision + 1,
                title=command.title,
                content=command.content,
            )
            await self._revision(conn, actor, page)
            await conn.execute(
                "UPDATE knowledge_page SET revision=$2,updated_at=now() WHERE id=$1",
                page.id,
                page.revision,
            )
            await self._finish(conn, actor, page, key, operation)
            return page

    async def create_task_from_page(
        self, actor: IdentityPrincipal, page_id: UUID, command: CreateTaskFromPage
    ) -> TaskFromPage:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor)
            current = await self._page(conn, actor, page_id, write=True)
            operation = "knowledge.page.task_created"
            key, replay = await self._receipt(conn, actor, page_id, operation, command)
            tasks = self.tasks(conn)
            if replay:
                result = TaskFromPage.model_validate_json(replay["document"])
                await tasks.get_task(actor, result.task.id)
                return result
            if current.revision != command.expected_revision:
                raise Conflict(
                    "revision_conflict", "Die Seite wurde inzwischen geändert."
                )
            # Derive a page-specific key to avoid accidental receipt collisions across entry points.
            task_command = CreateTask.model_validate(
                {
                    **command.model_dump(exclude={"list_id", "expected_revision"}),
                    "idempotency_key": uuid5(page_id, str(command.idempotency_key)),
                }
            )
            task = await tasks.create_task(actor, command.list_id, task_command)
            try:
                page = Page(
                    id=current.id,
                    action_id=current.action_id,
                    owner_user_id=current.owner_user_id,
                    revision=current.revision + 1,
                    title=current.title,
                    content={
                        "type": "doc",
                        "content": [
                            *current.content["content"],
                            {
                                "type": "taskReference",
                                "attrs": {"taskId": str(task.id)},
                            },
                        ],
                    },
                )
            except ValidationError as error:
                raise Conflict(
                    "document_limit",
                    "Die Seite bietet keinen Platz für einen weiteren Verweis.",
                ) from error
            await self._revision(conn, actor, page)
            await conn.execute(
                "UPDATE knowledge_page SET revision=$2,updated_at=now() WHERE id=$1",
                page.id,
                page.revision,
            )
            result = TaskFromPage(page=page, task=task)
            await self._finish(
                conn,
                actor,
                page,
                key,
                operation,
                result={"document": result.model_dump_json()},
            )
            return result

    async def get_page(self, actor: IdentityPrincipal, page_id: UUID) -> Page:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor)
            return await self._page(conn, actor, page_id, write=False)

    async def list_pages(self, actor: IdentityPrincipal, query: PageQuery) -> Pages:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor)
            rows = await conn.fetch(
                f"""
                SELECT p.id,p.action_id,p.owner_user_id,p.revision,r.title
                FROM knowledge_page p JOIN knowledge_page_revision r ON (r.page_id,r.revision)=(p.id,p.revision)
                WHERE {_READ_ACCESS} AND ($2::uuid IS NULL OR p.action_id=$2)
                    AND strpos(lower(r.title),lower($3))>0
                ORDER BY p.created_at,p.id LIMIT $4 OFFSET $5
            """,
                actor.account.id,
                query.action_id,
                query.search,
                query.limit + 1,
                query.offset,
            )
            return Pages(
                items=[
                    PageSummary.model_validate(dict(row)) for row in rows[: query.limit]
                ],
                next_offset=query.offset + query.limit
                if len(rows) > query.limit and query.offset + query.limit <= 5000
                else None,
            )

    async def _manage_page(
        self,
        conn: asyncpg.Connection[Any],
        actor: IdentityPrincipal,
        page_id: UUID,
        *,
        write: bool,
    ) -> Page:
        page = await self._page(conn, actor, page_id, write=write)
        if not (
            await self._permissions(
                conn, actor.account.id, page_id, page.owner_user_id, page.action_id
            )
        ).can_manage:
            raise ResourceNotFound("not_found", "Seitenverwaltung nicht verfügbar.")
        return page

    async def set_page_member(
        self,
        actor: IdentityPrincipal,
        page_id: UUID,
        command: SetPageMember | SetPageMemberByEmail,
    ) -> PageAccess:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor)
            page = await self._manage_page(conn, actor, page_id, write=True)
            operation = "knowledge.page.member_changed"
            key, replay = await self._receipt(conn, actor, page_id, operation, command)
            if replay:
                return PageAccess.model_validate_json(replay["document"])
            revision = await conn.fetchval(
                "SELECT access_revision FROM knowledge_page WHERE id=$1", page_id
            )
            if revision != command.expected_access_revision:
                raise Conflict(
                    "revision_conflict", "Die Seitenrechte wurden inzwischen geändert."
                )
            if isinstance(command, SetPageMemberByEmail):
                user_id = await conn.fetchval(
                    "SELECT id FROM user_account WHERE lower(email)=lower($1) AND status='active'",
                    str(command.email),
                )
                if user_id is None:
                    raise Conflict(
                        "page_member_invalid",
                        "Dieses Konto kann nicht hinzugefügt werden.",
                    )
            else:
                user_id = command.user_id
            if user_id == page.owner_user_id:
                raise Conflict(
                    "page_owner_protected",
                    "Der Eigentümer kann nicht entfernt oder herabgestuft werden.",
                )
            if command.access is not None:
                if not await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM user_account WHERE id=$1 AND status='active')",
                    user_id,
                ):
                    raise Conflict(
                        "page_member_invalid",
                        "Dieses Konto kann nicht hinzugefügt werden.",
                    )
                if page.action_id is not None and not await conn.fetchval(
                    f"SELECT EXISTS (SELECT 1 FROM knowledge_page p WHERE p.id=$2 AND {_READ_ACCESS})",
                    user_id,
                    page_id,
                ):
                    raise Conflict(
                        "page_member_invalid", "Aktionszugriff erforderlich."
                    )
                await conn.execute(
                    "INSERT INTO knowledge_page_member(page_id,user_id,access) VALUES ($1,$2,$3) ON CONFLICT(page_id,user_id) DO UPDATE SET access=EXCLUDED.access",
                    page_id,
                    user_id,
                    command.access,
                )
            else:
                await conn.execute(
                    "DELETE FROM knowledge_page_member WHERE page_id=$1 AND user_id=$2",
                    page_id,
                    user_id,
                )
            revision = await conn.fetchval(
                "UPDATE knowledge_page SET access_revision=access_revision+1 WHERE id=$1 RETURNING access_revision",
                page_id,
            )
            result = PageAccess(
                owner_user_id=page.owner_user_id, access_revision=revision
            )
            await self._finish(
                conn,
                actor,
                page,
                key,
                operation,
                result={"document": result.model_dump_json()},
            )
            return result

    async def list_members(
        self, actor: IdentityPrincipal, page_id: UUID, query: MemberQuery
    ) -> PageMembers:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor)
            page = await self._manage_page(conn, actor, page_id, write=False)
            revision = await conn.fetchval(
                "SELECT access_revision FROM knowledge_page WHERE id=$1", page_id
            )
            rows = await conn.fetch(
                "SELECT m.user_id,u.display_name,m.access,(u.status='active') AS active FROM knowledge_page_member m JOIN user_account u ON u.id=m.user_id WHERE m.page_id=$1 AND strpos(lower(u.display_name),lower($2))>0 ORDER BY m.user_id LIMIT $3 OFFSET $4",
                page_id,
                query.search,
                query.limit + 1,
                query.offset,
            )
            return PageMembers(
                owner_user_id=page.owner_user_id,
                access_revision=revision,
                items=[
                    PageMember.model_validate(dict(row)) for row in rows[: query.limit]
                ],
                next_offset=query.offset + query.limit
                if len(rows) > query.limit and query.offset + query.limit <= 5000
                else None,
            )

    async def _permissions(
        self,
        conn: asyncpg.Connection[Any],
        user_id: UUID,
        page_id: UUID,
        owner_user_id: UUID,
        action_id: UUID | None,
    ) -> PagePermissions:
        # Call only after the page read policy has passed; ownership never bypasses action access.
        manage = owner_user_id == user_id or (
            action_id is not None and await self._action_write(conn, user_id, action_id)
        )
        edit = manage or bool(
            await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM knowledge_page_member WHERE page_id=$1 AND user_id=$2 AND access='editor')",
                page_id,
                user_id,
            )
        )
        return PagePermissions(can_edit=edit, can_manage=manage)

    async def get_permissions(
        self, actor: IdentityPrincipal, page_id: UUID
    ) -> PagePermissions:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor)
            page = await self._page(conn, actor, page_id, write=False)
            return await self._permissions(
                conn, actor.account.id, page_id, page.owner_user_id, page.action_id
            )
