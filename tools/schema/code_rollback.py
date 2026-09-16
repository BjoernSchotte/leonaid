#!/usr/bin/env python3
"""Run real older FastAPI code on the current schema without a downgrade.

This checks startup and persisted identity reads, not old workers consuming new jobs.
Run only through the isolated schema runner.
"""

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg
import httpx
import leonaid.entrypoints.fastapi.platform as platform
from leonaid.configuration import Settings
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)


async def main() -> None:
    expected_source = Path(os.environ["ROLLBACK_SOURCE"]).resolve()
    assert Path(platform.__file__).resolve().is_relative_to(expected_source)
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

    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    user_id, session_id, list_id, task_id = (uuid4() for _ in range(4))
    token = uuid4().hex + uuid4().hex
    now = datetime.now(timezone.utc)
    revision = await conn.fetchval("SELECT version_num FROM alembic_version")
    assert await conn.fetchval("SELECT to_regclass('inbox_case') IS NOT NULL")
    try:
        await conn.execute(
            "INSERT INTO user_account(id,email,display_name,status) VALUES ($1,$2,'Code rollback proof','active')",
            user_id,
            f"{user_id}@leonaid.invalid",
        )
        await conn.execute(
            "INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,device_hint,created_at,updated_at) VALUES ($1,$2,$3,$4,$5,$5,'Rollback proof',$5,$5)",
            session_id,
            user_id,
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )
        await conn.execute(
            "INSERT INTO task_list(id,owner_user_id,title) VALUES ($1,$2,'Rollback retained list')",
            list_id,
            user_id,
        )
        await conn.execute(
            "INSERT INTO task(id,list_id,title,created_by,due_at,deferred_until) VALUES ($1,$2,'Rollback retained task',$3,$4,$4)",
            task_id,
            list_id,
            user_id,
            now,
        )
        original_task = dict(
            await conn.fetchrow("SELECT * FROM task WHERE id=$1", task_id)
        )
        app = platform.create_app(settings)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://tasks.leonaid.invalid",
            ) as client:
                assert (await client.get("/api/v1/identity/me")).status_code == 401
                response = await client.get(
                    "/api/v1/identity/me",
                    headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
                )
                assert response.status_code == 200, response.text
                assert "Code rollback proof" in response.text
                assert response.headers["cache-control"] == "no-store"
                if "/api/v1/task-lists" in app.openapi()["paths"]:
                    task = await client.get(
                        f"/api/v1/tasks/{task_id}",
                        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
                    )
                    assert task.status_code == 200, task.text
                    assert task.json()["title"] == original_task["title"]
                    assert task.json()["listId"] == str(list_id)
                await conn.execute(
                    "UPDATE user_account SET status='suspended' WHERE id=$1", user_id
                )
                assert (
                    await client.get(
                        "/api/v1/identity/me",
                        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
                    )
                ).status_code == 401
        assert (
            await conn.fetchval("SELECT version_num FROM alembic_version") == revision
        )
        assert (
            dict(await conn.fetchrow("SELECT * FROM task WHERE id=$1", task_id))
            == original_task
        )
        print(
            "PASS older code: real lifespan, session read and current account revocation and retained new task on unchanged expanded schema"
        )
    finally:
        await conn.execute("DELETE FROM task WHERE id=$1", task_id)
        await conn.execute("DELETE FROM task_list WHERE id=$1", list_id)
        await conn.execute("DELETE FROM user_session WHERE user_id=$1", user_id)
        await conn.execute("DELETE FROM user_account WHERE id=$1", user_id)
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
