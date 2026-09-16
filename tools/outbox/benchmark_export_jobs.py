"""Measure real queued survey exports; writes isolated synthetic test records."""

import argparse
import asyncio
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest


async def main(fixture_path: Path) -> None:
    fixture = json.loads(fixture_path.read_text())
    db = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    actor, survey = uuid4(), uuid4()
    token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    try:
        async with db.transaction():
            await db.execute(
                "INSERT INTO user_account(id,email,display_name,status) VALUES($1,$2,'Synthetic export benchmark','active')",
                actor,
                f"{actor}@example.invalid",
            )
            await db.execute(
                "INSERT INTO user_global_role(user_id,role) VALUES($1,'system_admin')",
                actor,
            )
            await db.execute(
                "INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$5,$5,$5)",
                uuid4(),
                actor,
                session_token_digest(token),
                now + SESSION_LIFETIME,
                now,
            )
        async with httpx.AsyncClient(
            base_url="http://api:8000",
            headers={"Cookie": f"__Host-leonaid_session={token}"},
            timeout=60,
        ) as client:

            async def call(
                method: str, path: str, body: dict[str, Any] | None = None
            ) -> httpx.Response:
                response = await client.request(method, path, json=body)
                assert response.status_code == 200, (path, response.status_code)
                return response

            path = f"/api/v1/surveys/{survey}"
            await call(
                "POST",
                path,
                {
                    "operationId": "create",
                    "title": "Synthetic full export measurement",
                    "definition": fixture["definition"],
                },
            )
            version = (
                await call(
                    "POST",
                    path + "/publish",
                    {"operationId": "publish", "expectedRevision": 1},
                )
            ).json()
            async with db.transaction():
                await db.executemany(
                    "INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,status,answers,current_page,inactivity_timeout_seconds,created_at,last_answer_changed_at,completed_at) VALUES($1,$2,$3,$4,'completed',$5::jsonb,'main',3600,$6,$6,$6)",
                    [
                        (
                            uuid4(),
                            survey,
                            UUID(version["id"]),
                            hashlib.sha256(secrets.token_bytes(48)).hexdigest(),
                            json.dumps(
                                fixture["responses"][i % len(fixture["responses"])]
                            ),
                            now,
                        )
                        for i in range(5000)
                    ],
                )
            snapshot = (
                await call(
                    "POST",
                    path + "/analysis",
                    {"operationId": "snapshot", "filter": {"versionId": version["id"]}},
                )
            ).json()
            results = []
            for product in (
                "analysis_pdf",
                "analysis_xlsx",
                "responses_csv",
                "responses_xlsx",
            ):
                started = perf_counter()
                job = (
                    await call(
                        "POST",
                        path + "/exports",
                        {
                            "operationId": product,
                            "snapshotId": snapshot["id"],
                            "product": product,
                        },
                    )
                ).json()
                async with asyncio.timeout(240):
                    while job["status"] != "available":
                        assert job["status"] in ("queued", "processing", "retrying"), (
                            job["status"]
                        )
                        await asyncio.sleep(0.25)
                        job = (await call("GET", path + f"/exports/{job['id']}")).json()
                ready_seconds = perf_counter() - started
                artifact = await call("GET", path + f"/exports/{job['id']}/download")
                assert len(artifact.content) == job["sizeBytes"] > 0
                if product == "analysis_pdf":
                    assert artifact.content.startswith(b"%PDF-")
                elif product.endswith("xlsx"):
                    assert artifact.content.startswith(b"PK")
                else:
                    assert len(artifact.text.splitlines()) >= 5001
                results.append(
                    {
                        "product": product,
                        "responses": 5000,
                        "readySeconds": round(ready_seconds, 3),
                        "downloadedSeconds": round(perf_counter() - started, 3),
                        "sizeBytes": len(artifact.content),
                    }
                )
            print(
                json.dumps(
                    {
                        "scope": "production API, durable queue/worker, PostgreSQL, private storage and download",
                        "measurements": results,
                    },
                    indent=2,
                )
            )
    finally:
        await db.execute(
            "UPDATE user_session SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL",
            actor,
        )
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/surveys/analysis-golden.json"),
    )
    asyncio.run(main(parser.parse_args().fixture))
