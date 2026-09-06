"""Real member scope, list/count and action-link checks; ephemeral browser seeds."""

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path
from uuid import UUID, uuid4
from datetime import datetime, timezone

import asyncpg
import httpx
from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest


async def main():
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    if sys.argv[1] == "verify":
        data = json.loads(Path("/proof/module-result.json").read_text())
        row = await conn.fetchrow("SELECT * FROM survey WHERE id=$1", UUID(data["id"]))
        assert row["status"] == "ended" and row["inactivity_timeout_seconds"] == 3
        assert str(row["action_id"]) == data["actionId"]
        assert (
            await conn.fetchval(
                "SELECT inactivity_timeout_seconds FROM survey_settings WHERE singleton"
            )
            == 1800
        )
        print(
            "PASS: member lifecycle/restoration, action association and settings verified in PostgreSQL"
        )
        await conn.close()
        return
    token = Path("/proof/session.env").read_text().strip().split("=", 1)[1]
    admin = {"Cookie": f"__Host-leonaid_session={token}"}
    member, action = uuid4(), uuid4()
    secret = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    await conn.execute(
        "INSERT INTO user_account(id,email,display_name,status,email_verified_at) VALUES($1,$2,'Survey Designer','active',$3)",
        member,
        f"{member}@example.invalid",
        now,
    )
    await conn.execute(
        "INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$5,$5,$5)",
        uuid4(),
        member,
        session_token_digest(secret),
        now + SESSION_LIFETIME,
        now,
    )
    await conn.execute(
        "INSERT INTO charity_action(id,carrier_name,name,purpose,status,starts_on,ends_on,archive_slug,goal_value,actual_value,goal_unit,currency) VALUES($1,'Synthetic charity','Survey module action','Synthetic proof','draft','2026-09-01','2026-11-15',$2,0,0,'cent','EUR')",
        action,
        f"survey-module-{action}",
    )
    headers = {"Cookie": f"__Host-leonaid_session={secret}"}
    async with httpx.AsyncClient(base_url="http://api:8000") as client:

        async def request(method, path, body=None, auth=admin, expected=200):
            response = await client.request(method, path, json=body, headers=auth)
            assert response.status_code == expected, (
                path,
                response.status_code,
                response.text,
            )
            return response.json()

        ids = [uuid4() for _ in range(3)]
        definition = {
            "pages": [
                {
                    "name": "page",
                    "elements": [
                        {
                            "type": "text",
                            "name": "feedback",
                            "title": "Ihre Rückmeldung",
                        }
                    ],
                }
            ]
        }
        for sid, title, aid in [
            (ids[0], "Shared design fixture", None),
            (ids[1], "Action scoped fixture", str(action)),
            (ids[2], "Private unrelated fixture", None),
        ]:
            await request(
                "POST",
                f"/api/v1/surveys/{sid}",
                {
                    "operationId": "create",
                    "title": title,
                    "definition": definition,
                    "actionId": aid,
                },
            )
        for sid in ids[:2]:
            await conn.execute(
                "INSERT INTO survey_grant(survey_id,user_id,capability) VALUES($1,$2,'design')",
                sid,
                member,
            )
        listed = await request("GET", "/api/v1/surveys", auth=headers)
        assert (
            listed["total"] == 1
            and listed["items"][0]["id"] == str(ids[0])
            and listed["actions"] == []
        )
        assert listed["items"][0]["capabilities"] == ["design"]
        for sid in ids[1:]:
            await request("GET", f"/api/v1/surveys/{sid}", auth=headers, expected=404)
        assert (await request("GET", "/api/v1/surveys?search=Private", auth=headers))[
            "total"
        ] == 0
        await request("GET", "/api/v1/survey-settings", auth=headers, expected=403)
        await request(
            "POST",
            f"/api/v1/surveys/{ids[0]}/publish",
            {"operationId": "denied-publish", "expectedRevision": 1},
            headers,
            404,
        )
        await request(
            "POST",
            f"/api/v1/surveys/{ids[0]}/transition",
            {"operationId": "denied-trash", "expectedRevision": 1, "action": "trash"},
            headers,
            404,
        )
        await request(
            "POST",
            f"/api/v1/surveys/{uuid4()}",
            {
                "operationId": "denied-create",
                "title": "Forbidden link",
                "definition": definition,
                "actionId": str(action),
            },
            headers,
            404,
        )
        await conn.execute(
            "INSERT INTO action_membership(id,action_id,user_id,role) VALUES($1,$2,$3,'acquirer')",
            uuid4(),
            action,
            member,
        )
        listed = await request("GET", "/api/v1/surveys", auth=headers)
        assert listed["total"] == 2 and {v["id"] for v in listed["items"]} == {
            str(v) for v in ids[:2]
        }
        assert (
            listed["actions"] == []
        )  # membership permits granted design, not action management
        assert (await request("GET", "/api/v1/surveys?offset=1", auth=headers))[
            "total"
        ] == 2
        assert (
            len(
                (await request("GET", "/api/v1/surveys?offset=1", auth=headers))[
                    "items"
                ]
            )
            == 1
        )
        assert (await request("GET", "/api/v1/surveys?status=active", auth=headers))[
            "total"
        ] == 0
        await request("GET", "/api/v1/surveys?offset=-1", auth=headers, expected=422)
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM survey WHERE title='Forbidden link'"
            )
            == 0
        )
        with Path("/proof/session.env").open("a") as output:
            output.write(
                f"\nSURVEY_DESIGN_SESSION={secret}\nSURVEY_SHARED_ID={ids[0]}\nSURVEY_ACTION_ID={action}\nSURVEY_PRIVATE_ID={ids[2]}\n"
            )
        print(
            "PASS: real designer role, action-membership boundary, filtered list/search/count/pagination, denied publishing/settings/foreign creation"
        )
    await conn.close()


asyncio.run(main())
