#!/usr/bin/env python3
"""Full FastAPI lifespan and middleware with real PostgreSQL; no external I/O claimed."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import asyncpg
import httpx

from leonaid.configuration import Settings
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)
from leonaid.entrypoints.fastapi.platform import create_app


async def main() -> None:
    settings = Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-http-proof-secret-only-32-characters",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-http-proof-encryption-32-characters",
            "LEONAID_PUBLIC_BASE_URL": "https://tasks.leonaid.invalid",
            "LEONAID_ALLOWED_ORIGINS": "https://tasks.leonaid.invalid",
            "TWENTY_BASE_URL": "http://127.0.0.1:9",
            "TWENTY_HEALTH_URL": "http://127.0.0.1:9/health",
            "RUSTFS_HEALTH_URL": "http://127.0.0.1:9/health",
            "OBJECT_STORAGE_ENDPOINT_URL": "http://127.0.0.1:9",
            "OBJECT_STORAGE_BUCKET": "leonaid",
            "OBJECT_STORAGE_ACCESS_KEY": "synthetic-proof",
            "OBJECT_STORAGE_SECRET_KEY": "synthetic-proof",
        }
    )
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    user_id, session_id = uuid4(), uuid4()
    editor_id, editor_session_id = uuid4(), uuid4()
    editor_token = uuid4().hex + uuid4().hex
    token = uuid4().hex + uuid4().hex
    now = datetime.now(timezone.utc)
    try:
        await connection.execute(
            "INSERT INTO user_account (id,email,display_name,status) VALUES ($1,$2,'Task HTTP proof','active')",
            user_id,
            f"{user_id}@leonaid.invalid",
        )
        await connection.execute(
            """
            INSERT INTO user_session (id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,device_hint,created_at,updated_at)
            VALUES ($1,$2,$3,$4,$5,$5,'Task HTTP proof',$5,$5)
        """,
            session_id,
            user_id,
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )
        await connection.execute(
            "INSERT INTO user_account (id,email,display_name,status) VALUES ($1,$2,'Second actor','active')",
            editor_id,
            f"{editor_id}@leonaid.invalid",
        )
        await connection.execute(
            "INSERT INTO user_session (id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,device_hint,created_at,updated_at) VALUES ($1,$2,$3,$4,$5,$5,'Second actor',$5,$5)",
            editor_session_id,
            editor_id,
            session_token_digest(editor_token),
            now + SESSION_LIFETIME,
            now,
        )
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://tasks.leonaid.invalid",
            ) as client:
                assert (await client.get("/api/v1/task-lists")).status_code == 401
                headers = {
                    "Cookie": f"{SESSION_COOKIE_NAME}={token}",
                    "Origin": "https://tasks.leonaid.invalid",
                }
                editor_headers = {
                    **headers,
                    "Cookie": f"{SESSION_COOKIE_NAME}={editor_token}",
                }
                command = {"idempotencyKey": str(uuid4()), "title": "HTTP tasks"}
                assert (
                    await client.post(
                        "/api/v1/task-lists",
                        headers={"Cookie": headers["Cookie"], "Sec-Fetch-Mode": "cors"},
                        json=command,
                    )
                ).status_code == 403
                created = await client.post(
                    "/api/v1/task-lists", headers=headers, json=command
                )
                assert created.status_code == 200, created.text
                assert created.headers["cache-control"] == "no-store"
                listing = created.json()
                assert (
                    await client.post(
                        "/api/v1/task-lists",
                        headers=headers,
                        json={**command, "title": "Changed"},
                    )
                ).status_code == 409
                assert listing["ownerUserId"] == str(user_id)
                assert listing["canEdit"] is True
                assert (
                    await client.post(
                        "/api/v1/task-lists", headers=headers, json=command
                    )
                ).json() == listing
                assert (await client.get("/api/v1/task-lists", headers=headers)).json()[
                    "items"
                ] == [listing]
                member_path = f"/api/v1/task-lists/{listing['id']}/members"
                members = await client.get(member_path, headers=headers)
                assert members.status_code == 200 and members.json()["items"] == []
                assert members.json()["ownerUserId"] == str(user_id)
                protection = await client.put(
                    member_path,
                    headers=headers,
                    json={
                        "idempotencyKey": str(uuid4()),
                        "expectedRevision": 1,
                        "userId": str(user_id),
                        "access": None,
                    },
                )
                assert (
                    protection.status_code == 409
                    and protection.json()["error"]["code"] == "list_owner_protected"
                )
                epic_path = f"/api/v1/task-lists/{listing['id']}/epics"
                epic_command = {"idempotencyKey": str(uuid4()), "title": "Preparation"}
                epic_response = await client.post(
                    epic_path, headers=headers, json=epic_command
                )
                assert epic_response.status_code == 200, epic_response.text
                epic = epic_response.json()
                assert (
                    await client.post(epic_path, headers=headers, json=epic_command)
                ).json() == epic
                assert (
                    await client.post(
                        epic_path,
                        headers=headers,
                        json={**epic_command, "parentId": epic["id"]},
                    )
                ).status_code == 422
                body = {
                    "idempotencyKey": str(uuid4()),
                    "title": "HTTP task",
                    "description": "All original fields",
                    "deferredUntil": now.isoformat(),
                    "epicId": epic["id"],
                    "assigneeUserId": str(user_id),
                    "dueAt": now.isoformat(),
                }
                response = await client.post(
                    f"/api/v1/task-lists/{listing['id']}/tasks",
                    headers=headers,
                    json=body,
                )
                assert response.status_code == 200, response.text
                task = response.json()
                rename = {
                    "idempotencyKey": str(uuid4()),
                    "expectedRevision": 1,
                    "title": "Ready",
                }
                renamed = await client.put(
                    f"/api/v1/task-epics/{epic['id']}", headers=headers, json=rename
                )
                assert renamed.status_code == 200 and renamed.json()["revision"] == 2, (
                    renamed.text
                )
                assert (
                    await client.put(
                        f"/api/v1/task-epics/{epic['id']}", headers=headers, json=rename
                    )
                ).json() == renamed.json()
                assert (
                    await client.put(
                        f"/api/v1/task-epics/{epic['id']}",
                        headers=headers,
                        json={**rename, "idempotencyKey": str(uuid4())},
                    )
                ).status_code == 409
                assert (
                    await client.get(epic_path + "?search=Ready", headers=headers)
                ).json()["items"] == [renamed.json()]
                assert (
                    await client.get(f"/api/v1/tasks/{task['id']}", headers=headers)
                ).json()["epicId"] == epic["id"]
                assert task["listId"] == listing["id"] and task["status"] == "open"
                mine = await client.get(
                    "/api/v1/tasks?forMe=true&status=open", headers=headers
                )
                assert mine.status_code == 200
                summary = mine.json()["items"][0]
                assert {key: summary[key] for key in task} == task
                assert summary["canEdit"] and summary["listTitle"] == listing["title"]
                assert (
                    summary["epicTitle"] == "Ready"
                    and summary["assigneeName"] == "Task HTTP proof"
                )
                assert summary["actionTitle"] is None
                s3_query = await client.get(
                    "/api/v1/tasks",
                    headers=headers,
                    params={
                        "listId": listing["id"],
                        "status": "open",
                        "dueFrom": (now - timedelta(seconds=1)).isoformat(),
                        "dueBefore": (now + timedelta(seconds=1)).isoformat(),
                        "deferredState": "all",
                        "sort": "due",
                    },
                )
                assert s3_query.status_code == 200, s3_query.text
                assert [item["id"] for item in s3_query.json()["items"]] == [task["id"]]
                for params in (
                    {
                        "dueFrom": now.isoformat(),
                        "dueBefore": (now - timedelta(seconds=1)).isoformat(),
                    },
                    {"sort": "section"},
                    {"includeDeferred": "false", "deferredState": "all"},
                    {"includeDeferred": "true", "deferredState": "active"},
                    {"dueFrom": "2026-03-29T00:00:00"},
                ):
                    invalid_query = await client.get(
                        "/api/v1/tasks", headers=headers, params=params
                    )
                    assert invalid_query.status_code == 422, (
                        params,
                        invalid_query.text,
                    )
                assert (
                    await client.get("/api/v1/tasks", headers=editor_headers)
                ).json()["items"] == []
                grant = await client.put(
                    member_path,
                    headers=headers,
                    json={
                        "idempotencyKey": str(uuid4()),
                        "expectedRevision": 1,
                        "userId": str(editor_id),
                        "access": "viewer",
                    },
                )
                assert grant.status_code == 200
                assert not (
                    await client.get(
                        f"/api/v1/task-lists/{listing['id']}", headers=editor_headers
                    )
                ).json()["canEdit"]
                assert not (
                    await client.get("/api/v1/tasks", headers=editor_headers)
                ).json()["items"][0]["canEdit"]
                assert (
                    await client.get("/api/v1/tasks?limit=101", headers=headers)
                ).status_code == 422
                invalid = {**body, "idempotencyKey": str(uuid4()), "dueAt": 12345}
                assert (
                    await client.post(
                        f"/api/v1/task-lists/{listing['id']}/tasks",
                        headers=headers,
                        json=invalid,
                    )
                ).status_code == 422
                update = {
                    **body,
                    "expectedRevision": 1,
                    "idempotencyKey": str(uuid4()),
                    "title": task["title"],
                    "status": "done",
                }
                path = f"/api/v1/tasks/{task['id']}"
                assert (
                    await client.put(
                        path, headers=headers, json={**update, "expectedRevision": "1"}
                    )
                ).status_code == 422
                assert (
                    await client.put(path, headers=editor_headers, json=update)
                ).status_code == 404
                promotion = await client.put(
                    member_path,
                    headers=headers,
                    json={
                        "idempotencyKey": str(uuid4()),
                        "expectedRevision": 2,
                        "userId": str(editor_id),
                        "access": "editor",
                    },
                )
                assert promotion.status_code == 200
                assert (
                    await client.get("/api/v1/tasks", headers=editor_headers)
                ).json()["items"][0]["canEdit"]
                changed = await client.put(path, headers=editor_headers, json=update)
                assert changed.status_code == 200 and changed.json()["revision"] == 2, (
                    changed.text
                )
                assert (
                    await client.put(
                        path,
                        headers=headers,
                        json={**update, "idempotencyKey": str(uuid4())},
                    )
                ).status_code == 409
                assert (
                    await client.put(path, headers=editor_headers, json=update)
                ).json() == changed.json()
                undo = {
                    **update,
                    "idempotencyKey": str(uuid4()),
                    "expectedRevision": changed.json()["revision"],
                    "status": "open",
                }
                undone = await client.put(path, headers=editor_headers, json=undo)
                assert undone.status_code == 200 and undone.json()["revision"] == 3
                assert (
                    await client.put(path, headers=editor_headers, json=undo)
                ).json() == undone.json()
                preserved = set(task) - {"status", "revision", "updatedAt"}
                for saved in (
                    changed.json(),
                    undone.json(),
                    (await client.get(path, headers=headers)).json(),
                ):
                    assert {key: saved[key] for key in preserved} == {
                        key: task[key] for key in preserved
                    }
                assert (
                    await connection.fetchval(
                        "SELECT count(*) FROM command_receipt WHERE idempotency_key LIKE $1",
                        f"tasks:{editor_id}:tasks.task.updated:%",
                    )
                    == 2
                )
                complete_again = {
                    **update,
                    "idempotencyKey": str(uuid4()),
                    "expectedRevision": 3,
                }
                completed = await client.put(
                    path, headers=editor_headers, json=complete_again
                )
                assert completed.status_code == 200
                edited = await client.put(
                    path,
                    headers=headers,
                    json={
                        **complete_again,
                        "idempotencyKey": str(uuid4()),
                        "expectedRevision": 4,
                        "title": "Other actor title",
                    },
                )
                assert edited.status_code == 200
                stale_undo = await client.put(
                    path,
                    headers=editor_headers,
                    json={
                        **undo,
                        "idempotencyKey": str(uuid4()),
                        "expectedRevision": 4,
                    },
                )
                assert stale_undo.status_code == 409
                assert (await client.get(path, headers=headers)).json() == edited.json()
                revocation = await client.put(
                    member_path,
                    headers=headers,
                    json={
                        "idempotencyKey": str(uuid4()),
                        "expectedRevision": 3,
                        "userId": str(editor_id),
                        "access": None,
                    },
                )
                assert revocation.status_code == 200
                assert (
                    await client.put(path, headers=editor_headers, json=complete_again)
                ).status_code == 404
                assert (
                    await client.get("/api/v1/tasks", headers=editor_headers)
                ).json()["items"] == []
                await connection.execute(
                    "UPDATE user_account SET status='suspended' WHERE id=$1", user_id
                )
                assert (await client.get(path, headers=headers)).status_code == 401
        print(
            "PASS: production FastAPI composition, sessions, CSRF, camelCase JSON, validation, queries and revision conflict"
        )
    finally:
        async with connection.transaction():
            await connection.execute(
                "DELETE FROM task WHERE list_id IN (SELECT id FROM task_list WHERE owner_user_id=$1)",
                user_id,
            )
            await connection.execute(
                "DELETE FROM task_epic WHERE list_id IN (SELECT id FROM task_list WHERE owner_user_id=$1)",
                user_id,
            )
            await connection.execute(
                "DELETE FROM task_list WHERE owner_user_id=$1", user_id
            )
            await connection.execute(
                "DELETE FROM audit_event WHERE actor_user_id=ANY($1::uuid[])",
                [user_id, editor_id],
            )
            await connection.execute(
                "DELETE FROM command_receipt WHERE idempotency_key LIKE $1 OR idempotency_key LIKE $2",
                f"tasks:{user_id}:%",
                f"tasks:{editor_id}:%",
            )
            await connection.execute(
                "DELETE FROM user_session WHERE id=ANY($1::uuid[])",
                [session_id, editor_session_id],
            )
            await connection.execute(
                "DELETE FROM user_account WHERE id=ANY($1::uuid[])",
                [user_id, editor_id],
            )
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
