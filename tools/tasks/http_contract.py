#!/usr/bin/env python3
"""Full FastAPI lifespan and middleware with real PostgreSQL; no external I/O claimed."""

import asyncio
import os
from datetime import datetime, timezone
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
                assert (
                    await client.post(
                        "/api/v1/task-lists", headers=headers, json=command
                    )
                ).json() == listing
                assert (await client.get("/api/v1/task-lists", headers=headers)).json()[
                    "items"
                ] == [listing]
                body = {
                    "idempotencyKey": str(uuid4()),
                    "title": "HTTP task",
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
                assert task["listId"] == listing["id"] and task["status"] == "open"
                mine = await client.get(
                    "/api/v1/tasks?forMe=true&status=open", headers=headers
                )
                assert mine.status_code == 200 and mine.json()["items"] == [task]
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
                    "idempotencyKey": str(uuid4()),
                    "expectedRevision": 1,
                    "title": "Completed",
                    "status": "done",
                }
                path = f"/api/v1/tasks/{task['id']}"
                assert (
                    await client.put(
                        path, headers=headers, json={**update, "expectedRevision": "1"}
                    )
                ).status_code == 422
                changed = await client.put(path, headers=headers, json=update)
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
                "DELETE FROM task_list WHERE owner_user_id=$1", user_id
            )
            await connection.execute(
                "DELETE FROM audit_event WHERE actor_user_id=$1", user_id
            )
            await connection.execute(
                "DELETE FROM command_receipt WHERE idempotency_key LIKE $1",
                f"tasks:{user_id}:%",
            )
            await connection.execute("DELETE FROM user_session WHERE id=$1", session_id)
            await connection.execute("DELETE FROM user_account WHERE id=$1", user_id)
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
