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
    PermissionDenied,
    AuthenticationRequired,
    Conflict,
    ResourceNotFound,
)
from leonaid.domain.identity import AccountStatus, IdentityPrincipal, UserAccount
from leonaid.modules.tasks.api import (
    SetListMember,
    SearchPage,
    ListQuery,
    TaskQuery,
    CreateList,
    CreateTask,
    UpdateTask,
    TaskService,
)
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
        assert (await service.list_lists(owner, ListQuery())).items == [first]
        assert not (
            await service.list_lists(reader, ListQuery(search="Preparation"))
        ).items
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
        assert not (await service.list_tasks(owner, TaskQuery(for_me=True))).items
        assert (
            await service.list_tasks(
                owner, TaskQuery(for_me=True, include_deferred=True)
            )
        ).items == [task]
        assert not (
            await service.list_tasks(
                reader, TaskQuery(search="Prepare", include_deferred=True)
            )
        ).items
        assert not (
            await service.list_tasks(
                owner, TaskQuery(search="%", include_deferred=True)
            )
        ).items
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE task SET deferred_until=now() WHERE id=$1", task.id
            )
        visible = (await service.list_tasks(owner, TaskQuery(for_me=True))).items
        assert (
            len(visible) == 1
            and visible[0].id == task.id
            and visible[0].due_at == creation.due_at
        )
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE task SET deferred_until=$2 WHERE id=$1",
                task.id,
                creation.deferred_until,
            )
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
        protected = SetListMember(
            idempotency_key=uuid4(), expected_revision=1, user_id=owner_id, access=None
        )
        try:
            await service.set_list_member(owner, first.id, protected)
        except Conflict as error:
            assert error.code == "list_owner_protected"
        else:
            raise AssertionError("Owner access could be removed")
        grant = SetListMember(
            idempotency_key=uuid4(),
            expected_revision=1,
            user_id=reader_id,
            access="viewer",
        )
        granted, replayed_grant = await asyncio.gather(
            service.set_list_member(owner, first.id, grant),
            service.set_list_member(owner, first.id, grant),
        )
        assert granted == replayed_grant and granted.revision == 2
        assert (await service.get_list(reader, first.id)).id == first.id
        members = await service.list_members(owner, first.id, SearchPage())
        assert (
            members.revision == 2
            and members.items[0].user_id == reader_id
            and members.items[0].access == "viewer"
        )
        try:
            await service.create_task(
                reader, first.id, CreateTask(idempotency_key=uuid4(), title="Forbidden")
            )
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Viewer could write")
        promotion = SetListMember(
            idempotency_key=uuid4(),
            expected_revision=2,
            user_id=reader_id,
            access="editor",
        )
        try:
            await service.set_list_member(reader, first.id, promotion)
        except PermissionDenied:
            pass
        else:
            raise AssertionError("Member could promote itself")
        try:
            await service.set_list_member(
                owner, first.id, promotion.model_copy(update={"expected_revision": 1})
            )
        except Conflict as error:
            assert error.code == "revision_conflict"
        else:
            raise AssertionError("Stale rights update accepted")
        promoted = await service.set_list_member(owner, first.id, promotion)
        assert promoted.revision == 3
        reader_command = CreateTask(idempotency_key=uuid4(), title="Shared task")
        shared = await service.create_task(reader, first.id, reader_command)
        assert await service.get_task(reader, shared.id) == shared
        page = await service.list_tasks(
            reader, TaskQuery(include_deferred=True, limit=1)
        )
        assert len(page.items) == 1 and page.next_offset == 1
        following = await service.list_tasks(
            reader, TaskQuery(include_deferred=True, limit=1, offset=page.next_offset)
        )
        assert len(following.items) == 1 and following.next_offset is None
        assert page.items[0].id != following.items[0].id
        assert (
            await service.list_tasks(
                owner, TaskQuery(for_me=True, status="done", include_deferred=True)
            )
        ).items == [changed]
        assert not (
            await service.list_tasks(
                owner, TaskQuery(for_me=True, status="open", include_deferred=True)
            )
        ).items
        revoked = await service.set_list_member(
            owner,
            first.id,
            SetListMember(
                idempotency_key=uuid4(),
                expected_revision=3,
                user_id=reader_id,
                access=None,
            ),
        )
        assert revoked.revision == 4
        assert not (
            await service.list_tasks(reader, TaskQuery(include_deferred=True))
        ).items
        assert not (await service.list_lists(reader, ListQuery())).items
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
                == 7
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM command_receipt WHERE idempotency_key LIKE $1 OR idempotency_key LIKE $2",
                    f"tasks:{owner_id}:%",
                    f"tasks:{reader_id}:%",
                )
                == 7
            )
        print(
            "PASS: direct operations, concurrent replay, conflict rollback, revisions, current permissions, suspension, authorized search, pagination and database-time deferral"
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
