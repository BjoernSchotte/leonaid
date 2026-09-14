#!/usr/bin/env python3
"""Personal planning isolation and concurrency against real PostgreSQL."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

import asyncpg
from pydantic import ValidationError

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.domain.identity import AccountStatus, IdentityPrincipal, UserAccount
from leonaid.modules.tasks.api import (
    CreateList,
    CreateTask,
    PlanQuery,
    SetListMember,
    SetTaskPlan,
    Task,
    TaskService,
    UpdateTask,
)
from leonaid.modules.tasks.planning import planning_day
from leonaid.modules.tasks.repository import AsyncpgTaskRepository


def actor(user_id: UUID) -> IdentityPrincipal:
    return IdentityPrincipal(
        UserAccount(
            user_id,
            f"{user_id}@example.org",
            "Planning proof",
            AccountStatus.ACTIVE,
        ),
        frozenset(),
        (),
    )


def update(task: Task, status: Literal["open", "done"]) -> UpdateTask:
    return UpdateTask(
        idempotency_key=uuid4(),
        expected_revision=task.revision,
        title=task.title,
        description=task.description,
        epic_id=task.epic_id,
        assignee_user_id=task.assignee_user_id,
        due_at=task.due_at,
        deferred_until=task.deferred_until,
        status=status,
    )


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=4
    )
    assert pool is not None
    owner_id, reader_id = uuid4(), uuid4()
    owner, reader = actor(owner_id), actor(reader_id)
    service = TaskService(AsyncpgTaskRepository(pool))
    try:
        async with pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO user_account(id,email,display_name,status) VALUES($1,$2,'Planning proof','active')",
                [(owner_id, owner.account.email), (reader_id, reader.account.email)],
            )
        listing = await service.create_list(
            owner, CreateList(idempotency_key=uuid4(), title="Personal planning")
        )
        listing = await service.set_list_member(
            owner,
            listing.id,
            SetListMember(
                idempotency_key=uuid4(),
                expected_revision=listing.revision,
                user_id=reader_id,
                access="viewer",
            ),
        )
        now = datetime.now(timezone.utc)
        shared = await service.create_task(
            owner,
            listing.id,
            CreateTask(
                idempotency_key=uuid4(),
                title="Shared planned task",
                assignee_user_id=owner_id,
                due_at=now - timedelta(hours=1),
                deferred_until=now + timedelta(days=1),
            ),
        )
        due_only = await service.create_task(
            owner,
            listing.id,
            CreateTask(
                idempotency_key=uuid4(),
                title="Due hint only",
                assignee_user_id=owner_id,
                due_at=now,
            ),
        )
        future_planned_due = await service.create_task(
            owner,
            listing.id,
            CreateTask(
                idempotency_key=uuid4(),
                title="Future plan with current due date",
                assignee_user_id=owner_id,
                due_at=now,
            ),
        )
        today, _, _ = planning_day("Europe/Berlin", now=now)
        owner_command = SetTaskPlan(
            idempotency_key=uuid4(),
            expected_revision=0,
            state="scheduled",
            planned_on=today - timedelta(days=1),
        )
        reader_command = SetTaskPlan(
            idempotency_key=uuid4(),
            expected_revision=0,
            state="scheduled",
            planned_on=today + timedelta(days=1),
        )
        owner_plan, reader_plan = await asyncio.gather(
            service.set_task_plan(owner, shared.id, owner_command),
            service.set_task_plan(reader, shared.id, reader_command),
        )
        future_plan = await service.set_task_plan(
            owner,
            future_planned_due.id,
            SetTaskPlan(
                idempotency_key=uuid4(),
                expected_revision=0,
                state="scheduled",
                planned_on=today + timedelta(days=1),
            ),
        )
        assert owner_plan.planned_on != reader_plan.planned_on
        assert (await service.get_task_plan(owner, shared.id)) == owner_plan
        assert (await service.get_task_plan(reader, shared.id)) == reader_plan
        reader_planned = await service.list_task_plans(
            reader, PlanQuery(view="planned", time_zone="Europe/Berlin")
        )
        assert reader_planned.items[0].plan_source == "planned"
        unchanged = await service.get_task(owner, shared.id)
        assert unchanged.model_dump() == shared.model_dump()

        today_query = PlanQuery(view="today", time_zone="Europe/Berlin")
        owner_today = await service.list_task_plans(owner, today_query)
        assert [item.id for item in owner_today.items].count(shared.id) == 1
        assert [item.id for item in owner_today.items].count(due_only.id) == 1
        assert (
            next(item for item in owner_today.items if item.id == shared.id).plan_source
            == "planned"
        )
        assert (
            next(
                item for item in owner_today.items if item.id == due_only.id
            ).plan_source
            == "due"
        )
        assert (
            next(
                item for item in owner_today.items if item.id == future_planned_due.id
            ).plan_source
            == "due"
        )
        assert (
            next(
                item
                for item in (
                    await service.list_task_plans(
                        owner,
                        PlanQuery(view="planned", time_zone="Europe/Berlin"),
                    )
                ).items
                if item.id == future_planned_due.id
            ).personal_plan
            == future_plan
        )
        async with pool.acquire() as conn:
            assert not await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM task_personal_plan WHERE task_id=$1)",
                due_only.id,
            )

        done = await service.update_task(owner, shared.id, update(shared, "done"))
        assert shared.id not in {
            item.id
            for item in (await service.list_task_plans(owner, today_query)).items
        }
        reopened = await service.update_task(owner, shared.id, update(done, "open"))
        restored = await service.list_task_plans(owner, today_query)
        assert shared.id in {item.id for item in restored.items}
        assert (
            await service.get_task_plan(owner, shared.id)
        ).planned_on == owner_plan.planned_on

        try:
            await service.update_task(reader, shared.id, update(reopened, "done"))
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Viewer changed shared task state")
        listing = await service.set_list_member(
            owner,
            listing.id,
            SetListMember(
                idempotency_key=uuid4(),
                expected_revision=listing.revision,
                user_id=reader_id,
                access=None,
            ),
        )
        assert not (
            await service.list_task_plans(
                reader, PlanQuery(view="planned", time_zone="Europe/Berlin")
            )
        ).items
        try:
            await service.get_task_plan(reader, shared.id)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Revoked reader recovered private task data")
        try:
            await service.set_task_plan(reader, shared.id, reader_command)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Revoked reader replayed private task data")

        unplan = SetTaskPlan(
            idempotency_key=uuid4(),
            expected_revision=owner_plan.revision,
            state="unplanned",
            planned_on=None,
        )
        unplanned = await service.set_task_plan(owner, shared.id, unplan)
        assert unplanned == await service.set_task_plan(owner, shared.id, unplan)
        try:
            await service.set_task_plan(
                owner,
                shared.id,
                owner_command.model_copy(update={"idempotency_key": uuid4()}),
            )
        except Conflict:
            pass
        else:
            raise AssertionError("Stale plan revision bypassed unplanned marker")
        assert (await service.get_task_plan(owner, shared.id)).revision == 2

        local_days = {
            zone: planning_day(zone, now=now)[0]
            for zone in ("Pacific/Honolulu", "Pacific/Kiritimati")
        }
        early_zone = min(local_days, key=lambda zone: local_days[zone])
        late_zone = max(local_days, key=lambda zone: local_days[zone])
        assert local_days[early_zone] < local_days[late_zone]
        zoned = await service.create_task(
            owner,
            listing.id,
            CreateTask(idempotency_key=uuid4(), title="Zone boundary"),
        )
        zoned_plan = await service.set_task_plan(
            owner,
            zoned.id,
            SetTaskPlan(
                idempotency_key=uuid4(),
                expected_revision=0,
                state="scheduled",
                planned_on=local_days[late_zone],
            ),
        )
        assert zoned.id not in {
            item.id
            for item in (
                await service.list_task_plans(
                    owner, PlanQuery(view="today", time_zone=early_zone)
                )
            ).items
        }
        assert zoned.id in {
            item.id
            for item in (
                await service.list_task_plans(
                    owner, PlanQuery(view="today", time_zone=late_zone)
                )
            ).items
        }
        assert (
            await service.get_task_plan(owner, zoned.id)
        ).planned_on == zoned_plan.planned_on
        for invalid in (
            lambda: PlanQuery(view="today", time_zone="Mars/Olympus"),
            lambda: SetTaskPlan(
                idempotency_key=uuid4(),
                expected_revision=0,
                state="scheduled",
            ),
            lambda: SetTaskPlan(
                idempotency_key=uuid4(),
                expected_revision=0,
                state="someday",
                planned_on=today,
            ),
        ):
            try:
                invalid()
            except ValidationError:
                pass
            else:
                raise AssertionError("Invalid planning input accepted")
        print(
            "PASS: private planning, due hints, rollover, access, ABA, idempotency and time zones"
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
