#!/usr/bin/env python3
"""Shared and personal task ordering against real PostgreSQL."""

import asyncio
import os
from datetime import date, timedelta
from typing import Literal
from uuid import UUID, uuid4

import asyncpg
from pydantic import ValidationError

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.domain.identity import AccountStatus, IdentityPrincipal, UserAccount
from leonaid.modules.tasks.api import (
    CreateEpic,
    CreateList,
    CreateTask,
    MovePlacement,
    MoveTask,
    PlanQuery,
    SetListMember,
    SetTaskPlan,
    TaskQuery,
    TaskService,
    TaskSummary,
)
from leonaid.modules.tasks.planning import planning_day
from leonaid.modules.tasks.repository import AsyncpgTaskRepository


def actor(user_id: UUID) -> IdentityPrincipal:
    return IdentityPrincipal(
        UserAccount(
            user_id,
            f"{user_id}@example.org",
            "Ordering proof",
            AccountStatus.ACTIVE,
        ),
        frozenset(),
        (),
    )


def move(
    *,
    context: Literal["list", "personal"],
    order_revision: int,
    task_revision: int | None = None,
    plan_revision: int | None = None,
    target_epic_id: UUID | None = None,
    target_date: date | None = None,
    placement: MovePlacement,
) -> MoveTask:
    return MoveTask(
        idempotency_key=uuid4(),
        context=context,
        target_epic_id=target_epic_id,
        target_date=target_date,
        placement=placement,
        expected_task_revision=task_revision,
        expected_plan_revision=plan_revision,
        expected_order_revision=order_revision,
    )


