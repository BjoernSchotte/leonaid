"""Real isolated PostgreSQL/API foundation proof, with ephemeral browser session."""

import asyncio
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)


async def main():
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    member = os.environ.get("SURVEY_FOUNDATION_MEMBER") == "1"
    actor = UUID(
        "10000000-0000-4000-8000-000000009702"
        if member
        else "10000000-0000-4000-8000-000000009701"
    )
    name = "Survey Test Member" if member else "Survey Test Admin"
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(48)
    try:
        await connection.execute(
            """INSERT INTO user_account(id,email,display_name,status,email_verified_at)
            VALUES($1,$3,$4,'active',$2)
            ON CONFLICT(id) DO NOTHING""",
            actor,
            now,
            "surveys-member@example.invalid"
            if member
            else "surveys-admin@example.invalid",
            name,
        )
        if not member:
            await connection.execute(
                "INSERT INTO user_global_role(user_id,role) VALUES($1,'system_admin') ON CONFLICT DO NOTHING",
                actor,
            )
        await connection.execute(
            """INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,created_at,updated_at)
            VALUES($1,$2,$3,$4,$5,$5,$5,$5)""",
            uuid4(),
            actor,
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )
        survey, version, participation = uuid4(), uuid4(), uuid4()
        async with connection.transaction():
            await connection.execute(
                "INSERT INTO survey(id,title,owner_user_id) VALUES($1,'Synthetic fixture',$2)",
                survey,
                actor,
            )
            await connection.execute(
                """INSERT INTO survey_version(id,survey_id,number,definition,schema_hash,renderer_version,capability_profile)
                VALUES($1,$2,1,'{"pages":[]}','synthetic','3.0.3','initial-v1')""",
                version,
                survey,
            )
            await connection.execute(
                """INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,inactivity_timeout_seconds,answers)
                VALUES($1,$2,$3,$4,30,'{"nps":9}')""",
                participation,
                survey,
                version,
                secrets.token_hex(32),
            )
            assert json.loads(
                await connection.fetchval(
                    "SELECT answers::text FROM survey_participation WHERE id=$1",
                    participation,
                )
            ) == {"nps": 9}
            try:
                async with connection.transaction():
                    await connection.execute(
                        "UPDATE survey_version SET definition='{}' WHERE id=$1", version
                    )
            except asyncpg.IntegrityConstraintViolationError:
                pass
            else:
                raise AssertionError("Published version was mutable")
            await connection.execute("DELETE FROM survey WHERE id=$1", survey)
            assert not await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM survey_participation WHERE id=$1)",
                participation,
            )
        async with httpx.AsyncClient(base_url="http://api:8000") as client:
            assert (await client.get("/health/ready")).status_code == 200
            response = await client.get(
                "/api/v1/identity/me", cookies={SESSION_COOKIE_NAME: token}
            )
            assert response.status_code == 200, response.text
            assert name in response.text
        output = Path("/proof/session.env")
        if member:
            assert not await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM user_global_role WHERE user_id=$1)", actor
            )
            output.write_text(
                output.read_text() + "SURVEY_MEMBER_SESSION=" + token + "\n"
            )
        else:
            output.write_text("SURVEY_ADMIN_SESSION=" + token + "\n")
        output.chmod(0o600)
        print(
            "PASS: PostgreSQL snapshot roundtrip, immutable version, cascade cleanup, real API identity and readiness"
        )
    finally:
        await connection.close()


asyncio.run(main())
