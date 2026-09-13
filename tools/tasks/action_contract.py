#!/usr/bin/env python3
"""Current action roles, cross-action isolation and revocation on real PostgreSQL."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable
from typing import Any
from uuid import uuid4

import asyncpg

from leonaid.application.errors import ApplicationError
from leonaid.domain.identity import (
    AccountStatus,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)
from leonaid.modules.tasks.api import (
    CreateEpic,
    CreateList,
    CreateTask,
    SetListMember,
    TaskQuery,
    ListQuery,
    SearchPage,
    TaskService,
)
from leonaid.modules.tasks.repository import AsyncpgTaskRepository


async def rejected(operation: Awaitable[Any], code: str) -> None:
    try:
        await operation
    except ApplicationError as error:
        assert error.code == code, (error.code, code)
    else:
        raise AssertionError(f"Expected {code}")


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=4
    )
    assert pool is not None
    names = (
        "owner",
        "manager",
        "acquirer",
        "finance_reader",
        "driver",
        "expired",
        "future",
        "other",
        "global",
        "outsider",
    )
    actors = {
        name: IdentityPrincipal(
            UserAccount(
                uuid4(), f"{uuid4()}@leonaid.invalid", name, AccountStatus.ACTIVE
            ),
            frozenset(),
            (),
        )
        for name in names
    }
    # A forged/stale in-memory role must not grant access missing from PostgreSQL.
    outsider = actors["outsider"]
    actors["outsider"] = IdentityPrincipal(
        outsider.account, frozenset({GlobalRole.SYSTEM_ADMIN}), ()
    )
    users = [actor.account.id for actor in actors.values()]
    actions = [uuid4(), uuid4()]
    service = TaskService(AsyncpgTaskRepository(pool))
    try:
        async with pool.acquire() as conn:
            for actor in actors.values():
                await conn.execute(
                    "INSERT INTO user_account (id,email,display_name,status) VALUES ($1,$2,$3,'active')",
                    actor.account.id,
                    actor.account.email,
                    actor.account.display_name,
                )
            for action_id in actions:
                await conn.execute(
                    "INSERT INTO charity_action (id,carrier_name,name,purpose,status,starts_on,ends_on,archive_slug) VALUES ($1,'Synthetic','Task matrix','Proof','draft','2026-01-01','2026-12-31',$2)",
                    action_id,
                    f"task-matrix-{action_id}",
                )
            for name in (
                "owner",
                "manager",
                "acquirer",
                "finance_reader",
                "driver",
                "other",
            ):
                role = (
                    "charity_admin" if name in ("owner", "manager", "other") else name
                )
                await conn.execute(
                    "INSERT INTO action_membership (id,action_id,user_id,role) VALUES ($1,$2,$3,$4)",
                    uuid4(),
                    actions[1] if name == "other" else actions[0],
                    actors[name].account.id,
                    role,
                )
            await conn.execute(
                "INSERT INTO action_membership (id,action_id,user_id,role,active_from,active_until) VALUES ($1,$2,$3,'acquirer',now()-interval '2 days',now()-interval '1 day')",
                uuid4(),
                actions[0],
                actors["expired"].account.id,
            )
            await conn.execute(
                "INSERT INTO action_membership (id,action_id,user_id,role,active_from) VALUES ($1,$2,$3,'acquirer',now()+interval '1 day')",
                uuid4(),
                actions[0],
                actors["future"].account.id,
            )
            await conn.execute(
                "INSERT INTO user_global_role (user_id,role) VALUES ($1,'system_admin')",
                actors["global"].account.id,
            )
        owner = actors["owner"]
        listing = await service.create_list(
            owner,
            CreateList(
                idempotency_key=uuid4(), title="Action work", action_id=actions[0]
            ),
        )
        task = await service.create_task(
            owner,
            listing.id,
            CreateTask(
                idempotency_key=uuid4(),
                title="Scoped task",
                assignee_user_id=actors["acquirer"].account.id,
            ),
        )
        for name in (
            "owner",
            "manager",
            "acquirer",
            "finance_reader",
            "driver",
            "global",
        ):
            assert (await service.get_task(actors[name], task.id)).id == task.id
            assert [
                item.id
                for item in (await service.list_tasks(actors[name], TaskQuery())).items
            ] == [task.id]
        for name in ("expired", "future", "other", "outsider"):
            await rejected(service.get_task(actors[name], task.id), "not_found")
            assert not (
                await service.list_tasks(actors[name], TaskQuery(search="Scoped"))
            ).items
            assert not (
                await service.list_lists(actors[name], ListQuery(action_id=actions[0]))
            ).items
        for name in (
            "acquirer",
            "finance_reader",
            "driver",
            "expired",
            "future",
            "other",
            "outsider",
        ):
            await rejected(
                service.create_task(
                    actors[name],
                    listing.id,
                    CreateTask(idempotency_key=uuid4(), title="Denied"),
                ),
                "not_found",
            )
            await rejected(
                service.create_list(
                    actors[name],
                    CreateList(
                        idempotency_key=uuid4(), title="Denied", action_id=actions[0]
                    ),
                ),
                "permission_denied",
            )
        await service.create_task(
            actors["global"],
            listing.id,
            CreateTask(idempotency_key=uuid4(), title="Admin task"),
        )
        await service.create_epic(
            actors["manager"],
            listing.id,
            CreateEpic(idempotency_key=uuid4(), title="Manager epic"),
        )
        await rejected(
            service.set_list_member(
                owner,
                listing.id,
                SetListMember(
                    idempotency_key=uuid4(),
                    expected_revision=1,
                    user_id=actors["outsider"].account.id,
                    access="editor",
                ),
            ),
            "list_member_invalid",
        )
        await service.set_list_member(
            actors["manager"],
            listing.id,
            SetListMember(
                idempotency_key=uuid4(),
                expected_revision=1,
                user_id=actors["acquirer"].account.id,
                access="editor",
            ),
        )
        command = CreateTask(idempotency_key=uuid4(), title="Granted task")
        await service.create_task(actors["acquirer"], listing.id, command)
        foreign_list = await service.create_list(
            actors["other"],
            CreateList(
                idempotency_key=uuid4(), title="Other action", action_id=actions[1]
            ),
        )
        foreign_epic = await service.create_epic(
            actors["other"],
            foreign_list.id,
            CreateEpic(idempotency_key=uuid4(), title="Other epic"),
        )
        await rejected(
            service.create_task(
                owner,
                listing.id,
                CreateTask(
                    idempotency_key=uuid4(), title="Wrong epic", epic_id=foreign_epic.id
                ),
            ),
            "task_epic_invalid",
        )
        await rejected(
            service.create_task(
                owner,
                listing.id,
                CreateTask(
                    idempotency_key=uuid4(),
                    title="Wrong assignee",
                    assignee_user_id=actors["other"].account.id,
                ),
            ),
            "not_found",
        )
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE action_membership SET active_until=now() WHERE action_id=$1 AND user_id=ANY($2::uuid[])",
                actions[0],
                [owner.account.id, actors["acquirer"].account.id],
            )
            await conn.execute(
                "DELETE FROM user_global_role WHERE user_id=$1",
                actors["global"].account.id,
            )
        for name in ("owner", "acquirer", "global"):
            await rejected(service.get_task(actors[name], task.id), "not_found")
            assert not (
                await service.list_tasks(actors[name], TaskQuery(for_me=True))
            ).items
        await rejected(
            service.create_task(actors["acquirer"], listing.id, command), "not_found"
        )
        await rejected(
            service.list_members(owner, listing.id, SearchPage()), "not_found"
        )
        assert (
            await service.list_members(actors["manager"], listing.id, SearchPage())
        ).items[0].user_id == actors["acquirer"].account.id
        print(
            "PASS: ten identities, four action roles, two actions, current/expired/future membership, global-role revocation, owner revocation, reference isolation and denied replay"
        )
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM task WHERE list_id IN (SELECT id FROM task_list WHERE action_id=ANY($1::uuid[]))",
                actions,
            )
            await conn.execute(
                "DELETE FROM task_epic WHERE list_id IN (SELECT id FROM task_list WHERE action_id=ANY($1::uuid[]))",
                actions,
            )
            await conn.execute(
                "DELETE FROM task_list WHERE action_id=ANY($1::uuid[])", actions
            )
            await conn.execute(
                "DELETE FROM audit_event WHERE actor_user_id=ANY($1::uuid[])", users
            )
            for user_id in users:
                await conn.execute(
                    "DELETE FROM command_receipt WHERE idempotency_key LIKE $1",
                    f"tasks:{user_id}:%",
                )
            await conn.execute(
                "DELETE FROM charity_action WHERE id=ANY($1::uuid[])", actions
            )
            await conn.execute(
                "DELETE FROM action_archive_slug_reservation WHERE action_id=ANY($1::uuid[])",
                actions,
            )
            await conn.execute(
                "DELETE FROM user_account WHERE id=ANY($1::uuid[])", users
            )
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
