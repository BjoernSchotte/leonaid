#!/usr/bin/env python3
"""Exercise direct TaskService calls with real PostgreSQL, including stale actors."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import asyncpg
from pydantic import ValidationError

from leonaid.application.errors import (
    ApplicationError,
    AuthenticationRequired,
    Conflict,
    ResourceNotFound,
)
from leonaid.domain.identity import AccountStatus, IdentityPrincipal, UserAccount
from leonaid.modules.tasks.api import CreateList, CreateTask, UpdateTask, TaskService
from leonaid.modules.tasks.repository import AsyncpgTaskRepository


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=4
    )
    assert pool is not None
    owner_id, reader_id = uuid4(), uuid4()
    actors = [
        IdentityPrincipal(
            UserAccount(
                user_id,
                f"{user_id}@leonaid.invalid",
                "Task proof",
                AccountStatus.ACTIVE,
            ),
            frozenset(),
            (),
        )
        for user_id in (owner_id, reader_id)
    ]
    owner, reader = actors
    service = TaskService(AsyncpgTaskRepository(pool))
    try:
        async with pool.acquire() as conn:
            for actor in actors:
                await conn.execute(
                    "INSERT INTO user_account (id,email,display_name,status) VALUES ($1,$2,'Task proof','active')",
                    actor.account.id,
                    actor.account.email,
                )
        command = CreateList(idempotency_key=uuid4(), title="  Preparation  ")
        first, replay = await asyncio.gather(
            service.create_list(owner, command), service.create_list(owner, command)
        )
        assert first == replay and first.title == "Preparation"
        try:
            await service.create_list(
                owner, command.model_copy(update={"title": "Different"})
            )
        except ApplicationError as error:
            assert error.code == "idempotency_conflict"
        else:
            raise AssertionError("Reused key accepted changed input")
        try:
            await service.get_list(reader, first.id)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Private list disclosed")
        now = datetime.now(timezone.utc)
        creation = CreateTask(
            idempotency_key=uuid4(),
            title="Prepare",
            assignee_user_id=owner_id,
            due_at=now - timedelta(days=1),
            deferred_until=now + timedelta(days=1),
        )
        task = await service.create_task(owner, first.id, creation)
        assert await service.create_task(owner, first.id, creation) == task
        assert creation.due_at is not None
        offset_creation = creation.model_copy(
            update={"due_at": creation.due_at.astimezone(timezone(timedelta(hours=2)))}
        )
        assert await service.create_task(owner, first.id, offset_creation) == task
        update = UpdateTask(
            idempotency_key=uuid4(),
            expected_revision=1,
            title="Ready",
            status="done",
            assignee_user_id=owner_id,
            due_at=creation.due_at,
            deferred_until=creation.deferred_until,
        )
        changed = await service.update_task(owner, task.id, update)
        assert changed.revision == 2 and changed.status == "done"
        assert (
            changed.due_at == creation.due_at
            and changed.deferred_until == creation.deferred_until
        )
        assert await service.update_task(owner, task.id, update) == changed
        try:
            await service.update_task(
                owner, task.id, update.model_copy(update={"idempotency_key": uuid4()})
            )
        except Conflict as error:
            assert error.code == "revision_conflict"
        else:
            raise AssertionError("Stale revision accepted")
        malformed = creation.model_copy(update={"title": " "})
        try:
            await service.create_task(owner, first.id, malformed)
        except ValidationError:
            pass
        else:
            raise AssertionError("Mutated input accepted")
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO task_list_member VALUES ($1,$2,'editor')",
                first.id,
                reader_id,
            )
        reader_command = CreateTask(idempotency_key=uuid4(), title="Shared task")
        shared = await service.create_task(reader, first.id, reader_command)
        assert await service.get_task(reader, shared.id) == shared
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM task_list_member WHERE list_id=$1 AND user_id=$2",
                first.id,
                reader_id,
            )
        try:
            await service.create_task(reader, first.id, reader_command)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Replay bypassed revoked access")
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_account SET status='suspended' WHERE id=$1", owner_id
            )
        try:
            await service.create_list(owner, command)
        except AuthenticationRequired:
            pass
        else:
            raise AssertionError("Stale principal bypassed suspension")
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM task WHERE list_id=$1", first.id
                )
                == 2
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM audit_event WHERE actor_user_id=ANY($1::uuid[]) AND event_type LIKE 'tasks.%'",
                    [owner_id, reader_id],
                )
                == 4
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM command_receipt WHERE idempotency_key LIKE $1 OR idempotency_key LIKE $2",
                    f"tasks:{owner_id}:%",
                    f"tasks:{reader_id}:%",
                )
                == 4
            )
        print(
            "PASS: direct operations, concurrent replay, conflict rollback, revisions, current permissions and suspension"
        )
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM task WHERE list_id IN (SELECT id FROM task_list WHERE owner_user_id=$1)",
                owner_id,
            )
            await conn.execute("DELETE FROM task_list WHERE owner_user_id=$1", owner_id)
            await conn.execute(
                "DELETE FROM audit_event WHERE actor_user_id=ANY($1::uuid[])",
                [owner_id, reader_id],
            )
            await conn.execute(
                "DELETE FROM command_receipt WHERE idempotency_key LIKE $1 OR idempotency_key LIKE $2",
                f"tasks:{owner_id}:%",
                f"tasks:{reader_id}:%",
            )
            await conn.execute(
                "DELETE FROM user_account WHERE id=ANY($1::uuid[])",
                [owner_id, reader_id],
            )
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
