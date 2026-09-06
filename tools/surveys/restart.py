"""Persisted request ordering and terminal completion across actual process restarts."""

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path
from uuid import UUID, uuid4
import asyncpg
import httpx


async def main():
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    token = next(
        line.split("=", 1)[1]
        for line in Path("/proof/session.env").read_text().splitlines()
        if line.startswith("SURVEY_ADMIN_SESSION=")
    )
    state_file = Path("/proof/restart-state.json")
    async with httpx.AsyncClient(base_url="http://api:8000") as client:

        async def call(method, path, body=None, cookie=None, expected=200):
            client.cookies.clear()
            response = await client.request(
                method, path, json=body, headers={"Cookie": cookie} if cookie else {}
            )
            assert response.status_code == expected, (
                path,
                response.status_code,
                expected,
            )
            return response.json()

        if sys.argv[1] == "prepare":
            sid = str(uuid4())
            admin = f"/api/v1/surveys/{sid}"
            auth = f"__Host-leonaid_session={token}"
            await call(
                "POST",
                admin,
                {
                    "operationId": "create",
                    "title": "Synthetic process restart",
                    "inactivityTimeoutSeconds": 1800,
                    "definition": {
                        "pages": [
                            {
                                "name": "one",
                                "elements": [{"type": "text", "name": "answer"}],
                            }
                        ]
                    },
                },
                auth,
            )
            await call(
                "POST",
                admin + "/publish",
                {"operationId": "publish", "expectedRevision": 1},
                auth,
            )
            state = {"survey": sid, "participants": []}
            for completed in [False, True]:
                secret = secrets.token_urlsafe(48)
                start = {"operationId": str(uuid4()), "resumeSecret": secret}
                public = f"/api/v1/public/surveys/{sid}/participations"
                initial = await call("POST", public, start)
                assert initial == await call("POST", public, start)
                path = public + "/" + initial["id"]
                cookie = f"__Host-survey_{initial['id']}={secret}"
                old = {
                    "operationId": "old",
                    "expectedRevision": 1,
                    "answers": {"answer": "Older answer"},
                }
                first = await call("PUT", path, old, cookie)
                new = {
                    "operationId": "new",
                    "expectedRevision": 2,
                    "answers": {"answer": "Winning answer"},
                }
                second = await call("PUT", path, new, cookie)
                assert first == await call("PUT", path, old, cookie)
                await call(
                    "PUT", path, {**old, "operationId": "delayed-stale"}, cookie, 409
                )
                assert (await call("GET", path, cookie=cookie))["response"] == second
                finish = {
                    "operationId": "finish",
                    "expectedRevision": second["revision"],
                }
                if completed:
                    final = await call("POST", path + "/complete", finish, cookie)
                    assert final == await call(
                        "POST", path + "/complete", finish, cookie
                    )
                else:
                    final = second
                state["participants"].append(
                    {
                        "id": initial["id"],
                        "start": start,
                        "initial": initial,
                        "old": old,
                        "first": first,
                        "new": new,
                        "second": second,
                        "finish": finish,
                        "final": final,
                        "completed": completed,
                    }
                )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM survey_participation WHERE survey_id=$1",
                    UUID(sid),
                )
                == 2
            )
            state_file.write_text(json.dumps(state))
            print(
                "PASS: duplicate start/save and reordered stale writes preserve newer answers; completed and incomplete snapshots prepared for real API/worker restart"
            )
        else:
            state = json.loads(state_file.read_text())
            sid = state["survey"]
            public = f"/api/v1/public/surveys/{sid}/participations"
            for p in state["participants"]:
                path = public + "/" + p["id"]
                cookie = f"__Host-survey_{p['id']}={p['start']['resumeSecret']}"
                # Every replay is served by new API/worker processes from persisted ledgers.
                assert await call("POST", public, p["start"]) == p["initial"]
                restored = await call("GET", path, cookie=cookie)
                assert restored["response"] == p["final"]
                assert await call("PUT", path, p["old"], cookie) == p["first"]
                assert await call("PUT", path, p["new"], cookie) == p["second"]
                assert (await call("GET", path, cookie=cookie))["response"] == p[
                    "final"
                ]
                await call(
                    "PUT",
                    path,
                    {**p["old"], "answers": {"answer": "Key misuse"}},
                    cookie,
                    409,
                )
                if not p["completed"]:
                    await call(
                        "PUT",
                        path,
                        {**p["old"], "operationId": "stale-after-restart"},
                        cookie,
                        409,
                    )
                    changed = await call(
                        "PUT",
                        path,
                        {
                            "operationId": "resume",
                            "expectedRevision": p["second"]["revision"],
                            "answers": {"answer": "Resumed after restart"},
                        },
                        cookie,
                    )
                    p["finish"] = {
                        "operationId": "finish",
                        "expectedRevision": changed["revision"],
                    }
                    p["final"] = await call(
                        "POST", path + "/complete", p["finish"], cookie
                    )
                assert (
                    await call("POST", path + "/complete", p["finish"], cookie)
                    == p["final"]
                )
                await call(
                    "POST",
                    path + "/complete",
                    {**p["finish"], "operationId": "another-completion"},
                    cookie,
                    409,
                )
                await call(
                    "PUT",
                    path,
                    {
                        "operationId": "late-edit",
                        "expectedRevision": p["final"]["revision"],
                        "answers": {"answer": "Must never persist"},
                    },
                    cookie,
                    409,
                )
                assert (await call("GET", path, cookie=cookie))["response"] == p[
                    "final"
                ]
                row = await conn.fetchrow(
                    "SELECT revision,status,answers,completed_at FROM survey_participation WHERE id=$1",
                    UUID(p["id"]),
                )
                assert (
                    row["revision"] == p["final"]["revision"]
                    and row["status"] == "completed"
                )
                assert json.loads(row["answers"]) == p["final"]["answers"]
                assert row["completed_at"].isoformat() == p["final"]["completedAt"]
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM survey_operation WHERE survey_id=$1 AND scope=$2",
                        UUID(sid),
                        f"participation:{p['id']}:complete",
                    )
                    == 1
                )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM survey_participation WHERE survey_id=$1",
                    UUID(sid),
                )
                == 2
            )
            await conn.execute("DELETE FROM survey WHERE id=$1", UUID(sid))
            state_file.unlink()
            print(
                "PASS: actual API/worker restart retains exact operation results; no duplicate participations/completions, stale writes rejected, incomplete participation resumes and terminal answers/revisions survive"
            )
    await conn.close()


asyncio.run(main())
