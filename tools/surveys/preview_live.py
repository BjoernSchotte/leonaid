"""Synthetic preview-isolation and timeout browser fixture with SQL verification."""

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
    state = Path("/proof/preview-state.json")
    if sys.argv[1] == "seed":
        sid = uuid4()
        token = Path("/proof/session.env").read_text().strip().split("=", 1)[1]
        async with httpx.AsyncClient(
            base_url="http://api:8000",
            headers={"Cookie": f"__Host-leonaid_session={token}"},
        ) as client:
            response = await client.post(
                f"/api/v1/surveys/{sid}",
                json={
                    "operationId": "preview-seed",
                    "title": "Synthetic preview isolation",
                    "inactivityTimeoutSeconds": 60,
                    "definition": {
                        "pages": [
                            {
                                "name": "one",
                                "elements": [
                                    {
                                        "type": "text",
                                        "name": "answer",
                                        "title": "Synthetic response",
                                    }
                                ],
                            }
                        ]
                    },
                },
            )
            assert response.status_code == 200
            response = await client.post(
                f"/api/v1/surveys/{sid}/publish",
                json={"operationId": "publish", "expectedRevision": 1},
            )
            assert response.status_code == 200
            version = response.json()
        await conn.execute(
            """INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,status,answers,is_test,inactivity_timeout_seconds,completed_at)
            VALUES($1,$2,$3,$4,'completed','{"answer":"SEEDED_TEST_ONLY"}',true,60,now())""",
            uuid4(),
            sid,
            UUID(version["id"]),
            secrets.token_hex(32),
        )
        state.write_text(json.dumps({"surveyId": str(sid)}))
        print(
            "PASS: real published survey plus explicitly marked synthetic test response"
        )
    else:
        sid = UUID(json.loads(state.read_text())["surveyId"])
        # Wait for the real worker's durable classification, independently of API effective status.
        async with asyncio.timeout(15):
            while not await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM survey_participation WHERE survey_id=$1 AND NOT is_test AND inactivity_timeout_seconds=1 AND status='partial')",
                sid,
            ):
                await asyncio.sleep(0.1)
        rows = await conn.fetch(
            "SELECT is_test,inactivity_timeout_seconds,status,answers FROM survey_participation WHERE survey_id=$1",
            sid,
        )
        assert len(rows) == 3
        real = [r for r in rows if not r["is_test"]]
        assert len(real) == 2 and sorted(
            r["inactivity_timeout_seconds"] for r in real
        ) == [1, 60]
        assert {r["status"] for r in real} == {"completed", "partial"}
        assert all("PREVIEW_ONLY" not in r["answers"] for r in rows)
        snapshots = await conn.fetch(
            "SELECT payload FROM survey_analysis_snapshot WHERE survey_id=$1", sid
        )
        results = [json.loads(r["payload"]) for r in snapshots]
        assert any(
            not r["filter"]["isTest"] and r["participationCount"] == 2 for r in results
        )
        assert any(
            r["filter"]["isTest"] and r["participationCount"] == 1 for r in results
        )
        Path("/proof/preview-proof.json").write_text(
            json.dumps(
                {
                    "syntheticOnly": True,
                    "previewAnswerAbsent": True,
                    "realResponses": 2,
                    "seededTestResponses": 1,
                    "oldTimeoutSeconds": 60,
                    "newTimeoutSeconds": 1,
                    "productionAndTestSnapshotsSeparated": True,
                },
                indent=2,
            )
            + "\n"
        )
        print(
            "PASS: preview never persisted; actual timeout snapshots and real/test analysis separation verified"
        )
    await conn.close()


asyncio.run(main())
