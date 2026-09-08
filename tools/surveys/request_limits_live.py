"""Real HTTP/PostgreSQL quota boundaries; only near-limit counters are seeded."""

import asyncio
import json
import os
import secrets
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx


async def main():
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    token = Path("/proof/session.env").read_text().strip().split("=", 1)[1]
    sid = uuid4()
    admin = f"/api/v1/surveys/{sid}"
    public = f"/api/v1/public/surveys/{sid}"
    # A reserved synthetic proxy address isolates this quota fixture from earlier
    # cases and Docker's possible reuse of a just-removed container's address.
    async with httpx.AsyncClient(
        base_url="http://api:8000", headers={"X-Forwarded-For": "198.19.255.1"}
    ) as client:
        auth = {"Cookie": f"__Host-leonaid_session={token}"}
        response = await client.post(
            admin,
            headers=auth,
            json={
                "operationId": "create",
                "title": "Synthetic request quota",
                "definition": {
                    "pages": [
                        {
                            "name": "one",
                            "elements": [{"type": "text", "name": "answer"}],
                        }
                    ]
                },
            },
        )
        assert response.status_code == 200
        response = await client.post(
            admin + "/publish",
            headers=auth,
            json={"operationId": "publish", "expectedRevision": 1},
        )
        assert response.status_code == 200
        secret = secrets.token_urlsafe(48)
        start = {"operationId": "start", "resumeSecret": secret}
        response = await client.post(public + "/participations", json=start)
        assert response.status_code == 200
        pid = response.json()["id"]
        path = public + "/participations/" + pid
        resume = {"Cookie": f"__Host-survey_{pid}={secret}"}

        async def remaining_one(scope, limit):
            # Preserve the real transport-generated HMAC and timestamp; synthesize
            # only preceding attempts to avoid hundreds of redundant HTTP calls.
            row = await conn.fetchrow(
                "SELECT fingerprint_hash,attempted_at FROM security_rate_attempt WHERE scope=$1 ORDER BY attempted_at DESC LIMIT 1",
                scope,
            )
            assert row is not None
            count = await conn.fetchval(
                "SELECT count(*) FROM security_rate_attempt WHERE scope=$1 AND fingerprint_hash=$2 AND attempted_at >= now()-interval '60 seconds'",
                scope,
                row["fingerprint_hash"],
            )
            await conn.executemany(
                "INSERT INTO security_rate_attempt(id,scope,fingerprint_hash,attempted_at) VALUES($1,$2,$3,$4)",
                [
                    (uuid4(), scope, row["fingerprint_hash"], row["attempted_at"])
                    for _ in range(limit - 1 - count)
                ],
            )

        def denied(response):
            assert response.status_code == 429
            assert response.headers["Retry-After"] == "60"
            assert "request_rate_limited" in response.text
            assert secret not in response.text and token not in response.text

        await remaining_one("survey.public.start", 30)
        # Actual concurrent transactions compete for the last remaining permit.
        results = await asyncio.gather(
            *[
                client.post(
                    public + "/participations",
                    json={
                        "operationId": str(uuid4()),
                        "resumeSecret": secrets.token_urlsafe(48),
                    },
                )
                for _ in range(2)
            ]
        )
        statuses = sorted(r.status_code for r in results)
        assert statuses == [200, 429], statuses
        denied(next(r for r in results if r.status_code == 429))
        count = await conn.fetchval(
            "SELECT count(*) FROM survey_participation WHERE survey_id=$1", sid
        )
        assert count == 2
        for blocked_path in (
            public + "/participations",
            f"/api/v1/public/surveys/{sid.hex}/participations",
            f"/api/v1/public/surveys/urn:uuid:{sid}/participations",
            f"/api/v1/public/surveys/{uuid4()}/participations",
            public + "/invitation/redeem",
        ):
            denied(
                await client.post(
                    blocked_path,
                    json=start,
                    headers={
                        "User-Agent": "changed-client",
                        "Cookie": "__Host-leonaid_session=changed-cookie",
                    },
                )
            )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM survey_participation WHERE survey_id=$1", sid
            )
            == count
        )

        save = {
            "operationId": "save",
            "expectedRevision": 1,
            "answers": {"answer": "ACKNOWLEDGED"},
            "currentPage": "one",
        }
        response = await client.put(path, json=save, headers=resume)
        assert response.status_code == 200
        await remaining_one("survey.public.write", 300)
        assert (await client.put(path, json=save, headers=resume)).status_code == 200
        denied(
            await client.put(
                path,
                json={
                    **save,
                    "operationId": "blocked-save",
                    "expectedRevision": 2,
                    "answers": {"answer": "REJECTED"},
                },
                headers=resume,
            )
        )
        denied(
            await client.post(
                path + "/complete",
                json={"operationId": "blocked-complete", "expectedRevision": 2},
                headers=resume,
            )
        )
        denied(
            await client.put(
                path.replace(str(sid), sid.hex).replace(pid, pid.replace("-", "")),
                json=save,
                headers=resume,
            )
        )
        row = await conn.fetchrow(
            "SELECT answers,revision,status FROM survey_participation WHERE id=$1",
            UUID(pid),
        )
        assert json.loads(row["answers"]) == {"answer": "ACKNOWLEDGED"}
        assert row["revision"] == 2 and row["status"] == "in_progress"

        assert (await client.get(public)).status_code == 200
        await remaining_one("survey.public.read", 600)
        assert (await client.get(public)).status_code == 200
        denied(await client.get(path, headers=resume))
        denied(await client.get(f"/api/v1/public/surveys/{sid.hex}"))
        assert (await client.get(admin, headers=auth)).status_code == 200
        # Deterministic expiry advances only synthetic quota timestamps, not the
        # production clock. Expired attempts must not block a real new start.
        await conn.execute(
            "UPDATE security_rate_attempt SET attempted_at=now()-interval '61 seconds' WHERE scope LIKE 'survey.public.%'"
        )
        response = await client.post(public + "/participations", json=start)
        assert response.status_code == 200 and response.json()["id"] == pid
        assert (await client.get(path, headers=resume)).status_code == 200
        assert (
            await client.get(f"/api/v1/public/surveys/{sid.hex}")
        ).status_code == 200
        assert (
            await client.get(f"/api/v1/public/surveys/urn:uuid:{sid}")
        ).status_code == 200
        assert (await client.put(path, json=save, headers=resume)).status_code == 200
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM survey_participation WHERE survey_id=$1", sid
            )
            == 2
        )
    await conn.close()
    Path("/proof/request-limits-proof.json").write_text(
        json.dumps(
            {
                "syntheticOnly": True,
                "nearLimitCountersSeeded": True,
                "windowSeconds": 60,
                "startLimit": 30,
                "writeLimit": 300,
                "readLimit": 600,
                "concurrentLastPermitStatuses": [200, 429],
                "participationsAfterRejectedStarts": 2,
                "rejectedWritesPreservedRevision": 2,
                "cookieAndUserAgentRotationRejected": True,
                "crossSurveyAndRedeemShareQuota": True,
                "alternateUuidSpellingsShareQuota": True,
                "expiryAndIdempotentRetryPassed": True,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        "PASS: real public start/write/read quotas, concurrent last permit, no partial writes, identity rotation and expired-window recovery"
    )


asyncio.run(main())
