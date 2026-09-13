#!/usr/bin/env python3
"""Production FastAPI Inbox routes with actual PostgreSQL sessions and data."""

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
from leonaid.modules.inbox.api import SubmitCase


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
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    users = [uuid4(), uuid4()]
    tokens = [uuid4().hex + uuid4().hex for _ in users]
    case_id = None
    command = SubmitCase(
        idempotency_key=uuid4(),
        subject="HTTP Inbox",
        message="Synthetischer Eingang",
        given_name="Test",
        family_name="Person",
        email="test@example.org",
    )
    try:
        now = datetime.now(timezone.utc)
        for user, token in zip(users, tokens):
            await conn.execute(
                "INSERT INTO user_account(id,email,display_name,status) VALUES($1,$2,'Inbox HTTP proof','active')",
                user,
                f"{user}@example.org",
            )
            await conn.execute(
                "INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,device_hint,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$5,'Inbox HTTP proof',$5,$5)",
                uuid4(),
                user,
                session_token_digest(token),
                now + SESSION_LIFETIME,
                now,
            )
        await conn.execute(
            "INSERT INTO user_global_role(user_id,role) VALUES($1,'system_admin')",
            users[0],
        )
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            receipt = await app.state.inbox_service.submit(command)
            case_id = await conn.fetchval(
                "SELECT id FROM inbox_case WHERE public_reference=$1", receipt.reference
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://inbox.leonaid.invalid",
            ) as client:
                root = "/api/v1/inbox-cases"
                path = f"{root}/{case_id}"
                headers = {
                    "Cookie": f"{SESSION_COOKIE_NAME}={tokens[0]}",
                    "Origin": "https://inbox.leonaid.invalid",
                }
                outsider = {**headers, "Cookie": f"{SESSION_COOKIE_NAME}={tokens[1]}"}
                assert (await client.get(root)).status_code == 401
                assert (await client.get(path, headers=outsider)).status_code == 404
                assert (await client.get(root, headers=outsider)).json()["items"] == []
                candidates_path = path + "/assignees"
                assert (await client.get(candidates_path)).status_code == 401
                assert (
                    await client.get(candidates_path, headers=outsider)
                ).status_code == 404
                candidates = await client.get(
                    candidates_path,
                    headers=headers,
                    params={"search": "Inbox HTTP proof", "limit": 1},
                )
                assert candidates.status_code == 200, candidates.text
                assert candidates.headers["cache-control"] == "no-store"
                assert len(candidates.json()["items"]) == 1
                assert set(candidates.json()["items"][0]) == {"userId", "displayName"}
                assert candidates.json()["nextOffset"] == 1
                assert (
                    await client.get(
                        candidates_path, headers=headers, params={"limit": 101}
                    )
                ).status_code == 422
                response = await client.get(path, headers=headers)
                assert response.status_code == 200, response.text
                assert response.headers["cache-control"] == "no-store"
                case = response.json()
                assert (
                    case["message"] == command.message
                    and case["contactStatus"] == "pending"
                )
                assert not {"contactCreateId", "contactJobId"} & case.keys()
                assert (
                    await client.get(root + "?search=HTTP%20Inbox", headers=headers)
                ).json()["items"] == [case]
                comment_path = path + "/comments"
                comment = {"idempotencyKey": str(uuid4()), "body": "Internal HTTP note"}
                assert (await client.get(comment_path)).status_code == 401
                assert (
                    await client.get(comment_path, headers=outsider)
                ).status_code == 404
                assert (
                    await client.post(comment_path, headers=outsider, json=comment)
                ).status_code == 404
                assert (
                    await client.post(
                        comment_path,
                        headers={"Cookie": headers["Cookie"], "Sec-Fetch-Mode": "cors"},
                        json=comment,
                    )
                ).status_code == 403
                added = await client.post(comment_path, headers=headers, json=comment)
                assert added.status_code == 201, added.text
                assert added.headers["cache-control"] == "no-store"
                assert added.json()["authorUserId"] == str(users[0])
                assert (
                    await client.post(comment_path, headers=headers, json=comment)
                ).json() == added.json()
                assert (await client.get(comment_path, headers=headers)).json()[
                    "items"
                ] == [added.json()]
                assert (
                    await client.post(
                        comment_path,
                        headers=headers,
                        json={**comment, "body": "Changed"},
                    )
                ).status_code == 409
                assert (
                    await client.post(
                        comment_path, headers=headers, json={**comment, "body": " "}
                    )
                ).status_code == 422
                assert (
                    await client.get(
                        comment_path, headers=headers, params={"limit": 101}
                    )
                ).status_code == 422
                assert (
                    await client.get(f"/api/v1/public/inbox-cases/{case_id}/comments")
                ).status_code == 404
                change = {
                    "idempotencyKey": str(uuid4()),
                    "expectedRevision": 1,
                    "status": "closed",
                    "assigneeUserId": None,
                    "closureNote": "Beantwortet",
                }
                assert (
                    await client.put(
                        path,
                        headers={"Cookie": headers["Cookie"], "Sec-Fetch-Mode": "cors"},
                        json=change,
                    )
                ).status_code == 403
                assert (
                    await client.put(path, headers=outsider, json=change)
                ).status_code == 404
                for invalid in [
                    {**change, "closureNote": None},
                    {**change, "expectedRevision": "1"},
                    {**change, "message": "Rewrite original"},
                ]:
                    assert (
                        await client.put(path, headers=headers, json=invalid)
                    ).status_code == 422
                changed = await client.put(path, headers=headers, json=change)
                assert changed.status_code == 200, changed.text
                assert (
                    changed.json()["revision"] == 2
                    and changed.json()["closedAt"] is not None
                )
                assert (
                    await client.put(path, headers=headers, json=change)
                ).json() == changed.json()
                assert (
                    await client.put(
                        path,
                        headers=headers,
                        json={**change, "idempotencyKey": str(uuid4())},
                    )
                ).status_code == 409
                for query in [
                    "?limit=101",
                    "?offset=5001",
                    "?actionId=invalid",
                    "?status=approved",
                ]:
                    assert (
                        await client.get(root + query, headers=headers)
                    ).status_code == 422
                # Public submissions use a separate guarded route.
                assert (
                    await client.post(
                        root, headers=headers, json=command.model_dump(mode="json")
                    )
                ).status_code == 405
                await conn.execute(
                    "DELETE FROM user_global_role WHERE user_id=$1", users[0]
                )
                assert (
                    await client.put(path, headers=headers, json=change)
                ).status_code == 404
                assert (
                    await client.get(comment_path, headers=headers)
                ).status_code == 404
                assert (
                    await client.post(comment_path, headers=headers, json=comment)
                ).status_code == 404
                await conn.execute(
                    "UPDATE user_account SET status='suspended' WHERE id=$1", users[0]
                )
                assert (await client.get(root, headers=headers)).status_code == 401
        print(
            "PASS inbox HTTP: production lifespan/session/CSRF, internal comments, same ACL, no-store, strict JSON/query, close/replay/conflict, revoked access and suspended session"
        )
    finally:
        async with conn.transaction():
            await conn.execute("DELETE FROM inbox_case WHERE id=$1", case_id)
            await conn.execute(
                "DELETE FROM outbox_event WHERE aggregate_type='inbox_case' AND aggregate_id=$1",
                case_id,
            )
            await conn.execute("DELETE FROM audit_event WHERE entity_id=$1", case_id)
            await conn.execute(
                "DELETE FROM command_receipt WHERE idempotency_key=$1 OR idempotency_key LIKE $2 OR idempotency_key LIKE $3",
                f"inbox.submit:{command.idempotency_key}",
                f"inbox.update:{users[0]}:%",
                f"inbox.comment:{users[0]}:%",
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
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