async def all_manual(
    service: TaskService, principal: IdentityPrincipal, list_id: UUID
) -> tuple[list[TaskSummary], int]:
    items: list[TaskSummary] = []
    offset = 0
    revision = 0
    while True:
        page = await service.list_tasks(
            principal,
            TaskQuery(
                list_id=list_id,
                status="open",
                deferred_state="all",
                sort="manual",
                offset=offset,
                limit=50,
            ),
        )
        items.extend(page.items)
        assert page.order_revision is not None
        revision = page.order_revision
        if page.next_offset is None:
            return items, revision
        offset = page.next_offset


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
                "INSERT INTO user_account(id,email,display_name,status) VALUES($1,$2,'Ordering proof','active')",
                [(owner_id, owner.account.email), (reader_id, reader.account.email)],
            )
        listing = await service.create_list(
            owner, CreateList(idempotency_key=uuid4(), title="Ordering")
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
        epic_a = await service.create_epic(
            owner,
            listing.id,
            CreateEpic(idempotency_key=uuid4(), title="A section"),
        )
        epic_b = await service.create_epic(
            owner,
            listing.id,
            CreateEpic(idempotency_key=uuid4(), title="B empty section"),
        )
        tasks = [
            await service.create_task(
                owner,
                listing.id,
                CreateTask(
                    idempotency_key=uuid4(),
                    title=f"Ordered {index:03}",
                    epic_id=epic_a.id,
                ),
            )
            for index in range(120)
        ]
        initial, order_revision = await all_manual(service, owner, listing.id)
        assert [task.id for task in initial] == [task.id for task in tasks]
        async with pool.acquire() as conn:
            before_positions = dict(
                await conn.fetch(
                    "SELECT id,manual_position FROM task WHERE list_id=$1",
                    listing.id,
                )
            )
        first_move = move(
            context="list",
            order_revision=order_revision,
            task_revision=tasks[110].revision,
            target_epic_id=epic_a.id,
            placement=MovePlacement(before=tasks[5].id),
        )
        first_result = await service.move_task(owner, tasks[110].id, first_move)
        moved_items, order_revision = await all_manual(service, owner, listing.id)
        assert [task.id for task in moved_items][5] == tasks[110].id
        assert len({task.id for task in moved_items}) == 120
        async with pool.acquire() as conn:
            after_positions = dict(
                await conn.fetch(
                    "SELECT id,manual_position FROM task WHERE list_id=$1",
                    listing.id,
                )
            )
        assert {
            task_id
            for task_id in before_positions
            if before_positions[task_id] != after_positions[task_id]
        } == {tasks[110].id}
        assert first_result.order_revision == order_revision

        moved_task = await service.get_task(owner, tasks[0].id)
        empty_result = await service.move_task(
            owner,
            moved_task.id,
            move(
                context="list",
                order_revision=order_revision,
                task_revision=moved_task.revision,
                target_epic_id=epic_b.id,
                placement=MovePlacement(edge="start"),
            ),
        )
        order_revision = empty_result.order_revision
        assert (await service.get_task(owner, moved_task.id)).epic_id == epic_b.id

        other_list = await service.create_list(
            owner, CreateList(idempotency_key=uuid4(), title="Foreign order")
        )
        foreign = await service.create_task(
            owner,
            other_list.id,
            CreateTask(idempotency_key=uuid4(), title="Foreign neighbor"),
        )
        unchanged = await service.get_task(owner, tasks[1].id)
        try:
            await service.move_task(
                owner,
                unchanged.id,
                move(
                    context="list",
                    order_revision=order_revision,
                    task_revision=unchanged.revision,
                    target_epic_id=epic_a.id,
                    placement=MovePlacement(before=foreign.id),
                ),
            )
        except Conflict:
            pass
        else:
            raise AssertionError("Foreign ordering target accepted")
        assert await service.get_task(owner, unchanged.id) == unchanged

        left, right = await asyncio.gather(
            service.get_task(owner, tasks[1].id),
            service.get_task(owner, tasks[2].id),
        )
        left_move = move(
            context="list",
            order_revision=order_revision,
            task_revision=left.revision,
            target_epic_id=epic_a.id,
            placement=MovePlacement(edge="start"),
        )
        right_move = move(
            context="list",
            order_revision=order_revision,
            task_revision=right.revision,
            target_epic_id=epic_a.id,
            placement=MovePlacement(edge="start"),
        )
        concurrent = await asyncio.gather(
            service.move_task(owner, left.id, left_move),
            service.move_task(owner, right.id, right_move),
            return_exceptions=True,
        )
        winners = [result for result in concurrent if not isinstance(result, Exception)]
        losers = [result for result in concurrent if isinstance(result, Conflict)]
        assert len(winners) == len(losers) == 1
        winning_command = left_move if concurrent[0] in winners else right_move
        winning_task = left.id if concurrent[0] in winners else right.id
        assert (
            await service.move_task(owner, winning_task, winning_command) == winners[0]
        )

        personal_tasks = tasks[3:5]
        tomorrow = planning_day("Europe/Berlin")[0] + timedelta(days=1)
        for principal in (owner, reader):
            for task in personal_tasks:
                await service.set_task_plan(
                    principal,
                    task.id,
                    SetTaskPlan(
                        idempotency_key=uuid4(),
                        expected_revision=0,
                        state="scheduled",
                        planned_on=tomorrow,
                    ),
                )
        owner_plans = await service.list_task_plans(
            owner, PlanQuery(view="planned", time_zone="Europe/Berlin")
        )
        reader_plans = await service.list_task_plans(
            reader, PlanQuery(view="planned", time_zone="Europe/Berlin")
        )
        shared_before = await service.get_task(owner, personal_tasks[1].id)
        owner_move = move(
            context="personal",
            order_revision=owner_plans.order_revision,
            plan_revision=1,
            placement=MovePlacement(before=personal_tasks[0].id),
        )
        await service.move_task(owner, personal_tasks[1].id, owner_move)
        assert [
            task.id
            for task in (
                await service.list_task_plans(
                    owner, PlanQuery(view="planned", time_zone="Europe/Berlin")
                )
            ).items
        ][:2] == [personal_tasks[1].id, personal_tasks[0].id]
        assert [task.id for task in reader_plans.items][:2] == [
            personal_tasks[0].id,
            personal_tasks[1].id,
        ]
        await service.move_task(
            reader,
            personal_tasks[1].id,
            move(
                context="personal",
                order_revision=reader_plans.order_revision,
                plan_revision=1,
                placement=MovePlacement(before=personal_tasks[0].id),
            ),
        )
        assert await service.get_task(owner, personal_tasks[1].id) == shared_before
        try:
            await service.move_task(
                reader,
                personal_tasks[0].id,
                move(
                    context="list",
                    order_revision=order_revision + 1,
                    task_revision=personal_tasks[0].revision,
                    target_epic_id=epic_a.id,
                    placement=MovePlacement(edge="end"),
                ),
            )
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Viewer changed shared ordering")

        for invalid in (
            lambda: TaskQuery(sort="manual"),
            lambda: MovePlacement(before=tasks[0].id, edge="end"),
            lambda: move(
                context="personal",
                order_revision=1,
                task_revision=1,
                placement=MovePlacement(edge="end"),
            ),
        ):
            try:
                invalid()
            except ValidationError:
                pass
            else:
                raise AssertionError("Invalid ordering input accepted")
        print(
            "PASS: 120-row moves, empty and foreign targets, concurrency, replay, private order and viewer rights"
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
