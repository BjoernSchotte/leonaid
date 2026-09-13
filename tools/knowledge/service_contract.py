#!/usr/bin/env python3
"""Real knowledge transactions and permissions, including a one-connection pool."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg

from leonaid.application.errors import (
    Conflict,
    ResourceNotFound,
    AuthenticationRequired,
)
from leonaid.bootstrap.api import build_knowledge_service, build_task_service
from leonaid.domain.identity import IdentityPrincipal, UserAccount, AccountStatus
from leonaid.modules.knowledge.api import CreatePage, UpdatePage, PageQuery
from leonaid.modules.tasks.api import CreateList, CreateTask, TaskService
from leonaid.modules.tasks.repository import AsyncpgTaskRepository


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=1, command_timeout=10
    )
    assert pool is not None
    owner_id, reader_id = uuid4(), uuid4()
    actors = [
        IdentityPrincipal(
            UserAccount(
                user_id,
                f"{user_id}@example.org",
                "Knowledge proof",
                AccountStatus.ACTIVE,
            ),
            frozenset(),
            (),
        )
        for user_id in (owner_id, reader_id)
    ]
    owner, reader = actors
    knowledge = build_knowledge_service(pool)
    tasks = build_task_service(pool)
    try:
        async with pool.acquire() as conn:
            for actor in actors:
                await conn.execute(
                    "INSERT INTO user_account(id,email,display_name,status) VALUES ($1,$2,'Knowledge proof','active')",
                    actor.account.id,
                    actor.account.email,
                )
        listing = await tasks.create_list(
            owner, CreateList(idempotency_key=uuid4(), title="Task references")
        )
        task = await tasks.create_task(
            owner,
            listing.id,
            CreateTask(idempotency_key=uuid4(), title="Private task title"),
        )
        rolled_task = None
        async with pool.acquire() as conn:
            try:
                async with conn.transaction():
                    bound_tasks = TaskService(
                        AsyncpgTaskRepository(pool, connection=conn)
                    )
                    rolled_task = await bound_tasks.create_task(
                        owner,
                        listing.id,
                        CreateTask(idempotency_key=uuid4(), title="Must roll back"),
                    )
                    raise RuntimeError("Outer transaction rollback proof")
            except RuntimeError as error:
                assert str(error) == "Outer transaction rollback proof"
            assert rolled_task is not None
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM task WHERE id=$1", rolled_task.id
                )
                == 0
            )
        content = {
            "type": "doc",
            "content": [
                {"type": "paragraph"},
                {"type": "taskReference", "attrs": {"taskId": str(task.id)}},
            ],
        }
        command = CreatePage(
            idempotency_key=uuid4(), title="First page", content=content
        )
        async with asyncio.timeout(10):
            page, replay = await asyncio.gather(
                knowledge.create_page(owner, command),
                knowledge.create_page(owner, command),
            )
        assert page == replay and page.revision == 1
        assert (await knowledge.get_page(owner, page.id)) == page
        assert (
            len((await knowledge.list_pages(owner, PageQuery(search="FIRST"))).items)
            == 1
        )
        assert not (await knowledge.list_pages(owner, PageQuery(search="%"))).items
        assert not (await knowledge.list_pages(reader, PageQuery())).items
        try:
            await knowledge.get_page(reader, page.id)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Private page disclosed")
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO knowledge_page_member(page_id,user_id,access) VALUES ($1,$2,'viewer')",
                page.id,
                reader_id,
            )
        assert (await knowledge.get_page(reader, page.id)).content == content
        try:
            await tasks.get_task(reader, task.id)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Page reference expanded task access")
        update = UpdatePage(
            idempotency_key=uuid4(),
            expected_revision=1,
            title="Second page",
            content={"type": "doc", "content": [{"type": "paragraph"}]},
        )
        try:
            await knowledge.update_page(reader, page.id, update)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Viewer wrote page")
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE knowledge_page_member SET access='editor' WHERE page_id=$1",
                page.id,
            )
        changed = await knowledge.update_page(reader, page.id, update)
        assert changed.revision == 2
        assert await knowledge.update_page(reader, page.id, update) == changed
        try:
            await knowledge.update_page(
                reader, page.id, update.model_copy(update={"idempotency_key": uuid4()})
            )
        except Conflict as error:
            assert error.code == "revision_conflict"
        else:
            raise AssertionError("Stale revision accepted")
        forbidden = UpdatePage(
            idempotency_key=uuid4(),
            expected_revision=2,
            title="Forbidden reference",
            content=content,
        )
        try:
            await knowledge.update_page(reader, page.id, forbidden)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Unreadable task could be embedded")
        assert (await knowledge.get_page(owner, page.id)).revision == 2
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM knowledge_page_revision WHERE page_id=$1",
                    page.id,
                )
                == 2
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM knowledge_page_task WHERE page_id=$1 AND revision=1",
                    page.id,
                )
                == 1
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM knowledge_page_task WHERE page_id=$1 AND revision=2",
                    page.id,
                )
                == 0
            )
            assert (
                await conn.fetchval("SELECT count(*) FROM task WHERE id=$1", task.id)
                == 1
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM command_receipt WHERE idempotency_key LIKE 'knowledge:%' AND idempotency_key LIKE $1",
                    f"%{page.id}%",
                )
                == 1
            )
            await conn.execute(
                "DELETE FROM knowledge_page_member WHERE page_id=$1", page.id
            )
        concurrent_pool = await asyncpg.create_pool(
            os.environ["CORE_DATABASE_URL"], min_size=2, max_size=2, command_timeout=10
        )
        assert concurrent_pool is not None
        try:
            concurrent = build_knowledge_service(concurrent_pool)
            results = await asyncio.gather(
                *[
                    concurrent.update_page(
                        owner,
                        page.id,
                        UpdatePage(
                            idempotency_key=uuid4(),
                            expected_revision=2,
                            title=title,
                            content=changed.content,
                        ),
                    )
                    for title in ("Concurrent A", "Concurrent B")
                ],
                return_exceptions=True,
            )
            assert (
                sum(
                    isinstance(result, Conflict) and result.code == "revision_conflict"
                    for result in results
                )
                == 1
            )
            assert sum(not isinstance(result, BaseException) for result in results) == 1
            assert (await concurrent.get_page(owner, page.id)).revision == 3
        finally:
            await concurrent_pool.close()
        try:
            await knowledge.update_page(reader, page.id, update)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Replay bypassed revoked access")
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_account SET status='suspended' WHERE id=$1", owner_id
            )
        try:
            await knowledge.create_page(owner, command)
        except AuthenticationRequired:
            pass
        else:
            raise AssertionError("Replay bypassed suspension")
        print(
            "PASS knowledge one-connection references, revisions, rollback, history, search, current ACL and replay"
        )
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM knowledge_page WHERE owner_user_id=ANY($1::uuid[])",
                [owner_id, reader_id],
            )
            await conn.execute(
                "DELETE FROM task WHERE created_by=ANY($1::uuid[])",
                [owner_id, reader_id],
            )
            await conn.execute(
                "DELETE FROM task_list WHERE owner_user_id=ANY($1::uuid[])",
                [owner_id, reader_id],
            )
            await conn.execute(
                "DELETE FROM audit_event WHERE actor_user_id=ANY($1::uuid[])",
                [owner_id, reader_id],
            )
            for user_id in (owner_id, reader_id):
                await conn.execute(
                    "DELETE FROM command_receipt WHERE idempotency_key LIKE $1 OR idempotency_key LIKE $2",
                    f"knowledge:{user_id}:%",
                    f"tasks:{user_id}:%",
                )
            await conn.execute(
                "DELETE FROM user_account WHERE id=ANY($1::uuid[])",
                [owner_id, reader_id],
            )
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
