#!/usr/bin/env python3
"""Real knowledge transactions and permissions, including a one-connection pool."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg

from leonaid.adapters.storage.s3 import S3ObjectStorage

from leonaid.application.errors import (
    Conflict,
    ResourceNotFound,
)
from leonaid.bootstrap.api import build_knowledge_service, build_task_service
from leonaid.domain.identity import IdentityPrincipal, UserAccount, AccountStatus
from leonaid.modules.knowledge.api import CreatePage, CreateTaskFromPage
from leonaid.modules.tasks.api import CreateList, CreateTask, UpdateTask


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=1, command_timeout=10
    )
    assert pool is not None
    storage = S3ObjectStorage(
        endpoint_url=os.environ["OBJECT_STORAGE_ENDPOINT_URL"],
        access_key=os.environ["OBJECT_STORAGE_ACCESS_KEY"],
        secret_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],
        bucket=os.environ["OBJECT_STORAGE_BUCKET"],
    )
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
    knowledge = build_knowledge_service(pool, storage)
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
        await tasks.create_task(
            owner,
            listing.id,
            CreateTask(idempotency_key=uuid4(), title="Private task title"),
        )
        page = await knowledge.create_page(
            owner, CreatePage(idempotency_key=uuid4(), title="Page to task")
        )
        command = CreateTaskFromPage(
            idempotency_key=uuid4(),
            list_id=listing.id,
            expected_revision=1,
            title="Composed task",
            assignee_user_id=owner_id,
        )
        async with asyncio.timeout(10):
            result, replay = await asyncio.gather(
                knowledge.create_task_from_page(owner, page.id, command),
                knowledge.create_task_from_page(owner, page.id, command),
            )
        assert result == replay and result.page.revision == 2
        assert result.page.content["content"][-1] == {
            "type": "taskReference",
            "attrs": {"taskId": str(result.task.id)},
        }
        done = await tasks.update_task(
            owner,
            result.task.id,
            UpdateTask(
                idempotency_key=uuid4(),
                expected_revision=1,
                title=result.task.title,
                status="done",
                assignee_user_id=owner_id,
            ),
        )
        assert done.status == "done"
        assert (await knowledge.get_page(owner, page.id)).content == result.page.content
        try:
            await knowledge.create_task_from_page(
                owner, page.id, command.model_copy(update={"idempotency_key": uuid4()})
            )
        except Conflict as error:
            assert error.code == "revision_conflict"
        else:
            raise AssertionError("Stale page created task")
        try:
            await knowledge.create_task_from_page(reader, page.id, command)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Reader created task")
        full = await knowledge.create_page(
            owner,
            CreatePage(
                idempotency_key=uuid4(),
                title="Full",
                content={
                    "type": "doc",
                    "content": [{"type": "paragraph"} for _ in range(9999)],
                },
            ),
        )
        async with pool.acquire() as conn:
            before = tuple(
                [
                    await conn.fetchval(f"SELECT count(*) FROM {table}")
                    for table in (
                        "task",
                        "audit_event",
                        "command_receipt",
                        "knowledge_page_revision",
                    )
                ]
            )
        try:
            await knowledge.create_task_from_page(
                owner, full.id, command.model_copy(update={"idempotency_key": uuid4()})
            )
        except Conflict as error:
            assert error.code == "document_limit"
        else:
            raise AssertionError("Overfull page accepted")
        async with pool.acquire() as conn:
            after = tuple(
                [
                    await conn.fetchval(f"SELECT count(*) FROM {table}")
                    for table in (
                        "task",
                        "audit_event",
                        "command_receipt",
                        "knowledge_page_revision",
                    )
                ]
            )
        assert before == after
        assert (await knowledge.get_page(owner, full.id)).revision == 1
        concurrent_pool = await asyncpg.create_pool(
            os.environ["CORE_DATABASE_URL"], min_size=2, max_size=2
        )
        assert concurrent_pool is not None
        try:
            concurrent = build_knowledge_service(concurrent_pool, storage)
            results = await asyncio.gather(
                *[
                    concurrent.create_task_from_page(
                        owner,
                        page.id,
                        command.model_copy(
                            update={"idempotency_key": uuid4(), "expected_revision": 2}
                        ),
                    )
                    for _ in range(2)
                ],
                return_exceptions=True,
            )
            assert (
                sum(
                    isinstance(r, Conflict) and r.code == "revision_conflict"
                    for r in results
                )
                == 1
            )
            assert sum(not isinstance(r, BaseException) for r in results) == 1
        finally:
            await concurrent_pool.close()
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM task WHERE list_id=$1", listing.id
                )
                == 3
            )
            await conn.execute(
                "INSERT INTO knowledge_page_member(page_id,user_id,access) VALUES ($1,$2,'editor')",
                page.id,
                reader_id,
            )
        try:
            await knowledge.create_task_from_page(
                reader,
                page.id,
                command.model_copy(
                    update={"idempotency_key": uuid4(), "expected_revision": 3}
                ),
            )
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Page editor bypassed list access")
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO task_list_member(list_id,user_id,access) VALUES ($1,$2,'editor')",
                listing.id,
                reader_id,
            )
        shared_command = command.model_copy(
            update={"idempotency_key": uuid4(), "expected_revision": 3}
        )
        await knowledge.create_task_from_page(reader, page.id, shared_command)
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM task_list_member WHERE list_id=$1 AND user_id=$2",
                listing.id,
                reader_id,
            )
        try:
            await knowledge.create_task_from_page(reader, page.id, shared_command)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Replay disclosed task after list access revocation")
        print(
            "PASS atomic page-task: one-slot pool, replay, live status, stale revision, two-connection race, document-limit rollback and independent ACL"
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
