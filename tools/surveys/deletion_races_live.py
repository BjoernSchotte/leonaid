"""Deterministic PostgreSQL lock interleavings against real API and S3 adapters."""

import asyncio
import json
import os
import secrets
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.survey_deletion import AsyncpgSurveyDeletion
from leonaid.adapters.postgres.survey_exports import AsyncpgSurveyExports
from leonaid.adapters.storage.s3 import S3ObjectStorage
from leonaid.application.object_storage import ObjectLocation
from leonaid.domain.outbox import ClaimedOutboxEvent


def storage(cls=S3ObjectStorage):
    return cls(
        endpoint_url=os.environ["OBJECT_STORAGE_ENDPOINT_URL"],
        access_key=os.environ["OBJECT_STORAGE_ACCESS_KEY"],
        secret_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],
        bucket=os.environ["OBJECT_STORAGE_BUCKET"],
        region=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1"),
        path_style=True,
    )


async def main():
    dsn = os.environ["CORE_DATABASE_URL"]
    conn = await asyncpg.connect(dsn)
    blocker = await asyncpg.connect(dsn)
    erase_pool = await asyncpg.create_pool(
        dsn, min_size=1, max_size=2, server_settings={"application_name": "race-eraser"}
    )
    export_pool = await asyncpg.create_pool(
        dsn, min_size=1, max_size=2, server_settings={"application_name": "race-export"}
    )
    token = Path("/proof/session.env").read_text().strip().split("=", 1)[1]
    headers = {"Cookie": f"__Host-leonaid_session={token}"}
    outcomes = []

    async def waiting(*, application=None, query=None, blocked_by=None):
        # Poll observed lock state, never use elapsed time to establish ordering.
        async with asyncio.timeout(15):
            while True:
                rows = await conn.fetch(
                    """SELECT pid,application_name,query,pg_blocking_pids(pid) blockers
                    FROM pg_stat_activity WHERE datname=current_database()
                    AND wait_event_type='Lock' AND pid<>pg_backend_pid()"""
                )
                for row in rows:
                    if application and row["application_name"] != application:
                        continue
                    if query and query not in row["query"]:
                        continue
                    if blocked_by and blocked_by not in row["blockers"]:
                        continue
                    return row["pid"]
                await asyncio.sleep(0.02)

    async with httpx.AsyncClient(base_url="http://api:8000", timeout=45) as client:

        async def request(method, path, body=None, auth=None, expected=200):
            result = await client.request(method, path, json=body, headers=auth or {})
            assert result.status_code == expected, (
                method,
                result.status_code,
                expected,
            )
            return result.json()

        async def fixture():
            sid = uuid4()
            admin = f"/api/v1/surveys/{sid}"
            public = f"/api/v1/public/surveys/{sid}"
            await request(
                "POST",
                admin,
                {
                    "operationId": "create",
                    "title": "Synthetic deletion race",
                    "definition": {
                        "pages": [
                            {
                                "name": "page",
                                "elements": [{"type": "text", "name": "answer"}],
                            }
                        ]
                    },
                },
                headers,
            )
            version = await request(
                "POST",
                admin + "/publish",
                {"operationId": "publish", "expectedRevision": 1},
                headers,
            )
            secret = secrets.token_urlsafe(48)
            participant = await request(
                "POST",
                public + "/participations",
                {"operationId": "start", "resumeSecret": secret},
            )
            pid = UUID(participant["id"])
            path = public + f"/participations/{pid}"
            respondent = {"Cookie": f"__Host-survey_{pid}={secret}"}
            await request(
                "PUT",
                path,
                {
                    "operationId": "baseline",
                    "expectedRevision": 1,
                    "answers": {"answer": "SYNTHETIC_BASELINE"},
                },
                respondent,
            )
            return sid, admin, path, respondent, pid, version

        async def trash(admin, survey=None):
            if survey is None:
                survey = await request("GET", admin, auth=headers)
            return await request(
                "POST",
                admin + "/transition",
                {
                    "operationId": "trash",
                    "expectedRevision": survey["revision"],
                    "action": "trash",
                },
                headers,
            )

        async def intent(sid, admin, trashed):
            await request(
                "POST",
                admin + "/delete-permanently",
                {"operationId": "erase", "expectedRevision": trashed["revision"]},
                headers,
            )
            return await conn.fetchval(
                "SELECT event_id FROM survey_deletion WHERE survey_id=$1", sid
            )

        async def absent(sid, admin, path, respondent, event_id):
            for table in (
                "survey",
                "survey_draft",
                "survey_version",
                "survey_participation",
                "survey_operation",
                "survey_invitation",
                "survey_grant",
                "survey_analysis_snapshot",
                "survey_export_job",
            ):
                key = "id" if table == "survey" else "survey_id"
                assert not await conn.fetchval(
                    f"SELECT EXISTS(SELECT 1 FROM {table} WHERE {key}=$1)", sid
                ), table
            assert await conn.fetchval(
                "SELECT completed_at IS NOT NULL FROM survey_deletion WHERE survey_id=$1",
                sid,
            )
            await request("GET", admin, auth=headers, expected=404)
            await request(
                "PUT",
                path,
                {
                    "operationId": "late-save",
                    "expectedRevision": 2,
                    "answers": {"answer": "LATE"},
                },
                respondent,
                expected=404,
            )
            await request(
                "POST",
                path + "/complete",
                {"operationId": "late-complete", "expectedRevision": 2},
                respondent,
                expected=404,
            )
            await AsyncpgSurveyDeletion(erase_pool, storage()).erase(sid, event_id)

        for operation in ("save", "complete"):
            for first in ("response", "deletion"):
                sid, admin, path, respondent, pid, _ = await fixture()
                body = {"operationId": "racing-response", "expectedRevision": 2}
                if operation == "save":
                    body["answers"] = {"answer": "ACCEPTED_BEFORE_TRASH"}
                method, suffix = (
                    ("PUT", "") if operation == "save" else ("POST", "/complete")
                )
                if first == "response":
                    current = await request("GET", admin, auth=headers)
                    async with blocker.transaction():
                        await blocker.fetchrow(
                            "SELECT id FROM survey_participation WHERE id=$1 FOR UPDATE",
                            pid,
                        )
                        response = asyncio.create_task(
                            request(method, path + suffix, body, respondent)
                        )
                        response_pid = await waiting(
                            query="SELECT * FROM survey_participation",
                            blocked_by=blocker.get_server_pid(),
                        )
                        deletion = asyncio.create_task(trash(admin, current))
                        await waiting(
                            query="SELECT * FROM survey WHERE", blocked_by=response_pid
                        )
                    result, trashed = await asyncio.gather(response, deletion)
                    assert result["revision"] == 3
                    assert result["status"] == (
                        "completed" if operation == "complete" else "in_progress"
                    )
                    event_id = await intent(sid, admin, trashed)
                    await AsyncpgSurveyDeletion(erase_pool, storage()).erase(
                        sid, event_id
                    )
                else:
                    event_id = await intent(sid, admin, await trash(admin))
                    async with blocker.transaction():
                        await blocker.fetchrow(
                            "SELECT id FROM survey WHERE id=$1 FOR UPDATE", sid
                        )
                        deletion = asyncio.create_task(
                            AsyncpgSurveyDeletion(erase_pool, storage()).erase(
                                sid, event_id
                            )
                        )
                        await waiting(
                            application="race-eraser",
                            blocked_by=blocker.get_server_pid(),
                        )
                        response = asyncio.create_task(
                            request(
                                method, path + suffix, body, respondent, expected=404
                            )
                        )
                        await waiting(query="SELECT * FROM survey WHERE")
                    await asyncio.gather(deletion, response)
                await absent(sid, admin, path, respondent, event_id)
                outcomes.append(
                    {"operation": operation, "first": first, "passed": True}
                )
                print(
                    f"PASS: {operation}, {first} holds the survey lock first",
                    flush=True,
                )

        for first in ("export", "deletion"):
            sid, admin, path, respondent, _, version = await fixture()
            await request(
                "POST",
                path + "/complete",
                {"operationId": "complete-export-fixture", "expectedRevision": 2},
                respondent,
            )
            snap = await request(
                "POST",
                admin + "/analysis",
                {"operationId": "snapshot", "filter": {"versionId": version["id"]}},
                headers,
            )
            job = await request(
                "POST",
                admin + "/exports",
                {
                    "operationId": "export",
                    "snapshotId": snap["id"],
                    "product": "responses_csv",
                },
                headers,
            )
            row = await conn.fetchrow(
                "SELECT e.* FROM outbox_event e JOIN survey_export_job j ON j.event_id=e.id WHERE j.id=$1",
                UUID(job["id"]),
            )
            # Deliver the actual persisted event to the production handler.
            # Queue leasing/crash acknowledgement is exercised by deletion_live.py.
            event = ClaimedOutboxEvent(
                id=row["id"],
                aggregate_type=row["aggregate_type"],
                aggregate_id=row["aggregate_id"],
                event_type=row["event_type"],
                idempotency_key=row["idempotency_key"],
                payload=json.loads(row["payload"]),
                attempts=1,
                claim_token=uuid4(),
                claimed_by="race-proof",
            )
            uploaded, release = asyncio.Event(), asyncio.Event()
            locations = []

            class UploadBarrier(S3ObjectStorage):
                async def put_immutable(self, write):
                    stored = await super().put_immutable(write)
                    locations.append(stored.location)
                    uploaded.set()
                    async with asyncio.timeout(20):
                        await release.wait()
                    return stored

            renderer = AsyncpgSurveyExports(export_pool, storage(UploadBarrier))
            if first == "export":
                current = await request("GET", admin, auth=headers)
                render = asyncio.create_task(renderer.handle(event))
                await asyncio.wait_for(uploaded.wait(), 20)
                deletion = asyncio.create_task(trash(admin, current))
                await waiting(
                    query="pg_advisory_xact_lock",
                    blocked_by=await conn.fetchval(
                        "SELECT pid FROM pg_stat_activity WHERE application_name='race-export' AND state='idle in transaction'"
                    ),
                )
                release.set()
                _, trashed = await asyncio.gather(render, deletion)
                assert len(locations) == 1
                event_id = await intent(sid, admin, trashed)
                await AsyncpgSurveyDeletion(erase_pool, storage()).erase(sid, event_id)
            else:
                event_id = await intent(sid, admin, await trash(admin))
                async with blocker.transaction():
                    await blocker.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", str(sid)
                    )
                    deletion = asyncio.create_task(
                        AsyncpgSurveyDeletion(erase_pool, storage()).erase(
                            sid, event_id
                        )
                    )
                    await waiting(
                        application="race-eraser", blocked_by=blocker.get_server_pid()
                    )
                    render = asyncio.create_task(renderer.handle(event))
                    await waiting(application="race-export")
                await asyncio.gather(deletion, render)
                assert not uploaded.is_set() and not locations
            await renderer.handle(event)  # Late redelivery must remain a no-op.
            for location in locations:
                assert await storage().head(location) is None
                assert (
                    await storage().head(ObjectLocation(location.bucket, location.key))
                    is None
                )
            await request(
                "GET",
                admin + f"/exports/{job['id']}/download",
                auth=headers,
                expected=404,
            )
            await absent(sid, admin, path, respondent, event_id)
            outcomes.append(
                {
                    "operation": "export",
                    "first": first,
                    "passed": True,
                    "actualUploadedVersionsRemoved": len(locations),
                }
            )
            print(f"PASS: export, {first} holds the survey lock first", flush=True)

    Path("/proof/deletion-races-proof.json").write_text(
        json.dumps(
            {
                "syntheticOnly": True,
                "ordering": "observed PostgreSQL lock waiters and actual S3 upload barrier",
                "cases": outcomes,
                "lateResponseWritesRejected": True,
                "lateExportRedeliveryHarmless": True,
                "allTargetedDatabaseRowsAbsent": True,
                "downloadsDenied": True,
                "scope": "Production API, PostgreSQL, export/deletion handlers and RustFS; queue leasing covered separately",
            },
            indent=2,
        )
        + "\n"
    )
    await blocker.close()
    await conn.close()
    await erase_pool.close()
    await export_pool.close()


asyncio.run(main())
