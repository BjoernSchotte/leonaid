"""Scheduled closure against real API, database and stopped/restarted worker."""

import asyncio
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx


async def main():
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    token = Path("/proof/session.env").read_text().strip().split("=", 1)[1]
    auth = {"__Host-leonaid_session": token}
    state_file = Path("/proof/schedule-state.json")
    async with httpx.AsyncClient(base_url="http://api:8000") as client:

        async def call(method, path, body=None, cookies=None, expected=200):
            r = await client.request(method, path, json=body, cookies=cookies)
            assert r.status_code == expected, (path, r.status_code, r.text)
            return r.json()

        if sys.argv[1] == "prepare":
            sid = uuid4()
            admin = f"/api/v1/surveys/{sid}"
            public = f"/api/v1/public/surveys/{sid}/participations"
            await call(
                "POST",
                admin,
                {
                    "operationId": "create",
                    "title": "Synthetic scheduled closure",
                    "definition": {
                        "pages": [
                            {
                                "name": "one",
                                "elements": [{"type": "text", "name": "feedback"}],
                            }
                        ]
                    },
                },
                auth,
            )
            initial = await call("GET", admin, cookies=auth)
            future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
            body = {
                "operationId": "schedule",
                "expectedRevision": initial["revision"],
                "endsAt": future,
            }
            await call("PUT", admin + "/schedule", body, expected=401)
            for invalid in [
                "tomorrow",
                "2030-01-01T12:00:00",
                "2000-01-01T00:00:00Z",
                True,
            ]:
                await call(
                    "PUT", admin + "/schedule", {**body, "endsAt": invalid}, auth, 422
                )
            unchanged = await call("GET", admin, cookies=auth)
            assert unchanged == initial
            scheduled = await call("PUT", admin + "/schedule", body, auth)
            assert scheduled == await call("PUT", admin + "/schedule", body, auth)
            await call(
                "PUT", admin + "/schedule", {**body, "operationId": "stale"}, auth, 409
            )
            await call("PUT", admin + "/schedule", {**body, "endsAt": None}, auth, 409)
            assert datetime.fromisoformat(
                scheduled["endsAt"]
            ) == datetime.fromisoformat(future)
            # An expired draft cannot publish until its schedule is changed.
            await conn.execute(
                "UPDATE survey SET ends_at=statement_timestamp()-interval '1 second' WHERE id=$1",
                sid,
            )
            await call(
                "POST",
                admin + "/publish",
                {"operationId": "expired-publish", "expectedRevision": 1},
                auth,
                409,
            )
            cleared = await call(
                "PUT",
                admin + "/schedule",
                {
                    "operationId": "clear",
                    "expectedRevision": scheduled["revision"],
                    "endsAt": None,
                },
                auth,
            )
            assert cleared["endsAt"] is None
            await call(
                "POST",
                admin + "/publish",
                {"operationId": "publish", "expectedRevision": 1},
                auth,
            )
            current = await call("GET", admin, cookies=auth)
            body = {
                **body,
                "operationId": "active-schedule",
                "expectedRevision": current["revision"],
            }
            scheduled = await call("PUT", admin + "/schedule", body, auth)
            participants = []
            for completed in [False, True]:
                secret = secrets.token_urlsafe(48)
                p = await call(
                    "POST",
                    public,
                    {"operationId": str(uuid4()), "resumeSecret": secret},
                )
                cookie = {f"__Host-survey_{p['id']}": secret}
                path = public + "/" + p["id"]
                answer = {
                    "feedback": "Synthetic completed"
                    if completed
                    else "Synthetic partial"
                }
                saved = await call(
                    "PUT",
                    path,
                    {"operationId": "save", "expectedRevision": 1, "answers": answer},
                    cookie,
                )
                if completed:
                    saved = await call(
                        "POST",
                        path + "/complete",
                        {
                            "operationId": "complete",
                            "expectedRevision": saved["revision"],
                        },
                        cookie,
                    )
                participants.append(
                    {
                        "id": p["id"],
                        "revision": saved["revision"],
                        "answers": answer,
                        "completed": completed,
                    }
                )
                if not completed:
                    pending_path, pending_cookie = path, cookie
            await conn.execute(
                "UPDATE survey SET ends_at=statement_timestamp()-interval '1 second' WHERE id=$1",
                sid,
            )
            assert (
                await conn.fetchval("SELECT status FROM survey WHERE id=$1", sid)
                == "active"
            )
            await call(
                "POST",
                public,
                {
                    "operationId": "late-start",
                    "resumeSecret": secrets.token_urlsafe(48),
                },
                expected=409,
            )
            await call(
                "PUT",
                pending_path,
                {
                    "operationId": "late-save",
                    "expectedRevision": 2,
                    "answers": {"feedback": "Must never persist"},
                },
                pending_cookie,
                409,
            )
            await call(
                "POST",
                pending_path + "/complete",
                {"operationId": "late-complete", "expectedRevision": 2},
                pending_cookie,
                409,
            )
            await call(
                "PUT",
                admin + "/schedule",
                {
                    "operationId": "late-clear",
                    "expectedRevision": scheduled["revision"],
                    "endsAt": None,
                },
                auth,
                409,
            )
            assert scheduled == await call("PUT", admin + "/schedule", body, auth)
            state_file.write_text(
                json.dumps(
                    {
                        "survey": str(sid),
                        "revision": scheduled["revision"],
                        "participants": participants,
                    }
                )
            )
            print(
                "PASS: schedule validation, revision/replay, expired draft and active deadline rejection with actual worker stopped"
            )
        else:
            state = json.loads(state_file.read_text())
            sid = UUID(state["survey"])
            for _ in range(80):
                row = await conn.fetchrow(
                    "SELECT status,revision FROM survey WHERE id=$1", sid
                )
                if row["status"] == "ended":
                    break
                await asyncio.sleep(0.25)
            assert row["status"] == "ended", (
                "Real restarted worker did not close scheduled survey"
            )
            assert row["revision"] == state["revision"] + 1
            for p in state["participants"]:
                actual = await conn.fetchrow(
                    "SELECT status,revision,answers FROM survey_participation WHERE id=$1",
                    UUID(p["id"]),
                )
                assert actual["status"] == (
                    "completed" if p["completed"] else "partial"
                )
                assert actual["revision"] == p["revision"]
                assert json.loads(actual["answers"]) == p["answers"]
            # A further real worker sweep must not close/revise the same survey twice.
            await asyncio.sleep(5.5)
            assert (
                await conn.fetchval("SELECT revision FROM survey WHERE id=$1", sid)
                == state["revision"] + 1
            )
            await call(
                "PUT",
                f"/api/v1/surveys/{sid}/schedule",
                {
                    "operationId": "reopen",
                    "expectedRevision": state["revision"] + 1,
                    "endsAt": None,
                },
                auth,
                409,
            )
            await conn.execute("DELETE FROM survey WHERE id=$1", sid)
            state_file.unlink()
            print(
                "PASS: real worker restart durably closes once; partial and completed answers/revisions preserved; reopening rejected"
            )
    await conn.close()


asyncio.run(main())
