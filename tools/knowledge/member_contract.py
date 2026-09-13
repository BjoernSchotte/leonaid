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
)
from leonaid.bootstrap.api import build_knowledge_service
from leonaid.domain.identity import IdentityPrincipal, UserAccount, AccountStatus
from leonaid.modules.knowledge.api import (
    CreatePage,
    UpdatePage,
    MemberQuery,
    SetPageMember,
    SetPageMemberByEmail,
)


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
    try:
        async with pool.acquire() as conn:
            for actor in actors:
                await conn.execute(
                    "INSERT INTO user_account(id,email,display_name,status) VALUES ($1,$2,'Knowledge proof','active')",
                    actor.account.id,
                    actor.account.email,
                )
        page = await knowledge.create_page(
            owner, CreatePage(idempotency_key=uuid4(), title="Shared page")
        )
        members = await knowledge.list_members(owner, page.id, MemberQuery())
        assert members.access_revision == 1 and not members.items
        rights = await knowledge.get_permissions(owner, page.id)
        assert rights.can_edit and rights.can_manage
        grant = SetPageMemberByEmail(
            idempotency_key=uuid4(),
            expected_access_revision=1,
            email=reader.account.email.upper(),
            access="viewer",
        )
        result = await knowledge.set_page_member_by_email(owner, page.id, grant)
        assert result.access_revision == 2
        assert await knowledge.set_page_member_by_email(owner, page.id, grant) == result
        assert (await knowledge.get_page(reader, page.id)).revision == 1
        rights = await knowledge.get_permissions(reader, page.id)
        assert not rights.can_edit and not rights.can_manage
        members = await knowledge.list_members(
            owner, page.id, MemberQuery(search="KNOWLEDGE")
        )
        assert (
            members.items[0].user_id == reader_id
            and members.items[0].access == "viewer"
        )
        for operation in (
            knowledge.list_members(reader, page.id, MemberQuery()),
            knowledge.set_page_member(
                reader,
                page.id,
                SetPageMember(
                    idempotency_key=uuid4(),
                    expected_access_revision=2,
                    user_id=reader_id,
                    access="editor",
                ),
            ),
        ):
            try:
                await operation
            except ResourceNotFound:
                pass
            else:
                raise AssertionError("Viewer managed access")
        for target, code in (
            (owner_id, "page_owner_protected"),
            (uuid4(), "page_member_invalid"),
        ):
            try:
                await knowledge.set_page_member(
                    owner,
                    page.id,
                    SetPageMember(
                        idempotency_key=uuid4(),
                        expected_access_revision=2,
                        user_id=target,
                        access="viewer",
                    ),
                )
            except Conflict as error:
                assert error.code == code
            else:
                raise AssertionError("Invalid member accepted")
        promote = SetPageMember(
            idempotency_key=uuid4(),
            expected_access_revision=2,
            user_id=reader_id,
            access="editor",
        )
        result = await knowledge.set_page_member(owner, page.id, promote)
        assert result.access_revision == 3
        rights = await knowledge.get_permissions(reader, page.id)
        assert rights.can_edit and not rights.can_manage
        await knowledge.update_page(
            reader,
            page.id,
            UpdatePage(
                idempotency_key=uuid4(),
                expected_revision=1,
                title="Editor content",
                content=page.content,
            ),
        )
        assert (
            await knowledge.list_members(owner, page.id, MemberQuery())
        ).access_revision == 3
        try:
            await knowledge.list_members(reader, page.id, MemberQuery())
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Editor managed access")
        concurrent_pool = await asyncpg.create_pool(
            os.environ["CORE_DATABASE_URL"], min_size=2, max_size=2
        )
        assert concurrent_pool is not None
        try:
            concurrent = build_knowledge_service(concurrent_pool)
            results = await asyncio.gather(
                *[
                    concurrent.set_page_member(
                        owner,
                        page.id,
                        SetPageMember(
                            idempotency_key=uuid4(),
                            expected_access_revision=3,
                            user_id=reader_id,
                            access="viewer",
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
        await knowledge.set_page_member(
            owner,
            page.id,
            SetPageMember(
                idempotency_key=uuid4(),
                expected_access_revision=4,
                user_id=reader_id,
                access=None,
            ),
        )
        try:
            await knowledge.get_permissions(reader, page.id)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Removed member read content")
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
                    "SELECT access_revision FROM knowledge_page WHERE id=$1", page.id
                )
                == 5
            )
        print(
            "PASS knowledge members: email, manager rights, owner protection, independent revisions, concurrent conflict, removal"
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
