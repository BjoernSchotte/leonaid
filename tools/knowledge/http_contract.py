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
            "LEONAID_PUBLIC_BASE_URL": "https://knowledge.leonaid.invalid",
            "LEONAID_ALLOWED_ORIGINS": "https://knowledge.leonaid.invalid",
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
            "INSERT INTO user_account (id,email,display_name,status) VALUES ($1,$2,'Knowledge HTTP proof','active')",
            user_id,
            f"{user_id}@leonaid.invalid",
        )
        await connection.execute(
            """
            INSERT INTO user_session (id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,device_hint,created_at,updated_at)
            VALUES ($1,$2,$3,$4,$5,$5,'Knowledge HTTP proof',$5,$5)
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
                base_url="https://knowledge.leonaid.invalid",
            ) as client:
                root = "/api/v1/knowledge-pages"
                assert (await client.get(root)).status_code == 401
                headers = {
                    "Cookie": f"{SESSION_COOKIE_NAME}={token}",
                    "Origin": "https://knowledge.leonaid.invalid",
                }
                command = {"idempotencyKey": str(uuid4()), "title": "HTTP knowledge"}
                assert (
                    await client.post(
                        root,
                        headers={"Cookie": headers["Cookie"], "Sec-Fetch-Mode": "cors"},
                        json=command,
                    )
                ).status_code == 403
                response = await client.post(root, headers=headers, json=command)
                assert response.status_code == 200, response.text
                assert response.headers["cache-control"] == "no-store"
                page = response.json()
                assert page["ownerUserId"] == str(user_id) and page["revision"] == 1
                assert (
                    await client.post(root, headers=headers, json=command)
                ).json() == page
                assert (
                    await client.post(
                        root, headers=headers, json={**command, "title": "Different"}
                    )
                ).status_code == 409
                path = f"{root}/{page['id']}"
                assert (await client.get(path, headers=headers)).json() == page
                listing = await client.get(root + "?search=KNOWLEDGE", headers=headers)
                assert listing.status_code == 200 and listing.json()["items"] == [
                    {k: v for k, v in page.items() if k != "content"}
                ]
                assert (
                    await client.get(root + "?limit=101", headers=headers)
                ).status_code == 422
                assert (
                    await client.get(root + "?actionId=invalid", headers=headers)
                ).status_code == 422
                assert (
                    await client.get(f"{root}/{uuid4()}", headers=headers)
                ).status_code == 404
                for content in (
                    {"type": "script"},
                    {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "bad",
                                        "marks": [
                                            {
                                                "type": "link",
                                                "attrs": {
                                                    "href": "javascript:alert(1)"
                                                },
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                ):
                    assert (
                        await client.post(
                            root,
                            headers=headers,
                            json={
                                **command,
                                "idempotencyKey": str(uuid4()),
                                "content": content,
                            },
                        )
                    ).status_code == 422
                update = {
                    "idempotencyKey": str(uuid4()),
                    "expectedRevision": 1,
                    "title": "Updated",
                    "content": page["content"],
                }
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
                    await client.put(path, headers=headers, json=update)
                ).json() == changed.json()
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
                assert (
                    await client.post(root, headers=headers, json=command)
                ).status_code == 401
        print(
            "PASS: knowledge production lifespan, sessions, CSRF, camelCase, documents, query bounds, replay and revision conflict"
        )
    finally:
        async with connection.transaction():
            await connection.execute(
                "DELETE FROM knowledge_page WHERE owner_user_id=$1", user_id
            )
            await connection.execute(
                "DELETE FROM audit_event WHERE actor_user_id=$1", user_id
            )
            await connection.execute(
                "DELETE FROM command_receipt WHERE idempotency_key LIKE $1",
                f"knowledge:{user_id}:%",
            )
            await connection.execute("DELETE FROM user_session WHERE id=$1", session_id)
            await connection.execute("DELETE FROM user_account WHERE id=$1", user_id)
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
