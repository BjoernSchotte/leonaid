"""Real timeout settings, lagged classification and worker-restart acceptance."""

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest


async def main():
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    token = Path("/proof/session.env").read_text().strip().split("=", 1)[1]
    auth = {"__Host-leonaid_session": token}
    state_file = Path("/proof/timeout-state.json")
    async with httpx.AsyncClient(base_url="http://api:8000") as client:

        async def call(method, path, body=None, cookies=None, expected=200):
            response = await client.request(method, path, json=body, cookies=cookies)
            assert response.status_code == expected, (
                path,
                response.status_code,
                response.text,
            )
            return response.json()

        async def settings(value, previous, operation=None, expected=200):
            body = {
                "operationId": operation or str(uuid4()),
                "expectedRevision": previous["revision"],
                "inactivityTimeoutSeconds": value,
            }
            return await call("PUT", "/api/v1/survey-settings", body, auth, expected)

        if sys.argv[1] == "prepare":
            initial = await call("GET", "/api/v1/survey-settings", cookies=auth)
            await call("GET", "/api/v1/survey-settings", expected=401)
            first = await settings(20, initial, "timeout-default")
            assert first == await settings(20, initial, "timeout-default")
            await settings(21, initial, "timeout-default", expected=409)
            await settings(21, initial, expected=409)
            for invalid in [0, -1, 604801, True, 1.5, None]:
                await settings(invalid, first, expected=422)
            assert await call("GET", "/api/v1/survey-settings", cookies=auth) == first
            survey = str(uuid4())
            admin = f"/api/v1/surveys/{survey}"
            public = f"/api/v1/public/surveys/{survey}/participations"
            definition = {
                "pages": [
                    {"name": "one", "elements": [{"type": "text", "name": "feedback"}]},
                    {"name": "two", "elements": [{"type": "text", "name": "notes"}]},
                ]
            }
            await call(
                "POST",
                admin,
                {
                    "operationId": "create",
                    "title": "Synthetic timeout checks",
                    "definition": definition,
                },
                auth,
            )
            await call(
                "POST",
                admin + "/publish",
                {"operationId": "publish", "expectedRevision": 1},
                auth,
            )

            async def start(expected_timeout):
                secret = secrets.token_urlsafe(48)
                body = {"operationId": str(uuid4()), "resumeSecret": secret}
                p = await call("POST", public, body)
                assert p == await call("POST", public, body)
                assert p["inactivityTimeoutSeconds"] == expected_timeout
                return {"id": p["id"], "secret": secret, "timeout": expected_timeout}

            old = await start(20)
            changed_default = await settings(40, first)
            inherited = await start(40)
            summary = await call("GET", admin, cookies=auth)
            override = {
                "operationId": "override",
                "expectedRevision": summary["revision"],
                "inactivityTimeoutSeconds": 3,
            }
            # A real authenticated member has neither global-admin nor survey-design access.
            member_id = uuid4()
            member_token = secrets.token_urlsafe(48)
            now = datetime.now(timezone.utc)
            await conn.execute(
                "INSERT INTO user_account(id,email,display_name,status,email_verified_at) VALUES($1,$2,'Timeout member','active',$3)",
                member_id,
                f"{member_id}@example.invalid",
                now,
            )
            await conn.execute(
                "INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$5,$5,$5)",
                uuid4(),
                member_id,
                session_token_digest(member_token),
                now + SESSION_LIFETIME,
                now,
            )
            member = {"__Host-leonaid_session": member_token}
            try:
                await call(
                    "GET", "/api/v1/survey-settings", cookies=member, expected=403
                )
                await call(
                    "PUT",
                    "/api/v1/survey-settings",
                    {
                        "operationId": "denied",
                        "expectedRevision": changed_default["revision"],
                        "inactivityTimeoutSeconds": 50,
                    },
                    member,
                    403,
                )
                await call("PUT", admin + "/settings", override, member, 404)
            finally:
                await conn.execute("DELETE FROM user_account WHERE id=$1", member_id)
            assert (
                await call("GET", "/api/v1/survey-settings", cookies=auth)
                == changed_default
            )
            assert await call("GET", admin, cookies=auth) == summary
            updated = await call("PUT", admin + "/settings", override, auth)
            assert updated == await call("PUT", admin + "/settings", override, auth)
            await call(
                "PUT",
                admin + "/settings",
                {**override, "operationId": "stale"},
                auth,
                409,
            )
            short = await start(3)
            await call(
                "PUT",
                admin + "/settings",
                {
                    "operationId": "inherit",
                    "expectedRevision": updated["revision"],
                    "inactivityTimeoutSeconds": None,
                },
                auth,
            )
            reset = await start(40)
            for p in [old, inherited, short, reset]:
                row = await conn.fetchrow(
                    "SELECT * FROM survey_participation WHERE id=$1", UUID(p["id"])
                )
                assert row["inactivity_timeout_seconds"] == p["timeout"]
            path = public + "/" + short["id"]
            cookie = {f"__Host-survey_{short['id']}": short["secret"]}
            saved = await call(
                "PUT",
                path,
                {
                    "operationId": "answer",
                    "expectedRevision": 1,
                    "answers": {"feedback": "Synthetic retained answer"},
                    "currentPage": "one",
                },
                cookie,
            )
            assert saved["revision"] == 2
            # Fixture time injection, using the DB clock, avoids wall-clock sleeps.
            await conn.execute(
                "UPDATE survey_participation SET last_answer_changed_at=statement_timestamp()-interval '10 seconds' WHERE id=$1",
                UUID(short["id"]),
            )
            before = await conn.fetchrow(
                "SELECT * FROM survey_participation WHERE id=$1", UUID(short["id"])
            )
            assert before["status"] == "in_progress"  # actual worker is stopped
            restored = await call("GET", path, cookies=cookie)
            assert restored["response"]["status"] == "partial"
            assert (
                await conn.fetchval(
                    "SELECT effective_status FROM survey_participation_effective WHERE id=$1",
                    UUID(short["id"]),
                )
                == "partial"
            )
            page_only = await call(
                "PUT",
                path,
                {
                    "operationId": "page-only",
                    "expectedRevision": 2,
                    "answers": saved["answers"],
                    "currentPage": "two",
                },
                cookie,
            )
            assert page_only["status"] == "partial"
            after = await conn.fetchrow(
                "SELECT * FROM survey_participation WHERE id=$1", UUID(short["id"])
            )
            assert after["last_answer_changed_at"] == before["last_answer_changed_at"]
            assert after["answers"] == before["answers"]
            assert after["revision"] == 3 and after["status"] == "in_progress"
            state_file.write_text(
                json.dumps(
                    {
                        "survey": survey,
                        "short": short,
                        "settings": changed_default,
                        "initial": initial,
                        "lastChanged": after["last_answer_changed_at"].isoformat(),
                    }
                )
            )
            print(
                "PASS: revisioned/idempotent default and override settings; immutable timeout snapshots; lagged API/view classification; page-only save does not extend inactivity"
            )
        else:
            state = json.loads(state_file.read_text())
            short = state["short"]
            pid = UUID(short["id"])
            for _ in range(60):
                row = await conn.fetchrow(
                    "SELECT * FROM survey_participation WHERE id=$1", pid
                )
                if row["status"] == "partial":
                    break
                await asyncio.sleep(0.25)
            assert row["status"] == "partial", "Restarted real worker did not catch up"
            assert row["revision"] == 3
            assert row["last_answer_changed_at"].isoformat() == state["lastChanged"]
            assert json.loads(row["answers"]) == {
                "feedback": "Synthetic retained answer"
            }
            path = (
                f"/api/v1/public/surveys/{state['survey']}/participations/{short['id']}"
            )
            cookie = {f"__Host-survey_{short['id']}": short["secret"]}
            changed = await call(
                "PUT",
                path,
                {
                    "operationId": "resume",
                    "expectedRevision": 3,
                    "answers": {"feedback": "Changed after timeout"},
                },
                cookie,
            )
            assert changed["status"] == "in_progress" and changed["revision"] == 4
            final_body = {"operationId": "complete", "expectedRevision": 4}
            final = await call("POST", path + "/complete", final_body, cookie)
            assert final == await call("POST", path + "/complete", final_body, cookie)
            assert final["status"] == "completed"
            await conn.execute(
                "UPDATE survey_participation SET last_answer_changed_at=statement_timestamp()-interval '10 seconds' WHERE id=$1",
                pid,
            )
            # The real worker remains running; completed data stays terminal across a sweep.
            await asyncio.sleep(5.5)
            row = await conn.fetchrow(
                "SELECT * FROM survey_participation WHERE id=$1", pid
            )
            assert row["status"] == "completed" and row["revision"] == 5
            assert json.loads(row["answers"]) == {"feedback": "Changed after timeout"}
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM survey_participation WHERE survey_id=$1",
                    UUID(state["survey"]),
                )
                == 4
            )
            await settings(
                state["initial"]["inactivityTimeoutSeconds"], state["settings"]
            )
            await conn.execute("DELETE FROM survey WHERE id=$1", UUID(state["survey"]))
            print(
                "PASS: actual worker restart catches up without changing answers/revision; same participation resumes/completes; repeated sweeps retain terminal data"
            )
    await conn.close()


asyncio.run(main())
