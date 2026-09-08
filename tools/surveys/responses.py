"""Live response API contract; no mocked service or persistence."""

import asyncio
import json
import os
import secrets
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx


async def main():
    survey = uuid4()
    survey_ids = [survey]
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    token = Path("/proof/session.env").read_text().strip().split("=", 1)[1]
    auth = {"__Host-leonaid_session": token}
    definition = json.loads(Path("tests/fixtures/surveys/krapfentaxi.json").read_text())
    async with httpx.AsyncClient(base_url="http://api:8000") as client:

        async def call(method, path, *, body=None, cookies=None, expected=200):
            response = await client.request(method, path, json=body, cookies=cookies)
            assert response.status_code == expected, (
                path,
                response.status_code,
                response.text,
            )
            return response.json()

        admin = f"/api/v1/surveys/{survey}"
        public = f"/api/v1/public/surveys/{survey}"
        try:
            body = {
                "operationId": "create",
                "title": "Synthetic Krapfentaxi",
                "definition": definition,
                "inactivityTimeoutSeconds": 1,
            }
            await call("POST", admin, body=body, expected=401)
            created = await call("POST", admin, body=body, cookies=auth)
            assert created == await call("POST", admin, body=body, cookies=auth)
            version = await call(
                "POST",
                admin + "/publish",
                body={"operationId": "publish", "expectedRevision": 1},
                cookies=auth,
            )
            assert (await call("GET", public))["id"] == version["id"]
            secret = secrets.token_urlsafe(48)
            start = {"operationId": "start", "resumeSecret": secret}
            participation = await call("POST", public + "/participations", body=start)
            assert participation == await call(
                "POST", public + "/participations", body=start
            )
            pid = participation["id"]
            path = public + "/participations/" + pid
            cookies = {f"__Host-survey_{pid}": secret}
            # Raw client deliberately bypasses renderer validation.
            for invalid in [
                {"delivery_rating": True},
                {"delivery_rating": 100},
                {"freshness": "forged"},
                {"unknown": "x"},
            ]:
                await call(
                    "PUT",
                    path,
                    body={
                        "operationId": str(uuid4()),
                        "expectedRevision": 1,
                        "answers": invalid,
                    },
                    cookies=cookies,
                    expected=422,
                )
            save = {
                "operationId": "save-1",
                "expectedRevision": 1,
                "answers": {
                    "delivery_rating": 1,
                    "delivery_feedback": "Later than expected",
                },
                "currentPage": "experience",
            }
            first = await call("PUT", path, body=save, cookies=cookies)
            assert first["revision"] == 2
            assert first == await call("PUT", path, body=save, cookies=cookies)
            await call(
                "PUT", path, body={**save, "answers": {}}, cookies=cookies, expected=409
            )
            await call(
                "PUT",
                path,
                body={**save, "operationId": "stale"},
                cookies=cookies,
                expected=409,
            )
            await call(
                "POST",
                path + "/complete",
                body={"operationId": "incomplete", "expectedRevision": 2},
                cookies=cookies,
                expected=422,
            )
            restored = await call("GET", path, cookies=cookies)
            assert restored["response"]["answers"] == save["answers"]
            assert restored["response"]["revision"] == 2
            # Exercise the actual configured one-second inactivity interval.
            await asyncio.sleep(1.2)
            assert (await call("GET", path, cookies=cookies))["response"][
                "status"
            ] == "partial"
            revised = await call(
                "PUT",
                path,
                body={
                    "operationId": "save-2",
                    "expectedRevision": 2,
                    "answers": {
                        "delivery_rating": 5,
                        "delivery_feedback": "obsolete",
                        "freshness": "fresh",
                        "nps": 9,
                    },
                    "currentPage": "recommendation",
                },
                cookies=cookies,
            )
            assert (
                revised["status"] == "in_progress"
                and "delivery_feedback" not in revised["answers"]
            )
            complete = {"operationId": "complete", "expectedRevision": 3}
            final = await call(
                "POST", path + "/complete", body=complete, cookies=cookies
            )
            assert final["status"] == "completed"
            assert final == await call(
                "POST", path + "/complete", body=complete, cookies=cookies
            )
            await call(
                "PUT",
                path,
                body={**save, "expectedRevision": 4, "operationId": "late"},
                cookies=cookies,
                expected=409,
            )
            # A wrong credential never grants access, even to a known participation ID.
            await call(
                "GET", path, cookies={f"__Host-survey_{pid}": "z" * 64}, expected=404
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM survey_participation WHERE survey_id=$1",
                    survey,
                )
                == 1
            )
            stored = json.loads(
                await conn.fetchval(
                    "SELECT answers::text FROM survey_participation WHERE id=$1",
                    UUID(pid),
                )
            )
            assert stored == {"delivery_rating": 5, "freshness": "fresh", "nps": 9}
            golf_id = uuid4()
            survey_ids.append(golf_id)
            golf_admin = f"/api/v1/surveys/{golf_id}"
            golf_definition = json.loads(
                Path("tests/fixtures/surveys/golf.json").read_text()
            )
            await call(
                "POST",
                golf_admin,
                body={
                    "operationId": "golf-create",
                    "title": "Synthetic Golf",
                    "definition": golf_definition,
                },
                cookies=auth,
            )
            await call(
                "POST",
                golf_admin + "/publish",
                body={"operationId": "golf-publish", "expectedRevision": 1},
                cookies=auth,
            )
            golf_secret = secrets.token_urlsafe(48)
            golf_public = f"/api/v1/public/surveys/{golf_id}/participations"
            golf = await call(
                "POST",
                golf_public,
                body={"operationId": "golf-start", "resumeSecret": golf_secret},
            )
            golf_path = golf_public + "/" + golf["id"]
            golf_cookies = {f"__Host-survey_{golf['id']}": golf_secret}
            await call(
                "PUT",
                golf_path,
                body={
                    "operationId": "matrix-partial",
                    "expectedRevision": 1,
                    "answers": {"event_rating": {"organization": 3}},
                },
                cookies=golf_cookies,
            )
            await call(
                "POST",
                golf_path + "/complete",
                body={"operationId": "matrix-incomplete", "expectedRevision": 2},
                cookies=golf_cookies,
                expected=422,
            )
            await call(
                "PUT",
                golf_path,
                body={
                    "operationId": "matrix-full",
                    "expectedRevision": 2,
                    "answers": {
                        "event_rating": {"organization": 3, "course": 2, "catering": 1},
                        "improvements": ["food"],
                        "food_feedback": "More options",
                    },
                },
                cookies=golf_cookies,
            )
            assert (
                await call(
                    "POST",
                    golf_path + "/complete",
                    body={"operationId": "golf-complete", "expectedRevision": 3},
                    cookies=golf_cookies,
                )
            )["status"] == "completed"
            print(
                "PASS: live create/publish/start/save/restore/complete, partial timeout, hidden cleanup, invalid answers, revisions, idempotency and credentials"
            )
        finally:
            await conn.execute(
                "DELETE FROM survey WHERE id=ANY($1::uuid[])", survey_ids
            )
            await conn.close()


asyncio.run(main())
