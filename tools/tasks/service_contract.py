#!/usr/bin/env python3
"""Exercise direct TaskService calls with real PostgreSQL, including stale actors."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

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
    SetListMemberByEmail,
    SearchPage,
    ListQuery,
    TaskQuery,
    CreateEpic,
    Task,
    TaskSummary,
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
                f"{user_id}@example.org",
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
        assert getattr(first, "can_edit", None) is True, (
            "S1-A4: owner list projection must expose canEdit=true"
        )
        # Old deployed receipts predate the additive read projection. Replay
        # keeps its original revision and computes permission from live policy.
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE command_receipt SET result=jsonb_build_object('document', ((result->>'document')::jsonb - 'can_edit')::text) WHERE idempotency_key=$1",
                f"tasks:{owner_id}:tasks.list.created:{owner_id}:{command.idempotency_key}",
            )
        assert await service.create_list(owner, command) == first
        assert [
            item.user_id
            for item in (
                await service.list_assignees(owner, first.id, SearchPage())
            ).items
        ] == [owner_id]
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
        ).items[0].model_dump(include=set(Task.model_fields)) == task.model_dump()
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
        grant = SetListMemberByEmail.model_validate(
            dict(
                idempotency_key=uuid4(),
                expected_revision=1,
                email=reader.account.email.upper(),
                access="viewer",
            )
        )
        for invalid_email in ("missing@example.org", owner.account.email):
            try:
                await service.set_list_member_by_email(
                    owner,
                    first.id,
                    SetListMemberByEmail.model_validate(
                        dict(
                            idempotency_key=uuid4(),
                            expected_revision=1,
                            email=invalid_email,
                            access="viewer",
                        )
                    ),
                )
            except Conflict as error:
                assert error.code in ("list_member_invalid", "list_owner_protected")
            else:
                raise AssertionError("Invalid email membership accepted")
        granted, replayed_grant = await asyncio.gather(
            service.set_list_member_by_email(owner, first.id, grant),
            service.set_list_member_by_email(owner, first.id, grant),
        )
        assert granted == replayed_grant and granted.revision == 2
        assert (await service.get_list(reader, first.id)).id == first.id
        assert not (await service.get_list(reader, first.id)).can_edit
        reader_summary = (
            await service.list_tasks(reader, TaskQuery(include_deferred=True))
        ).items[0]
        assert not reader_summary.can_edit
        assert reader_summary.list_title == "Preparation"
        assert reader_summary.assignee_name == "Task proof"
        assert reader_summary.action_title is None and reader_summary.epic_title is None
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
        assert {
            item.user_id
            for item in (
                await service.list_assignees(reader, first.id, SearchPage())
            ).items
        } == {owner_id, reader_id}
        assert promoted.revision == 3
        assert (await service.get_list(reader, first.id)).can_edit
        assert all(
            item.can_edit
            for item in (
                await service.list_tasks(reader, TaskQuery(include_deferred=True))
            ).items
        )
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
        ).items[0].model_dump(include=set(Task.model_fields)) == changed.model_dump()
        assert not (
            await service.list_tasks(
                owner, TaskQuery(for_me=True, status="open", include_deferred=True)
            )
        ).items
        # S1-A2/A3: complete and undo full records, then reject stale undo after
        # a different real actor edits the title. Count exact receipts below.
        epic = await service.create_epic(
            owner, first.id, CreateEpic(idempotency_key=uuid4(), title="Supplies")
        )
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE task SET description='All fields retained',epic_id=$2,assignee_user_id=$3,due_at=$4,deferred_until=$5 WHERE id=$1",
                shared.id,
                epic.id,
                owner_id,
                now,
                now + timedelta(days=1),
            )
        original = await service.get_task(reader, shared.id)

        def status_command(current: Task, status: str) -> UpdateTask:
            return UpdateTask.model_validate(
                {
                    **current.model_dump(
                        include={
                            "title",
                            "description",
                            "epic_id",
                            "assignee_user_id",
                            "due_at",
                            "deferred_until",
                        }
                    ),
                    "status": status,
                    "expected_revision": current.revision,
                    "idempotency_key": uuid4(),
                }
            )

        complete = status_command(original, "done")
        completed, completed_replay = await asyncio.gather(
            service.update_task(reader, shared.id, complete),
            service.update_task(reader, shared.id, complete),
        )
        assert completed == completed_replay
        undo = status_command(completed, "open")
        undone = await service.update_task(reader, shared.id, undo)
        assert await service.update_task(reader, shared.id, undo) == undone
        preserved = set(Task.model_fields) - {"status", "revision", "updated_at"}
        for current in (completed, undone, await service.get_task(reader, shared.id)):
            assert current.model_dump(include=preserved) == original.model_dump(
                include=preserved
            )
        assert undone.revision == original.revision + 2 and undone.status == "open"
        completed = await service.update_task(
            reader, shared.id, status_command(undone, "done")
        )
        other_edit = status_command(completed, "done").model_copy(
            update={"title": "Other actor title"}
        )
        edited = await service.update_task(owner, shared.id, other_edit)
        try:
            await service.update_task(
                reader, shared.id, status_command(completed, "open")
            )
        except Conflict as error:
            assert error.code == "revision_conflict"
        else:
            raise AssertionError("S1-A3: stale undo overwrote other actor")
        assert await service.get_task(reader, shared.id) == edited
        async with pool.acquire() as conn:
            # Observe real SQL, no substitute connection or repository. Fixture
            # rows do not create domain receipts and are removed before totals.
            observed: list[str] = []
            repo = TaskService(AsyncpgTaskRepository(pool, connection=conn))

            def record_query(record: object) -> None:
                observed.append(getattr(record, "query"))

            with conn.query_logger(record_query):
                one = await repo.list_tasks(
                    owner, TaskQuery(list_id=first.id, include_deferred=True, limit=1)
                )
                await asyncio.sleep(0)
            one_count = len(observed)
            assert one_count > 0
            extra_ids = [uuid4() for _ in range(49)]
            await conn.executemany(
                "INSERT INTO task (id,list_id,title,created_by) VALUES ($1,$2,'Unassigned load proof',$3)",
                [(identifier, first.id, owner_id) for identifier in extra_ids],
            )
            observed.clear()
            with conn.query_logger(record_query):
                fifty = await repo.list_tasks(
                    owner, TaskQuery(list_id=first.id, include_deferred=True, limit=50)
                )
                await asyncio.sleep(0)
            assert len(fifty.items) == 50 and len(observed) == one_count, (
                one_count,
                len(observed),
            )
            assert one.items[0].list_title == "Preparation"
            assert any(item.epic_title == "Supplies" for item in fifty.items)
            assert all(
                item.assignee_name is None
                for item in fifty.items
                if item.assignee_user_id is None
            )
            await conn.execute("DELETE FROM task WHERE id=ANY($1::uuid[])", extra_ids)

        # S3-A1–A6: query every view in PostgreSQL before pagination. The fixture
        # contains more than two pages, boundary timestamps, duplicate section
        # titles and a deferred task whose due date must never be rewritten.
        berlin = ZoneInfo("Europe/Berlin")
        spring_start = datetime(2026, 3, 29, tzinfo=berlin).astimezone(timezone.utc)
        spring_end = datetime(2026, 3, 30, tzinfo=berlin).astimezone(timezone.utc)
        autumn_start = datetime(2026, 10, 25, tzinfo=berlin).astimezone(timezone.utc)
        autumn_end = datetime(2026, 10, 26, tzinfo=berlin).astimezone(timezone.utc)
        assert (spring_start.isoformat(), spring_end.isoformat()) == (
            "2026-03-28T23:00:00+00:00",
            "2026-03-29T22:00:00+00:00",
        )
        assert (autumn_start.isoformat(), autumn_end.isoformat()) == (
            "2026-10-24T22:00:00+00:00",
            "2026-10-25T23:00:00+00:00",
        )
        section_ids = [uuid4(), uuid4(), uuid4()]
        s3_ids = [uuid4() for _ in range(125)]
        created_base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        due_by_index: dict[int, datetime | None] = {
            75: spring_start + timedelta(hours=1),
            76: spring_end,
            77: spring_start,
            78: None,
            90: autumn_start,
            91: autumn_end - timedelta(seconds=1),
            92: autumn_end,
            110: now,
        }
        deferred_index = 110
        task_rows = []
        for index, task_id in enumerate(s3_ids):
            epic_id = (
                section_ids[0]
                if index % 4 == 0
                else section_ids[1]
                if index % 4 == 1
                else section_ids[2]
                if index % 4 == 2
                else None
            )
            title = (
                "S3 Treffer jenseits Seite eins"
                if index == 75
                else f"S3 Aufgabe {index:03d}"
            )
            task_rows.append(
                (
                    task_id,
                    first.id,
                    epic_id,
                    title,
                    owner_id,
                    due_by_index.get(
                        index,
                        datetime(2027, 1, 1, tzinfo=timezone.utc)
                        + timedelta(minutes=index),
                    ),
                    now + timedelta(days=1) if index == deferred_index else None,
                    created_base + timedelta(minutes=index),
                )
            )
        async with pool.acquire() as conn, conn.transaction():
            await conn.executemany(
                "INSERT INTO task_epic (id,list_id,title) VALUES ($1,$2,$3)",
                [
                    (section_ids[0], first.id, "Gleicher Abschnitt"),
                    (section_ids[1], first.id, "Gleicher Abschnitt"),
                    (section_ids[2], first.id, "Später Abschnitt"),
                ],
            )
            await conn.executemany(
                "INSERT INTO task (id,list_id,epic_id,title,created_by,due_at,deferred_until,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                task_rows,
            )

        async def collect(query: TaskQuery) -> list[TaskSummary]:
            items: list[TaskSummary] = []
            current = query
            while True:
                result = await service.list_tasks(owner, current)
                items.extend(result.items)
                if result.next_offset is None:
                    return items
                current = current.model_copy(update={"offset": result.next_offset})

        needle = await service.list_tasks(
            owner,
            TaskQuery(
                list_id=first.id,
                search="Treffer jenseits",
                deferred_state="all",
                limit=50,
            ),
        )
        assert [item.id for item in needle.items] == [s3_ids[75]]
        spring = await service.list_tasks(
            owner,
            TaskQuery(
                list_id=first.id,
                search="S3",
                due_from=spring_start,
                due_before=spring_end,
                deferred_state="all",
                limit=100,
            ),
        )
        assert {item.id for item in spring.items} == {s3_ids[75], s3_ids[77]}
        autumn = await service.list_tasks(
            owner,
            TaskQuery(
                list_id=first.id,
                search="S3",
                due_from=autumn_start,
                due_before=autumn_end,
                deferred_state="all",
                limit=100,
            ),
        )
        assert {item.id for item in autumn.items} == {s3_ids[90], s3_ids[91]}
        deferred = await service.list_tasks(
            owner,
            TaskQuery(
                list_id=first.id,
                search="S3 Aufgabe 110",
                deferred_state="deferred",
            ),
        )
        assert [item.id for item in deferred.items] == [s3_ids[deferred_index]]
        assert not (
            await service.list_tasks(
                owner,
                TaskQuery(
                    list_id=first.id,
                    search="S3 Aufgabe 110",
                    deferred_state="active",
                ),
            )
        ).items
        due_and_deferred = await service.list_tasks(
            owner,
            TaskQuery(
                list_id=first.id,
                search="S3 Aufgabe 110",
                due_from=now - timedelta(seconds=1),
                due_before=now + timedelta(seconds=1),
                deferred_state="all",
            ),
        )
        assert len(due_and_deferred.items) == 1
        assert due_and_deferred.items[0].due_at == now
        assert due_and_deferred.items[0].deferred_until == now + timedelta(days=1)
        assert not (
            await service.list_tasks(
                owner,
                TaskQuery(list_id=first.id, search="S3 Aufgabe 110"),
            )
        ).items
        assert [
            item.id
            for item in (
                await service.list_tasks(
                    owner,
                    TaskQuery(
                        list_id=first.id,
                        search="S3 Aufgabe 110",
                        include_deferred=True,
                    ),
                )
            ).items
        ] == [s3_ids[deferred_index]]
        section_items = await collect(
            TaskQuery(
                list_id=first.id,
                search="S3",
                deferred_state="all",
                sort="section",
                limit=50,
            )
        )
        assert len(section_items) == 125
        assert len({item.id for item in section_items}) == 125
        section_titles = {
            section_ids[0]: "Gleicher Abschnitt",
            section_ids[1]: "Gleicher Abschnitt",
            section_ids[2]: "Später Abschnitt",
        }
        expected_section_order = [
            row[0]
            for row in sorted(
                task_rows,
                key=lambda row: (
                    row[2] is None,
                    (section_titles[row[2]] if row[2] is not None else "").casefold(),
                    row[2] or section_ids[0],
                    row[7],
                    row[0],
                ),
            )
        ]
        assert [item.id for item in section_items] == expected_section_order
        due_items = await collect(
            TaskQuery(
                list_id=first.id,
                search="S3",
                deferred_state="all",
                sort="due",
                limit=50,
            )
        )
        assert due_items[-1].id == s3_ids[78]
        assert [item.id for item in due_items[:3]] == [
            s3_ids[77],
            s3_ids[75],
            s3_ids[76],
        ]
        for invalid_query in (
            {
                "due_from": spring_end,
                "due_before": spring_start,
            },
            {"deferred_state": "all", "include_deferred": False},
            {"deferred_state": "active", "include_deferred": True},
            {"sort": "section"},
        ):
            try:
                TaskQuery.model_validate(invalid_query)
            except ValidationError:
                pass
            else:
                raise AssertionError(f"Invalid S3 query accepted: {invalid_query}")
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM task WHERE id=ANY($1::uuid[])", s3_ids)
            await conn.execute(
                "DELETE FROM task_epic WHERE id=ANY($1::uuid[])", section_ids
            )
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
                == 12
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM command_receipt WHERE idempotency_key LIKE $1 OR idempotency_key LIKE $2",
                    f"tasks:{owner_id}:%",
                    f"tasks:{reader_id}:%",
                )
                == 12
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
            await conn.execute(
                "DELETE FROM task_epic WHERE list_id IN (SELECT id FROM task_list WHERE owner_user_id=$1)",
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
