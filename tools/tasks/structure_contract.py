#!/usr/bin/env python3
"""Priority, list tags and checklists with real PostgreSQL and current permissions."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import asyncpg
from pydantic import ValidationError

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.domain.identity import AccountStatus, IdentityPrincipal, UserAccount
from leonaid.modules.tasks.api import (
    ChecklistItem,
    CreateList,
    CreateTask,
    CreateTaskTag,
    SearchPage,
    SetListMember,
    SetTaskStructure,
    TaskQuery,
    TaskService,
)
from leonaid.modules.tasks.repository import AsyncpgTaskRepository


def principal(user_id: UUID) -> IdentityPrincipal:
    return IdentityPrincipal(
        UserAccount(
            user_id, f"{user_id}@example.org", "Structure proof", AccountStatus.ACTIVE
        ),
        frozenset(),
        (),
    )


async def expect(error: type[Exception], code: str | None, call: object) -> None:
    try:
        await call  # type: ignore[misc]
    except error as raised:
        if code is not None:
            assert getattr(raised, "code", None) == code, raised
    else:
        raise AssertionError(f"{error.__name__} {code} expected")


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=4
    )
    assert pool is not None
    owner_id, viewer_id, stranger_id = uuid4(), uuid4(), uuid4()
    owner, viewer, stranger = (
        principal(item) for item in (owner_id, viewer_id, stranger_id)
    )
    service = TaskService(AsyncpgTaskRepository(pool))
    try:
        async with pool.acquire() as conn:
            for user_id in (owner_id, viewer_id, stranger_id):
                await conn.execute(
                    "INSERT INTO user_account (id,email,display_name,status) "
                    "VALUES ($1,$2,'Structure proof','active')",
                    user_id,
                    f"{user_id}@example.org",
                )
        listing = await service.create_list(
            owner, CreateList(idempotency_key=uuid4(), title="Struktur")
        )
        other = await service.create_list(
            owner, CreateList(idempotency_key=uuid4(), title="Andere Liste")
        )
        listing = await service.set_list_member(
            owner,
            listing.id,
            SetListMember(
                idempotency_key=uuid4(),
                expected_revision=listing.revision,
                user_id=viewer_id,
                access="viewer",
            ),
        )
        task = await service.create_task(
            owner,
            listing.id,
            CreateTask(idempotency_key=uuid4(), title="Stände aufbauen"),
        )
        assert task.priority == "none" and task.tags == [] and task.checklist == []

        # Tags: replayable, unique per list after normalization.
        command = CreateTaskTag(idempotency_key=uuid4(), title="  Aufbau ")
        first, replay = await asyncio.gather(
            service.create_tag(owner, listing.id, command),
            service.create_tag(owner, listing.id, command),
        )
        assert first == replay and first.title == "Aufbau"
        await expect(
            Conflict,
            "task_tag_exists",
            service.create_tag(
                owner,
                listing.id,
                CreateTaskTag(idempotency_key=uuid4(), title="AUFBAU"),
            ),
        )
        foreign = await service.create_tag(
            owner, other.id, CreateTaskTag(idempotency_key=uuid4(), title="Fremd")
        )
        await expect(
            ResourceNotFound,
            None,
            service.create_tag(
                viewer, listing.id, CreateTaskTag(idempotency_key=uuid4(), title="Nein")
            ),
        )
        assert [
            tag.id
            for tag in (await service.list_tags(viewer, listing.id, SearchPage())).items
        ] == [first.id]
        await expect(
            ResourceNotFound,
            None,
            service.list_tags(stranger, listing.id, SearchPage()),
        )

        # Structure: one revision for priority, tags and checklist together.
        step = ChecklistItem(id=uuid4(), text="Tische holen", done=False)
        structure = SetTaskStructure(
            idempotency_key=uuid4(),
            expected_revision=task.revision,
            priority="high",
            tag_ids=[first.id],
            checklist=[step],
        )
        updated, again = await asyncio.gather(
            service.set_task_structure(owner, task.id, structure),
            service.set_task_structure(owner, task.id, structure),
        )
        assert updated == again
        assert updated.revision == task.revision + 1
        assert updated.priority == "high"
        assert [tag.id for tag in updated.tags] == [first.id]
        assert updated.checklist == [step]
        await expect(
            Conflict,
            "revision_conflict",
            service.set_task_structure(
                owner,
                task.id,
                structure.model_copy(update={"idempotency_key": uuid4()}),
            ),
        )
        await expect(
            Conflict,
            "task_tag_invalid",
            service.set_task_structure(
                owner,
                task.id,
                SetTaskStructure(
                    idempotency_key=uuid4(),
                    expected_revision=updated.revision,
                    priority="high",
                    tag_ids=[foreign.id],
                    checklist=[],
                ),
            ),
        )
        await expect(
            ResourceNotFound,
            None,
            service.set_task_structure(
                viewer,
                task.id,
                structure.model_copy(
                    update={
                        "idempotency_key": uuid4(),
                        "expected_revision": updated.revision,
                    }
                ),
            ),
        )
        for invalid in (
            {"tag_ids": [first.id, first.id]},
            {"checklist": [step, step]},
        ):
            try:
                SetTaskStructure.model_validate(
                    {
                        "idempotency_key": uuid4(),
                        "expected_revision": 1,
                        "priority": "none",
                        "tag_ids": [],
                        "checklist": [],
                        **invalid,
                    }
                )
            except ValidationError:
                pass
            else:
                raise AssertionError(f"Duplicate structure accepted: {invalid}")

        # Filters only return what the reader may see.
        high = await service.list_tasks(
            viewer, TaskQuery(list_id=listing.id, priority="high")
        )
        assert [item.id for item in high.items] == [task.id]
        tagged = await service.list_tasks(
            viewer, TaskQuery(list_id=listing.id, tag_id=first.id)
        )
        assert [item.id for item in tagged.items] == [task.id]
        hidden = await service.list_tasks(stranger, TaskQuery(tag_id=first.id))
        assert hidden.items == []

        # Removing a tag from the list removes it from its tasks.
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM task_tag WHERE id=$1", first.id)
        assert (await service.get_task(owner, task.id)).tags == []
    finally:
        await pool.close()
    print(
        "PASS: tags replay and stay unique per list, structure updates are one "
        "revision with conflict, foreign-tag and viewer denial, and filters "
        "respect access"
    )


if __name__ == "__main__":
    asyncio.run(main())
