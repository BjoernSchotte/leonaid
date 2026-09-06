"""Prove the minimal CMS profile contract using real Core HTTP and PostgreSQL."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx

from tools.identity.contract import KLARA_ID, SYSTEM_ID, create_session


async def main() -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        now = datetime.now(timezone.utc)
        system_token = await create_session(connection, SYSTEM_ID, now=now)
        charity_token = await create_session(connection, KLARA_ID, now=now)
        async with httpx.AsyncClient(base_url="http://api:8000", timeout=3) as client:
            anonymous = await client.get("/api/v1/identity/me")
            assert anonymous.status_code == 401
            assert anonymous.headers.get("cache-control") == "no-store"
            assert "email" not in anonymous.json()

            async def profile(token: str, expected_status: int = 200) -> dict[str, Any]:
                response = await client.get(
                    "/api/v1/identity/me",
                    headers={"Cookie": f"__Host-leonaid_session={token}"},
                )
                assert response.status_code == expected_status
                assert response.headers.get("cache-control") == "no-store"
                payload = response.json()
                assert isinstance(payload, dict)
                return payload

            system = await profile(system_token)
            charity = await profile(charity_token)
            for user_id, payload in [(SYSTEM_ID, system), (KLARA_ID, charity)]:
                email = await connection.fetchval(
                    "SELECT email FROM user_account WHERE id=$1", user_id
                )
                assert payload["userId"] == str(user_id)
                assert payload["email"] == email
            assert system["email"] != charity["email"]

            # This mutates synthetic fixture state, not the email-change workflow.
            # It proves that /me reflects the current authenticated account rather
            # than cached profile data, while the stable subject remains unchanged.
            await connection.execute(
                "UPDATE user_account SET email=$1 WHERE id=$2",
                "cms-profile-updated@leonaid.invalid",
                KLARA_ID,
            )
            updated = await profile(charity_token)
            assert updated["userId"] == charity["userId"]
            assert updated["email"] == "cms-profile-updated@leonaid.invalid"
            assert (await profile(system_token))["email"] == system["email"]

            await connection.execute(
                "UPDATE user_account SET status='suspended' WHERE id=$1", KLARA_ID
            )
            denied = await profile(charity_token, 401)
            assert "email" not in denied
            assert "userId" not in denied
    finally:
        await connection.close()
    print(
        "emdash-identity-profile: OK: authenticated own profile, mutable email, "
        "stable UUID, no-store and immediate suspension denial"
    )


if __name__ == "__main__":
    asyncio.run(main())
