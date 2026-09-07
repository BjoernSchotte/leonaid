"""Real erasure/reclaim proof. Only synthetic data; crash after an actual DELETE."""

import asyncio
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.outbox import AsyncpgOutboxQueue
from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.survey_deletion import AsyncpgSurveyDeletion
from leonaid.adapters.postgres.survey_exports import AsyncpgSurveyExports
from leonaid.adapters.storage.s3 import S3ObjectStorage
from leonaid.application.object_storage import ObjectLocation
from leonaid.application.outbox import OutboxWorker
from leonaid.application.surveys.export_rendering import export_filename
from leonaid.domain.outbox import RetryPolicy

PROOF = Path("/proof")
STATE = PROOF / "deletion-state.json"


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
    pool = await create_pool(os.environ["CORE_DATABASE_URL"])
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    token = (PROOF / "session.env").read_text().strip().split("=", 1)[1]
    async with httpx.AsyncClient(base_url="http://api:8000", timeout=60) as client:

        async def call(
            sid, method, suffix, body=None, expected=200, authenticated=True
        ):
            response = await client.request(
                method,
                f"/api/v1/surveys/{sid}{suffix}",
                json=body,
                headers={"Cookie": f"__Host-leonaid_session={token}"}
                if authenticated
                else {},
            )
            assert response.status_code == expected, (
                suffix,
                response.status_code,
                expected,
            )
            return response

        if sys.argv[1] == "prepare":
            sid = uuid4()
            fixture = json.loads(
                Path("tests/fixtures/surveys/analysis-golden.json").read_text()
            )
            create = {
                "operationId": "create",
                "title": "SENSITIVE_ERASURE_TITLE",
                "definition": fixture["definition"],
            }
            await call(sid, "POST", "", create)
            purge = {
                "operationId": "SENSITIVE_ERASURE_OPERATION",
                "expectedRevision": 1,
            }
            await call(
                sid,
                "POST",
                "/delete-permanently",
                purge,
                expected=401,
                authenticated=False,
            )
            await call(sid, "POST", "/delete-permanently", purge, expected=409)
            assert not await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM survey_deletion WHERE survey_id=$1)", sid
            )
            version = (
                await call(
                    sid,
                    "POST",
                    "/publish",
                    {"operationId": "publish", "expectedRevision": 1},
                )
            ).json()
            now = datetime.now(timezone.utc)
            for sample in fixture["responses"]:
                await conn.execute(
                    """INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,status,answers,inactivity_timeout_seconds,completed_at)
                    VALUES($1,$2,$3,$4,'completed',$5::jsonb,3600,$6)""",
                    uuid4(),
                    sid,
                    UUID(version["id"]),
                    secrets.token_hex(32),
                    json.dumps(sample),
                    now,
                )
            await conn.execute(
                """INSERT INTO survey_invitation(id,survey_id,recipient_email,recipient_name,token_digest,expires_at,mail_payload)
                VALUES($1,$2,'synthetic@example.invalid','SENSITIVE_ERASURE_RECIPIENT',$3,$4,'SENSITIVE_ERASURE_ENCRYPTED_PAYLOAD')""",
                uuid4(),
                sid,
                secrets.token_hex(32),
                now + timedelta(days=1),
            )
            snap = (
                await call(
                    sid,
                    "POST",
                    "/analysis",
                    {"operationId": "snapshot", "filter": {"versionId": version["id"]}},
                )
            ).json()
            queue = AsyncpgOutboxQueue(pool)
            locations, jobs = [], []
            for orphan in (False, True):
                job = (
                    await call(
                        sid,
                        "POST",
                        "/exports",
                        {
                            "operationId": f"export-{orphan}",
                            "snapshotId": snap["id"],
                            "product": "responses_csv",
                        },
                    )
                ).json()
                jobs.append(job["id"])
                reached_upload = False

                class UploadThenFail(S3ObjectStorage):
                    async def put_immutable(self, write):
                        nonlocal reached_upload
                        await super().put_immutable(write)
                        reached_upload = True
                        raise RuntimeError("SENSITIVE_ERASURE_PROVIDER_DETAIL")

                worker = OutboxWorker(
                    worker_id="deletion-export-fixture",
                    queue=queue,
                    handlers={
                        "survey.export.render.v1": AsyncpgSurveyExports(
                            pool, storage(UploadThenFail) if orphan else storage()
                        )
                    },
                    retry_policy=RetryPolicy(base_delay=timedelta(minutes=10)),
                )
                assert await worker.run_once()
                row = await conn.fetchrow(
                    "SELECT * FROM survey_export_job WHERE id=$1", UUID(job["id"])
                )
                assert row["status"] == ("queued" if orphan else "available")
                assert reached_upload == orphan
                assert bool(row["object_version"]) != orphan
                location = ObjectLocation(
                    storage().bucket,
                    f"surveys/{sid}/exports/{job['id']}/{export_filename('responses_csv', snap['id'])}",
                )
                stored = await storage().head(location)
                assert stored is not None
                locations.append(
                    {
                        "bucket": stored.location.bucket,
                        "key": stored.location.key,
                        "version_id": stored.location.version_id,
                    }
                )
            current = (await call(sid, "GET", "")).json()
            trash = (
                await call(
                    sid,
                    "POST",
                    "/transition",
                    {
                        "operationId": "trash",
                        "action": "trash",
                        "expectedRevision": current["revision"],
                    },
                )
            ).json()
            await call(sid, "POST", "/delete-permanently", purge, expected=409)
            purge["expectedRevision"] = trash["revision"]
            first = (await call(sid, "POST", "/delete-permanently", purge)).json()
            assert first["status"] == "pending"
            assert (
                await call(sid, "POST", "/delete-permanently", purge)
            ).json() == first
            await call(
                sid,
                "POST",
                "/delete-permanently",
                {**purge, "operationId": "different"},
                expected=409,
            )
            await call(
                sid,
                "POST",
                "/transition",
                {
                    "operationId": "restore",
                    "action": "restore",
                    "expectedRevision": trash["revision"],
                },
                expected=404,
            )
            for jid in jobs:
                await call(sid, "GET", f"/exports/{jid}/download", expected=404)
            ledger = await conn.fetchrow(
                "SELECT * FROM survey_deletion WHERE survey_id=$1", sid
            )
            assert set(ledger.keys()) == {
                "survey_id",
                "requested_by",
                "operation_hash",
                "expected_revision",
                "event_id",
                "requested_at",
                "completed_at",
            }
            assert (
                ledger["operation_hash"]
                == hashlib.sha256(purge["operationId"].encode()).hexdigest()
            )
            assert "SENSITIVE_" not in str(dict(ledger))
            STATE.write_text(
                json.dumps(
                    {
                        "sid": str(sid),
                        "purge": purge,
                        "locations": locations,
                        "jobs": jobs,
                        "event": str(ledger["event_id"]),
                        "create": create,
                    }
                )
            )
            print(
                "PASS: real exports including uncommitted upload; committed content-free deletion intent; request guards"
            )
        else:
            state = json.loads(STATE.read_text())
            sid, event_id = UUID(state["sid"]), UUID(state["event"])
            if sys.argv[1] == "crash":
                queue = AsyncpgOutboxQueue(pool)
                event = await queue.claim_next(
                    worker_id="deletion-crash", now=datetime.now(timezone.utc)
                )
                assert event is not None and event.id == event_id

                class DeleteThenCrash(S3ObjectStorage):
                    async def delete(self, location, *, authorization):
                        await super().delete(location, authorization=authorization)
                        assert await storage().head(location) is None
                        print(
                            "PASS: actual object version removed; terminating before database commit",
                            flush=True,
                        )
                        os._exit(73)

                await AsyncpgSurveyDeletion(pool, storage(DeleteThenCrash)).handle(
                    event
                )
                raise AssertionError("Expected process termination")
            assert sys.argv[1] == "recover"
            event = await conn.fetchrow(
                "SELECT * FROM outbox_event WHERE id=$1", event_id
            )
            assert event["status"] == "processing" and event["attempts"] == 1
            assert not await conn.fetchval(
                "SELECT completed_at FROM survey_deletion WHERE survey_id=$1", sid
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM survey_export_job WHERE survey_id=$1", sid
                )
                == 2
            )
            remaining = [
                await storage().head(ObjectLocation(**loc)) is not None
                for loc in state["locations"]
            ]
            assert remaining.count(False) == 1 and remaining.count(True) == 1
            await conn.execute(
                "UPDATE outbox_event SET claimed_at=clock_timestamp()-interval '10 minutes' WHERE id=$1",
                event_id,
            )
            worker = OutboxWorker(
                worker_id="deletion-recovery",
                queue=AsyncpgOutboxQueue(pool),
                handlers={"survey.delete.v1": AsyncpgSurveyDeletion(pool, storage())},
                retry_policy=RetryPolicy(),
            )
            assert await worker.run_once()
            event = await conn.fetchrow(
                "SELECT * FROM outbox_event WHERE id=$1", event_id
            )
            assert event["status"] == "completed" and event["attempts"] == 2
            tables = [
                "survey",
                "survey_draft",
                "survey_version",
                "survey_participation",
                "survey_operation",
                "survey_invitation",
                "survey_grant",
                "survey_analysis_snapshot",
                "survey_export_job",
            ]
            for table in tables:
                key = "id" if table == "survey" else "survey_id"
                assert (
                    await conn.fetchval(
                        f"SELECT count(*) FROM {table} WHERE {key}=$1", sid
                    )
                    == 0
                ), table
            for location in state["locations"]:
                assert await storage().head(ObjectLocation(**location)) is None
                assert (
                    await storage().head(
                        ObjectLocation(location["bucket"], location["key"])
                    )
                    is None
                )
            done = (
                await call(sid, "POST", "/delete-permanently", state["purge"])
            ).json()
            assert done["status"] == "completed" and done["completedAt"]
            await call(sid, "POST", "", state["create"], expected=404)
            await call(sid, "GET", "", expected=404)
            try:
                await conn.execute(
                    "INSERT INTO survey(id,title,owner_user_id) SELECT survey_id,'recreated',requested_by FROM survey_deletion WHERE survey_id=$1",
                    sid,
                )
            except asyncpg.IntegrityConstraintViolationError:
                pass
            else:
                raise AssertionError("DB allowed recreation of erased survey ID")
            # The orphan export event may be retried after deletion: no recreation.
            await conn.execute(
                "UPDATE outbox_event SET available_at=clock_timestamp() WHERE event_type='survey.export.render.v1' AND status='pending'"
            )
            late = OutboxWorker(
                worker_id="late-export",
                queue=AsyncpgOutboxQueue(pool),
                handlers={
                    "survey.export.render.v1": AsyncpgSurveyExports(pool, storage())
                },
                retry_policy=RetryPolicy(),
            )
            assert await late.run_once()
            assert not await late.run_once()
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM survey_export_job WHERE survey_id=$1", sid
                )
                == 0
            )
            (PROOF / "deletion-proof.json").write_text(
                json.dumps(
                    {
                        "syntheticOnly": True,
                        "requestGuards": True,
                        "contentFreeLedger": True,
                        "exportVersions": 2,
                        "uncommittedUploadRemoved": True,
                        "actualDeleteBeforeProcessExit": 73,
                        "deletionAttempts": 2,
                        "removedDatabaseTables": tables,
                        "restoreAndRecreationBlocked": True,
                        "lateExportHarmless": True,
                        "limitations": [
                            "No UI acceptance yet",
                            "Retention scheduling and backup restoration are separate open tasks",
                            "Fixed object-storage bucket for this proof",
                        ],
                    },
                    indent=2,
                )
                + "\n"
            )
            print(
                "PASS: exact object versions erased, DB cascades verified, durable retry completed, recreation blocked"
            )
    await conn.close()
    await pool.close()


asyncio.run(main())
