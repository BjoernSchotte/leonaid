#!/usr/bin/env python3
"""Real PostgreSQL and FastAPI proof for independently authorized Inbox task links."""

import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import asyncpg
import httpx

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.bootstrap.api import build_inbox_service, build_task_service
from leonaid.configuration import Settings
from leonaid.domain.identity import AccountStatus, IdentityPrincipal, UserAccount
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)
from leonaid.entrypoints.fastapi.platform import create_app
from leonaid.modules.inbox.api import SetTaskReference, SubmitCase, UpdateCase
from leonaid.modules.tasks.api import CreateList, CreateTask, SetListMember, UpdateTask


async def main() -> None:
    settings = Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-http-proof-secret-only-32-characters",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-http-proof-encryption-32-characters",
            "LEONAID_PUBLIC_BASE_URL": "https://inbox.leonaid.invalid",
            "LEONAID_ALLOWED_ORIGINS": "https://inbox.leonaid.invalid",
            "TWENTY_BASE_URL": "http://127.0.0.1:9",
            "TWENTY_HEALTH_URL": "http://127.0.0.1:9/health",
            "RUSTFS_HEALTH_URL": "http://127.0.0.1:9/health",
            "OBJECT_STORAGE_ENDPOINT_URL": "http://127.0.0.1:9",
            "OBJECT_STORAGE_BUCKET": "leonaid",
            "OBJECT_STORAGE_ACCESS_KEY": "synthetic-proof",
            "OBJECT_STORAGE_SECRET_KEY": "synthetic-proof",
        }
    )
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=1
    )
    assert pool is not None
    inbox, tasks = build_inbox_service(pool), build_task_service(pool)
    users = [uuid4() for _ in range(3)]
    actors = [
        IdentityPrincipal(
            UserAccount(
                user, f"{user}@example.org", "Inbox link proof", AccountStatus.ACTIVE
            ),
            frozenset(),
            (),
        )
        for user in users
    ]
    owner, assigned, outsider = actors
    token = uuid4().hex + uuid4().hex
    command = SubmitCase(
        idempotency_key=uuid4(),
        subject="Linked task",
        message="Synthetic",
        given_name="Test",
        family_name="Person",
        email="test@example.org",
    )
    case_id = None
    try:
        async with pool.acquire() as conn:
            for actor in actors:
                await conn.execute(
                    "INSERT INTO user_account(id,email,display_name,status) VALUES($1,$2,'Inbox link proof','active')",
                    actor.account.id,
                    actor.account.email,
                )
            await conn.execute(
                "INSERT INTO user_global_role(user_id,role) VALUES($1,'system_admin')",
                users[0],
            )
            now = datetime.now(timezone.utc)
            await conn.execute(
                "INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,device_hint,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$5,'Inbox links',$5,$5)",
                uuid4(),
                users[0],
                session_token_digest(token),
                now + SESSION_LIFETIME,
                now,
            )
        receipt = await inbox.submit(command)
        async with pool.acquire() as conn:
            case_id = await conn.fetchval(
                "SELECT id FROM inbox_case WHERE public_reference=$1", receipt.reference
            )
        current = await inbox.update_case(
            owner,
            case_id,
            UpdateCase(
                idempotency_key=uuid4(),
                expected_revision=1,
                status="in_progress",
                assignee_user_id=users[1],
            ),
        )
        listing = await tasks.create_list(
            owner, CreateList(idempotency_key=uuid4(), title="Private tasks")
        )
        task = await tasks.create_task(
            owner,
            listing.id,
            CreateTask(idempotency_key=uuid4(), title="Private task title"),
        )
        link = SetTaskReference(
            idempotency_key=uuid4(),
            expected_revision=current.revision,
            task_id=task.id,
            present=True,
        )
        try:
            await inbox.set_task_reference(assigned, case_id, link)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Case access granted task access")
        async with asyncio.timeout(10):
            result, replay = await asyncio.gather(
                inbox.set_task_reference(owner, case_id, link),
                inbox.set_task_reference(owner, case_id, link),
            )
        assert result == replay and result.revision == current.revision + 1
        assert result.contact_revision == current.contact_revision
        visible = await inbox.list_task_references(owner, case_id)
        assert len(visible.items) == 1 and visible.items[0].task == task
        hidden = await inbox.list_task_references(assigned, case_id)
        assert hidden.items[0].task_id == task.id and hidden.items[0].task is None
        try:
            await inbox.list_task_references(outsider, case_id)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Foreign case references leaked")
        done = await tasks.update_task(
            owner,
            task.id,
            UpdateTask(
                idempotency_key=uuid4(),
                expected_revision=task.revision,
                title=task.title,
                status="done",
            ),
        )
        assert (await inbox.list_task_references(owner, case_id)).items[0].task == done
        access = await tasks.set_list_member(
            owner,
            listing.id,
            SetListMember(
                idempotency_key=uuid4(),
                expected_revision=1,
                user_id=users[1],
                access="viewer",
            ),
        )
        shared_link = link.model_copy(
            update={"idempotency_key": uuid4(), "expected_revision": result.revision}
        )
        assert (
            await inbox.set_task_reference(assigned, case_id, shared_link)
        ).revision == result.revision
        assert (await inbox.list_task_references(assigned, case_id)).items[
            0
        ].task == done
        await tasks.set_list_member(
            owner,
            listing.id,
            SetListMember(
                idempotency_key=uuid4(),
                expected_revision=access.revision,
                user_id=users[1],
                access=None,
            ),
        )
        try:
            await inbox.set_task_reference(assigned, case_id, shared_link)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Link replay bypassed revoked task rights")
        assert (await inbox.list_task_references(assigned, case_id)).items[
            0
        ].task is None
        removed = await inbox.set_task_reference(
            assigned,
            case_id,
            SetTaskReference(
                idempotency_key=uuid4(),
                expected_revision=result.revision,
                task_id=task.id,
                present=False,
            ),
        )
        assert removed.revision == result.revision + 1
        assert not (await inbox.list_task_references(owner, case_id)).items
        assert (await tasks.get_task(owner, task.id)) == done
        try:
            await inbox.set_task_reference(
                owner, case_id, link.model_copy(update={"idempotency_key": uuid4()})
            )
        except Conflict:
            pass
        else:
            raise AssertionError("Stale case accepted reference")
        failed = link.model_copy(
            update={"idempotency_key": uuid4(), "expected_revision": removed.revision}
        )
        key = f"inbox.task-reference:{users[0]}:{case_id}:{failed.idempotency_key}"
        constraint = f"link_proof_{uuid4().hex}"
        async with pool.acquire() as conn:
            await conn.execute(
                f"ALTER TABLE audit_event ADD CONSTRAINT {constraint} CHECK(request_id <> '{key}')"
            )
        try:
            try:
                await inbox.set_task_reference(owner, case_id, failed)
            except asyncpg.CheckViolationError:
                pass
            else:
                raise AssertionError("Expected real audit failure")
            assert not (await inbox.list_task_references(owner, case_id)).items
            assert (await inbox.get_case(owner, case_id)).revision == removed.revision
            async with pool.acquire() as conn:
                assert not await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM command_receipt WHERE idempotency_key=$1)",
                    key,
                )
        finally:
            async with pool.acquire() as conn:
                await conn.execute(
                    f"ALTER TABLE audit_event DROP CONSTRAINT {constraint}"
                )
        # Populate a real bounded set, then exercise the public operation at its limit.
        limit_tasks = [uuid4() for _ in range(100)]
        async with pool.acquire() as conn, conn.transaction():
            await conn.executemany(
                "INSERT INTO task(id,list_id,title,created_by) VALUES($1,$2,'Reference limit proof',$3)",
                [(item, listing.id, users[0]) for item in limit_tasks],
            )
            await conn.executemany(
                "INSERT INTO inbox_case_task(case_id,task_id) VALUES($1,$2)",
                [(case_id, item) for item in limit_tasks],
            )
        try:
            await inbox.set_task_reference(owner, case_id, failed)
        except Conflict as error:
            assert error.code == "reference_limit"
        else:
            raise AssertionError("Reference limit bypassed")
        assert len((await inbox.list_task_references(owner, case_id)).items) == 100
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM inbox_case_task WHERE case_id=$1 AND task_id=ANY($2::uuid[])",
                case_id,
                limit_tasks,
            )
        app = create_app(settings)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://inbox.leonaid.invalid",
            ) as client,
        ):
            path = f"/api/v1/inbox-cases/{case_id}/tasks"
            headers = {
                "Cookie": f"{SESSION_COOKIE_NAME}={token}",
                "Origin": "https://inbox.leonaid.invalid",
            }
            assert (await client.get(path)).status_code == 401
            assert (
                await client.put(
                    path,
                    headers={"Cookie": headers["Cookie"], "Sec-Fetch-Mode": "cors"},
                    json=failed.model_dump(mode="json", by_alias=True),
                )
            ).status_code == 403
            response = await client.put(
                path,
                headers=headers,
                json=failed.model_dump(mode="json", by_alias=True),
            )
            assert response.status_code == 200, response.text
            references = await client.get(path, headers=headers)
            assert (
                references.status_code == 200
                and references.headers["cache-control"] == "no-store"
            )
            assert references.json()["items"][0]["task"]["status"] == "done"
            assert (
                await client.put(
                    path,
                    headers=headers,
                    json={
                        **failed.model_dump(mode="json", by_alias=True),
                        "present": "true",
                    },
                )
            ).status_code == 422
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM user_global_role WHERE user_id=$1", users[0]
                )
            assert (await client.get(path, headers=headers)).status_code == 404
            assert (
                await client.put(
                    path,
                    headers=headers,
                    json=failed.model_dump(mode="json", by_alias=True),
                )
            ).status_code == 404
        print(
            "PASS Inbox task references: one-slot composition, concurrent replay, live task state, independent ACL, source revocation, remove without task mutation, revision conflict, atomic rollback and production HTTP"
        )
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM inbox_case WHERE id=$1", case_id)
            await conn.execute(
                "DELETE FROM outbox_event WHERE aggregate_type='inbox_case' AND aggregate_id=$1",
                case_id,
            )
            await conn.execute(
                "DELETE FROM audit_event WHERE entity_id=$1 OR actor_user_id=ANY($2::uuid[])",
                case_id,
                users,
            )
            await conn.execute(
                "DELETE FROM task WHERE created_by=ANY($1::uuid[])", users
            )
            await conn.execute(
                "DELETE FROM task_list WHERE owner_user_id=ANY($1::uuid[])", users
            )
            await conn.execute(
                "DELETE FROM command_receipt WHERE idempotency_key=$1 OR idempotency_key LIKE ANY($2::text[])",
                f"inbox.submit:{command.idempotency_key}",
                [
                    f"{prefix}:{user}:%"
                    for user in users
                    for prefix in ("tasks", "inbox.update", "inbox.task-reference")
                ],
            )
            await conn.execute(
                "DELETE FROM user_session WHERE user_id=ANY($1::uuid[])", users
            )
            await conn.execute(
                "DELETE FROM user_global_role WHERE user_id=ANY($1::uuid[])", users
            )
            await conn.execute(
                "DELETE FROM user_account WHERE id=ANY($1::uuid[])", users
            )
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
