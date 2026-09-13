#!/usr/bin/env python3
"""Full FastAPI lifespan and middleware with real PostgreSQL; no external I/O claimed."""

from collections.abc import AsyncIterator

import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import asyncpg
import httpx

from leonaid.configuration import Settings
from leonaid.adapters.storage.s3 import S3ObjectStorage
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
            "LEONAID_PUBLIC_BASE_URL": "https://materials.leonaid.invalid",
            "LEONAID_ALLOWED_ORIGINS": "https://materials.leonaid.invalid",
            "TWENTY_BASE_URL": "http://127.0.0.1:9",
            "TWENTY_HEALTH_URL": "http://127.0.0.1:9/health",
            "RUSTFS_HEALTH_URL": "http://127.0.0.1:9/health",
            "OBJECT_STORAGE_ENDPOINT_URL": os.environ["OBJECT_STORAGE_ENDPOINT_URL"],
            "OBJECT_STORAGE_BUCKET": os.environ["OBJECT_STORAGE_BUCKET"],
            "OBJECT_STORAGE_ACCESS_KEY": os.environ["OBJECT_STORAGE_ACCESS_KEY"],
            "OBJECT_STORAGE_SECRET_KEY": os.environ["OBJECT_STORAGE_SECRET_KEY"],
        }
    )
    storage = S3ObjectStorage(
        endpoint_url=os.environ["OBJECT_STORAGE_ENDPOINT_URL"],
        access_key=os.environ["OBJECT_STORAGE_ACCESS_KEY"],
        secret_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],
        bucket=os.environ["OBJECT_STORAGE_BUCKET"],
    )
    await storage.ensure_private_versioned_bucket()
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
                base_url="https://materials.leonaid.invalid",
            ) as client:
                root = "/api/v1/materials"
                assert (await client.get(root)).status_code == 401
                headers = {
                    "Cookie": f"{SESSION_COOKIE_NAME}={token}",
                    "Origin": "https://materials.leonaid.invalid",
                }
                command = {"idempotencyKey": str(uuid4()), "title": "HTTP material"}
                upload = {"file": ("Ablauf ü.txt", b"first bytes", "text/plain")}
                assert (
                    await client.post(
                        root,
                        headers={"Cookie": headers["Cookie"], "Sec-Fetch-Mode": "cors"},
                        data=command,
                        files=upload,
                    )
                ).status_code == 403
                response = await client.post(
                    root, headers=headers, data=command, files=upload
                )
                assert response.status_code == 200, response.text
                material = response.json()
                assert material["ownerUserId"] == str(user_id)
                assert response.headers["cache-control"] == "no-store"
                assert (
                    await client.post(root, headers=headers, data=command, files=upload)
                ).json() == material
                assert (
                    await client.post(
                        root,
                        headers=headers,
                        data=command,
                        files={"file": ("Ablauf ü.txt", b"different", "text/plain")},
                    )
                ).status_code == 409
                path = root + "/" + material["id"]
                assert (await client.get(path, headers=headers)).json() == material
                assert (
                    await client.get(root + "?search=HTTP", headers=headers)
                ).json()["items"] == [material]
                version = await client.get(path + "/versions/1", headers=headers)
                assert version.json()["filename"] == "Ablauf ü.txt"
                assert (
                    not {"storageBucket", "objectKey", "storageVersionId"}
                    & version.json().keys()
                )
                download = await client.get(
                    path + "/versions/1/download", headers=headers
                )
                assert download.content == b"first bytes"
                assert download.headers["content-type"] == "application/octet-stream"
                assert download.headers["cache-control"] == "no-store"
                assert download.headers["x-content-type-options"] == "nosniff"
                assert (
                    "filename*=UTF-8''Ablauf%20%C3%BC.txt"
                    in download.headers["content-disposition"]
                )
                assert (
                    await client.get(path + "/versions/1/download")
                ).status_code == 401
                target_id = uuid4()
                target_email = f"{target_id}@example.org"
                await connection.execute(
                    "INSERT INTO user_account(id,email,display_name,status) VALUES ($1,$2,'Material member HTTP','active')",
                    target_id,
                    target_email,
                )
                permission = await client.get(path + "/permissions", headers=headers)
                assert permission.json() == {"canEdit": True, "canManage": True}
                grant = {
                    "idempotencyKey": str(uuid4()),
                    "expectedAccessRevision": 1,
                    "email": target_email,
                    "access": "editor",
                }
                access = await client.put(
                    path + "/members/by-email", headers=headers, json=grant
                )
                assert (
                    access.status_code == 200 and access.json()["accessRevision"] == 2
                ), access.text
                assert (
                    await client.put(
                        path + "/members/by-email", headers=headers, json=grant
                    )
                ).json() == access.json()
                members = await client.get(
                    path + "/members?search=member", headers=headers
                )
                assert members.json()["items"] == [
                    {
                        "userId": str(target_id),
                        "displayName": "Material member HTTP",
                        "access": "editor",
                        "active": True,
                    }
                ]
                removed = await client.put(
                    path + "/members",
                    headers=headers,
                    json={
                        "idempotencyKey": str(uuid4()),
                        "expectedAccessRevision": 2,
                        "userId": str(target_id),
                        "access": None,
                    },
                )
                assert (
                    removed.status_code == 200 and removed.json()["accessRevision"] == 3
                )
                assert (await client.get(path, headers=headers)).json()["revision"] == 1
                next_command = {"idempotencyKey": str(uuid4()), "expectedRevision": "1"}
                changed = await client.post(
                    path + "/versions",
                    headers=headers,
                    data=next_command,
                    files={"file": ("updated.txt", b"second bytes", "text/plain")},
                )
                assert changed.status_code == 200 and changed.json()["revision"] == 2, (
                    changed.text
                )
                assert (
                    await client.get(path + "/versions/1/download", headers=headers)
                ).content == b"first bytes"
                assert (
                    await client.post(
                        path + "/versions",
                        headers=headers,
                        data={**next_command, "idempotencyKey": str(uuid4())},
                        files=upload,
                    )
                ).status_code == 409
                for fields, files in (
                    (
                        {**command, "idempotencyKey": str(uuid4()), "unknown": "no"},
                        upload,
                    ),
                    (
                        {**command, "idempotencyKey": str(uuid4())},
                        {"file": ("../bad.txt", b"x", "text/plain")},
                    ),
                    (
                        {**command, "idempotencyKey": str(uuid4())},
                        {"file": ("empty.txt", b"", "text/plain")},
                    ),
                    (
                        {**command, "idempotencyKey": str(uuid4())},
                        {"file": ("type.txt", b"x", "invalid")},
                    ),
                ):
                    rejected = await client.post(
                        root, headers=headers, data=fields, files=files
                    )
                    assert rejected.status_code == 422, rejected.text
                assert (
                    await client.get(path + "/versions/0/download", headers=headers)
                ).status_code == 422
                assert (
                    await client.get(root + "?limit=101", headers=headers)
                ).status_code == 422

                duplicate = await client.post(
                    root,
                    headers=headers,
                    data=command,
                    files=[
                        ("file", ("duplicate.txt", b"x", "text/plain")),
                        ("title", (None, "second title")),
                    ],
                )
                assert duplicate.status_code == 422, duplicate.text
                assert (
                    await client.post(
                        "/api/v1/surveys", headers=headers, content=b"x" * 1_048_577
                    )
                ).status_code == 413

                async def oversized() -> AsyncIterator[bytes]:
                    for _ in range(26):
                        yield b"x" * 1_048_576

                rejected = await client.post(
                    root,
                    headers={**headers, "Content-Type": "application/octet-stream"},
                    content=oversized(),
                )
                assert rejected.status_code == 413, rejected.text
                assert rejected.headers["cache-control"] == "no-store"
                print(
                    "PASS production material multipart, session/CSRF, replay/conflict, attachment headers, strict metadata and actual streamed size limit"
                )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
