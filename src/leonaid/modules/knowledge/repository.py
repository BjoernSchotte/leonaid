"""Knowledge-owned transactions, revisions and authorized object references."""

from __future__ import annotations

from collections.abc import Callable

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
    ResourceNotFound,
)
from leonaid.domain.identity import IdentityPrincipal
from leonaid.modules.tasks.api import TaskService
from leonaid.modules.knowledge.api import (
    CreatePage,
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
        allowed = not write or row["owner_user_id"] == actor.account.id
        if not allowed and row["action_id"] is not None:
            allowed = await self._action_write(conn, actor.account.id, row["action_id"])
        if not allowed:
            allowed = bool(
                await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM knowledge_page_member WHERE page_id=$1 AND user_id=$2 AND access='editor')",
                    page_id,
                    actor.account.id,
                )
            )
        if not allowed:
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
        command: CreatePage | UpdatePage,
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
            idempotency_key=key, result={"document": page.model_dump_json()}
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
