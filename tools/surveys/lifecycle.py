"""Real API/PostgreSQL lifecycle, version and concurrency acceptance."""

import asyncio
import os
import secrets
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx


async def main():
    token = next(
        line.split("=", 1)[1]
        for line in Path("/proof/session.env").read_text().splitlines()
        if line.startswith("SURVEY_ADMIN_SESSION=")
    )
    auth = {"Cookie": f"__Host-leonaid_session={token}"}
    definition = {
        "title": "Synthetic lifecycle",
        "pages": [{"name": "page", "elements": [{"type": "text", "name": "note"}]}],
    }
    ids = []
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    async with httpx.AsyncClient(base_url="http://api:8000") as client:

        async def request(method, path, body=None, *, headers=auth, expected=200):
            response = await client.request(method, path, json=body, headers=headers)
            assert response.status_code == expected, (
                path,
                response.status_code,
                response.text,
            )
            return response.json()

        async def create(status="draft"):
            sid = uuid4()
            ids.append(sid)
            await request(
                "POST",
                f"/api/v1/surveys/{sid}",
                {
                    "operationId": "create",
                    "title": "Synthetic lifecycle",
                    "definition": definition,
                },
            )
            if status != "draft":
                await request(
                    "POST",
                    f"/api/v1/surveys/{sid}/publish",
                    {"operationId": "publish", "expectedRevision": 1},
                )
            for action in {
                "draft": [],
                "active": [],
                "ended": ["end"],
                "archived": ["end", "archive"],
                "deleted": ["trash"],
            }[status]:
                await transition(sid, action)
            return sid

        async def summary(sid):
            return await request("GET", f"/api/v1/surveys/{sid}")

        async def transition(sid, action, **kwargs):
            revision = (await summary(sid))["revision"]
            return await request(
                "POST",
                f"/api/v1/surveys/{sid}/transition",
                {
                    "operationId": str(uuid4()),
                    "expectedRevision": revision,
                    "action": action,
                },
                **kwargs,
            )

        async def start(sid):
            secret = secrets.token_urlsafe(48)
            result = await request(
                "POST",
                f"/api/v1/public/surveys/{sid}/participations",
                {"operationId": str(uuid4()), "resumeSecret": secret},
                headers={},
            )
            return result, {"Cookie": f"__Host-survey_{result['id']}={secret}"}

        try:
            allowed = {
                "draft": {"trash"},
                "active": {"end", "trash"},
                "ended": {"archive", "trash"},
                "archived": {"unarchive", "trash"},
                "deleted": {"restore"},
            }
            for status, actions in allowed.items():
                for action in ["end", "archive", "unarchive", "trash", "restore"]:
                    sid = await create(status)
                    if action in actions:
                        result = await transition(sid, action)
                        target = {
                            "end": "ended",
                            "archive": "archived",
                            "unarchive": "ended",
                            "trash": "deleted",
                            "restore": "ended",
                        }[action]
                        assert result["status"] == target
                        assert bool(result["deletedAt"]) == (target == "deleted")
                    else:
                        before = await summary(sid)
                        response = await client.post(
                            f"/api/v1/surveys/{sid}/transition",
                            headers=auth,
                            json={
                                "operationId": str(uuid4()),
                                "expectedRevision": before["revision"],
                                "action": action,
                            },
                        )
                        assert response.status_code in (409, 422), (
                            status,
                            action,
                            response.text,
                        )
                        assert await summary(sid) == before
            # Restoring an unpublished draft is the only restore-to-draft edge.
            draft_id = await create()
            await transition(draft_id, "trash")
            assert (await transition(draft_id, "restore"))["status"] == "draft"

            sid = await create("active")
            base = f"/api/v1/surveys/{sid}"
            old, old_auth = await start(sid)
            updates = [
                {
                    "operationId": str(uuid4()),
                    "expectedRevision": 2,
                    "definition": dict(definition, title=title),
                }
                for title in ("Version two A", "Version two B")
            ]
            writes = await asyncio.gather(
                *(
                    client.put(base + "/draft", headers=auth, json=body)
                    for body in updates
                )
            )
            assert sorted(r.status_code for r in writes) == [200, 409]
            published = await request(
                "POST", base + "/publish", {"operationId": "v2", "expectedRevision": 3}
            )
            winning = next(r.json() for r in writes if r.status_code == 200)
            assert published["definition"] == winning["definition"]
            assert published["number"] == 2
            newer, _ = await start(sid)
            assert newer["version"]["id"] == published["id"] != old["version"]["id"]
            restored = await request(
                "GET",
                f"/api/v1/public/surveys/{sid}/participations/{old['id']}",
                headers=old_auth,
            )
            assert restored["version"] == old["version"]
            publishes = await asyncio.gather(
                *(
                    client.post(
                        base + "/publish",
                        headers=auth,
                        json={"operationId": str(uuid4()), "expectedRevision": 4},
                    )
                    for _ in range(2)
                )
            )
            assert sorted(r.status_code for r in publishes) == [200, 409]
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM survey_version WHERE survey_id=$1", sid
                )
                == 3
            )

            # Both operations contend on the same survey row; either legal ordering is valid.
            participation, credentials = await start(sid)
            response_path = (
                f"/api/v1/public/surveys/{sid}/participations/{participation['id']}"
            )
            rev = (await summary(sid))["revision"]
            close_body = {
                "operationId": "end-race",
                "expectedRevision": rev,
                "action": "end",
            }
            ended, completion = await asyncio.gather(
                client.post(base + "/transition", headers=auth, json=close_body),
                client.post(
                    response_path + "/complete",
                    headers=credentials,
                    json={"operationId": "complete-race", "expectedRevision": 1},
                ),
            )
            assert ended.status_code == 200
            assert completion.status_code in (200, 409)
            state = await conn.fetchval(
                "SELECT status FROM survey_participation WHERE id=$1",
                UUID(participation["id"]),
            )
            assert state == (
                "completed" if completion.status_code == 200 else "partial"
            )
            assert (
                await request("POST", base + "/transition", close_body)
            ) == ended.json()
            await request(
                "PUT",
                response_path,
                {
                    "operationId": "late",
                    "expectedRevision": 1,
                    "answers": {"note": "late"},
                },
                headers=credentials,
                expected=409,
            )
            await request(
                "GET", f"/api/v1/public/surveys/{sid}", headers={}, expected=409
            )
            await request(
                "PUT",
                base + "/draft",
                {
                    "operationId": "closed-edit",
                    "expectedRevision": 5,
                    "definition": definition,
                },
                expected=409,
            )

            target = uuid4()
            ids.append(target)
            copy_body = {
                "operationId": "copy",
                "expectedRevision": (await summary(sid))["revision"],
                "targetSurveyId": str(target),
                "title": "Repeat event",
            }
            copied = await request("POST", base + "/duplicate", copy_body)
            assert copied == await request("POST", base + "/duplicate", copy_body)
            assert copied["status"] == "draft" and copied["publishedVersionId"] is None
            for table in ("survey_participation", "survey_version", "survey_grant"):
                assert (
                    await conn.fetchval(
                        f"SELECT count(*) FROM {table} WHERE survey_id=$1", target
                    )
                    == 0
                )
            source_definition = await conn.fetchval(
                "SELECT definition FROM survey_version WHERE id=(SELECT published_version_id FROM survey WHERE id=$1)",
                sid,
            )
            assert (
                await conn.fetchval(
                    "SELECT definition FROM survey_draft WHERE survey_id=$1", target
                )
                == source_definition
            )
            assert (
                await conn.fetchval("SELECT action_id FROM survey WHERE id=$1", target)
                is None
            )
            await transition(sid, "archive")
            await transition(sid, "trash")
            assert (await transition(sid, "restore"))["status"] == "ended"
            await request(
                "GET", f"/api/v1/public/surveys/{sid}", headers={}, expected=409
            )
            await request("GET", base, headers={}, expected=401)
            print(
                "PASS: 25 lifecycle/action pairs, draft restore, stale edits/publication races, immutable versions, close/complete cutoff, idempotent end and isolated duplication"
            )
        finally:
            await conn.execute("DELETE FROM survey WHERE id=ANY($1::uuid[])", ids)
            await conn.close()


asyncio.run(main())
