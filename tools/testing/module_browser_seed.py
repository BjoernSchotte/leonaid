#!/usr/bin/env python3
"""Two unrelated active accounts with sessions for the module browser tests."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg

from leonaid.adapters.storage import S3ObjectStorage
from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest

FIXTURE = Path(os.environ.get("LEONAID_MODULE_FIXTURE", "/proof/module-fixture.json"))


async def main() -> None:
    # Material uploads need the private versioned bucket of a fresh stack.
    await S3ObjectStorage(
        endpoint_url=os.environ["OBJECT_STORAGE_ENDPOINT_URL"],
        access_key=os.environ["OBJECT_STORAGE_ACCESS_KEY"],
        secret_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],
        bucket=os.environ["OBJECT_STORAGE_BUCKET"],
        region=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1"),
        path_style=os.environ.get("OBJECT_STORAGE_PATH_STYLE", "true").casefold()
        == "true",
    ).ensure_private_versioned_bucket()
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    tokens: list[str] = []
    users: list[str] = []
    now = datetime.now(timezone.utc)
    try:
        async with connection.transaction():
            for _ in range(2):
                user_id, token = uuid4(), uuid4().hex + uuid4().hex
                await connection.execute(
                    "INSERT INTO user_account(id,email,display_name,status) "
                    "VALUES($1,$2,'Modul Browsernachweis','active')",
                    user_id,
                    f"{user_id}@example.org",
                )
                await connection.execute(
                    "INSERT INTO user_session(id,user_id,token_digest,expires_at,"
                    "last_seen_at,fresh_login_at,device_hint,created_at,updated_at) "
                    "VALUES($1,$2,$3,$4,$5,$5,'Browser proof',$5,$5)",
                    uuid4(),
                    user_id,
                    session_token_digest(token),
                    now + SESSION_LIFETIME,
                    now,
                )
                tokens.append(token)
                users.append(str(user_id))
    finally:
        await connection.close()
    FIXTURE.write_text(json.dumps({"sessions": tokens, "users": users}))
    FIXTURE.chmod(0o600)
    print(f"module-browser-seed: two synthetic accounts written to {FIXTURE}")


if __name__ == "__main__":
    asyncio.run(main())
