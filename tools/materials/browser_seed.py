"""Two unrelated active accounts for the isolated material browser contract."""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg

from leonaid.configuration import Settings
from leonaid.adapters.storage.s3 import S3ObjectStorage

from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest


async def main() -> None:
    settings = Settings.model_validate(dict(os.environ))
    await S3ObjectStorage(
        endpoint_url=str(settings.object_storage_endpoint_url),
        access_key=settings.object_storage_access_key.get_secret_value(),
        secret_key=settings.object_storage_secret_key.get_secret_value(),
        bucket=settings.object_storage_bucket,
        region=settings.object_storage_region,
        path_style=settings.object_storage_path_style,
    ).ensure_private_versioned_bucket()
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    tokens = []
    now = datetime.now(timezone.utc)
    try:
        async with conn.transaction():
            for _ in range(2):
                user_id, token = uuid4(), uuid4().hex + uuid4().hex
                await conn.execute(
                    "INSERT INTO user_account(id,email,display_name,status) VALUES($1,$2,'Material Browsernachweis','active')",
                    user_id,
                    f"{user_id}@example.invalid",
                )
                await conn.execute(
                    "INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,device_hint,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$5,'Browser proof',$5,$5)",
                    uuid4(),
                    user_id,
                    session_token_digest(token),
                    now + SESSION_LIFETIME,
                    now,
                )
                tokens.append(token)
        output = Path("/proof/material-browser-fixture.json")
        output.write_text(json.dumps({"sessions": tokens}))
        output.chmod(0o600)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
