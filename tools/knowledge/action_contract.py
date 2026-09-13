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
from leonaid.bootstrap.api import build_knowledge_service
from leonaid.modules.knowledge.api import CreatePage, UpdatePage, PageQuery


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
    service = build_knowledge_service(pool)
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
                    "INSERT INTO charity_action (id,carrier_name,name,purpose,status,starts_on,ends_on,archive_slug) VALUES ($1,'Synthetic','Knowledge matrix','Proof','draft','2026-01-01','2026-12-31',$2)",
                    action_id,
                    f"knowledge-matrix-{action_id}",
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
        create = CreatePage(
            idempotency_key=uuid4(), title="Action page", action_id=actions[0]
        )
        page = await service.create_page(owner, create)
        for name in (
            "owner",
            "manager",
            "acquirer",
            "finance_reader",
            "driver",
            "global",
        ):
            assert (await service.get_page(actors[name], page.id)).id == page.id
            assert [
                p.id
                for p in (
                    await service.list_pages(
                        actors[name], PageQuery(action_id=actions[0])
                    )
                ).items
            ] == [page.id]
        for name in ("expired", "future", "other", "outsider"):
            await rejected(service.get_page(actors[name], page.id), "not_found")
            assert not (
                await service.list_pages(actors[name], PageQuery(action_id=actions[0]))
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
                service.create_page(
                    actors[name],
                    CreatePage(
                        idempotency_key=uuid4(), title="Denied", action_id=actions[0]
                    ),
                ),
                "not_found",
            )
            await rejected(
                service.update_page(
                    actors[name],
                    page.id,
                    UpdatePage(
                        idempotency_key=uuid4(),
                        expected_revision=1,
                        title="Denied",
                        content=page.content,
                    ),
                ),
                "not_found",
            )
        for name in ("manager", "global"):
            page = await service.update_page(
                actors[name],
                page.id,
                UpdatePage(
                    idempotency_key=uuid4(),
                    expected_revision=page.revision,
                    title=name,
                    content=page.content,
                ),
            )
        async with pool.acquire() as conn:
            # Direct database fixtures exercise read/write enforcement; no membership API is claimed.
            for name in ("acquirer", "outsider"):
                await conn.execute(
                    "INSERT INTO knowledge_page_member(page_id,user_id,access) VALUES ($1,$2,'editor')",
                    page.id,
                    actors[name].account.id,
                )
        await rejected(service.get_page(actors["outsider"], page.id), "not_found")
        edit = UpdatePage(
            idempotency_key=uuid4(),
            expected_revision=page.revision,
            title="Explicit editor",
            content=page.content,
        )
        page = await service.update_page(actors["acquirer"], page.id, edit)
        assert await service.update_page(actors["acquirer"], page.id, edit) == page
        private = await service.create_page(
            owner, CreatePage(idempotency_key=uuid4(), title="Standalone")
        )
        await rejected(service.get_page(actors["global"], private.id), "not_found")
        assert not (
            await service.list_pages(actors["global"], PageQuery(search="Standalone"))
        ).items
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
            await rejected(service.get_page(actors[name], page.id), "not_found")
            assert not (
                await service.list_pages(actors[name], PageQuery(action_id=actions[0]))
            ).items
        await rejected(service.create_page(owner, create), "not_found")
        await rejected(
            service.update_page(actors["acquirer"], page.id, edit), "not_found"
        )
        assert (await service.get_page(owner, private.id)).id == private.id
        assert (
            await service.get_page(actors["manager"], page.id)
        ).revision == page.revision
        print(
            "PASS knowledge action roles, isolation, explicit editor, standalone privacy, stale global role and revoked owner/editor replay"
        )
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM knowledge_page WHERE owner_user_id=ANY($1::uuid[])", users
            )
            await conn.execute(
                "DELETE FROM audit_event WHERE actor_user_id=ANY($1::uuid[])", users
            )
            for user_id in users:
                await conn.execute(
                    "DELETE FROM command_receipt WHERE idempotency_key LIKE $1",
                    f"knowledge:{user_id}:%",
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
