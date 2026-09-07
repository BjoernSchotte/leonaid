"""Inspect actual survey DB and object restoration around the offline erasure gate."""

import asyncio
import json
import os
from pathlib import Path
import secrets
import sys
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.outbox import AsyncpgOutboxQueue
from leonaid.adapters.postgres.survey_exports import AsyncpgSurveyExports
from leonaid.adapters.postgres.survey_deletion import AsyncpgSurveyDeletion
from leonaid.adapters.postgres.survey_recovery import (
    export_checkpoint,
    reapply_checkpoint,
)
from leonaid.adapters.storage.s3 import S3ObjectStorage
from leonaid.application.object_storage import ObjectLocation
from leonaid.application.outbox import OutboxWorker
from leonaid.application.surveys.recovery import seal
from leonaid.domain.outbox import RetryPolicy

PROOF = Path("/proof")


def storage():
    return S3ObjectStorage(
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
    async with httpx.AsyncClient(base_url="http://api:8000", timeout=30) as client:

        async def call(sid, method, suffix, body=None, expected=200):
            response = await client.request(
                method,
                f"/api/v1/surveys/{sid}{suffix}",
                json=body,
                headers={"Cookie": f"__Host-leonaid_session={token}"},
            )
            assert response.status_code == expected, (
                suffix,
                response.status_code,
                expected,
            )
            return response.json() if expected == 200 else None

        worker = OutboxWorker(
            worker_id="recovery-fixture",
            queue=AsyncpgOutboxQueue(pool),
            handlers={
                "survey.export.render.v1": AsyncpgSurveyExports(pool, storage()),
                "survey.delete.v1": AsyncpgSurveyDeletion(pool, storage()),
            },
            retry_policy=RetryPolicy(),
        )
        if sys.argv[1] == "seed":
            sid = uuid4()
            await call(
                sid,
                "POST",
                "",
                {
                    "operationId": "create",
                    "title": "Synthetic backup recovery survey",
                    "definition": {
                        "pages": [
                            {
                                "name": "main",
                                "elements": [{"name": "answer", "type": "text"}],
                            }
                        ]
                    },
                },
            )
            version = await call(
                sid,
                "POST",
                "/publish",
                {"operationId": "publish", "expectedRevision": 1},
            )
            await conn.execute(
                """INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,status,answers,inactivity_timeout_seconds,completed_at)
            VALUES($1,$2,$3,$4,'completed','{"answer":"SENSITIVE_BACKUP_ANSWER"}',60,clock_timestamp())""",
                uuid4(),
                sid,
                UUID(version["id"]),
                secrets.token_hex(32),
            )
            snapshot = await call(
                sid,
                "POST",
                "/analysis",
                {"operationId": "snapshot", "filter": {"versionId": version["id"]}},
            )
            job = await call(
                sid,
                "POST",
                "/exports",
                {
                    "operationId": "csv",
                    "snapshotId": snapshot["id"],
                    "product": "responses_csv",
                },
            )
            assert await worker.run_once()
            row = await conn.fetchrow(
                "SELECT * FROM survey_export_job WHERE id=$1", UUID(job["id"])
            )
            assert row["status"] == "available"
            location = ObjectLocation(
                row["bucket"], row["object_key"], row["object_version"]
            )
            fetched = await storage().get(location)
            assert b"SENSITIVE_BACKUP_ANSWER" in fetched.content
            state = {
                "sid": str(sid),
                "job": job["id"],
                "sha256": fetched.stored.sha256,
                "location": {
                    "bucket": location.bucket,
                    "key": location.key,
                    "version_id": location.version_id,
                },
            }
            (PROOF / "recovery-state.json").write_text(json.dumps(state))
            print(
                "PASS: real response/export ready for consistent DB and object-volume backup"
            )
        else:
            state = json.loads((PROOF / "recovery-state.json").read_text())
            sid = UUID(state["sid"])
            location = ObjectLocation(**state["location"])
            if sys.argv[1] == "delete":
                summary = await call(sid, "GET", "")
                trash = await call(
                    sid,
                    "POST",
                    "/transition",
                    {
                        "operationId": "trash",
                        "expectedRevision": summary["revision"],
                        "action": "trash",
                    },
                )
                await call(
                    sid,
                    "POST",
                    "/delete-permanently",
                    {"operationId": "erase", "expectedRevision": trash["revision"]},
                )
                assert await worker.run_once()
                assert (
                    await conn.fetchval("SELECT count(*) FROM survey WHERE id=$1", sid)
                    == 0
                )
                assert await storage().head(location) is None
                checkpoint = await export_checkpoint(pool)
                assert len(checkpoint.records) == 1
                document = seal(
                    checkpoint, os.environ["LEONAID_SESSION_ENCRYPTION_KEY"]
                )
                assert b"SENSITIVE_BACKUP_ANSWER" not in document
                (PROOF / "recovery-checkpoint.json").write_bytes(document)
                (PROOF / "recovery-cutoff.txt").write_text(
                    checkpoint.exported_at.isoformat()
                )
                print(
                    "PASS: post-backup erasure complete; newer authenticated checkpoint retained independently"
                )
            elif sys.argv[1] == "restored":
                assert (
                    PROOF / "recovery-checkpoint.json"
                ).stat().st_mode & 0o777 == 0o600
                assert (
                    await conn.fetchval("SELECT status FROM survey WHERE id=$1", sid)
                    == "active"
                )
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM survey_deletion WHERE survey_id=$1", sid
                    )
                    == 0
                )
                fetched = await storage().get(location)
                assert (
                    fetched.stored.sha256 == state["sha256"]
                    and b"SENSITIVE_BACKUP_ANSWER" in fetched.content
                )
                exported = json.loads((PROOF / "recovery-checkpoint.json").read_text())
                exported["checkpoint"]["records"] = []
                (PROOF / "recovery-tampered.json").write_text(json.dumps(exported))
                print(
                    "PASS: old DB and exact object version really restored while app writers remain offline"
                )
            elif sys.argv[1] == "verify":
                assert (
                    await conn.fetchval("SELECT count(*) FROM survey WHERE id=$1", sid)
                    == 0
                )
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM survey_participation WHERE survey_id=$1",
                        sid,
                    )
                    == 0
                )
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM survey_export_job WHERE survey_id=$1", sid
                    )
                    == 0
                )
                assert await storage().head(location) is None
                assert await conn.fetchval(
                    "SELECT completed_at IS NOT NULL FROM survey_deletion WHERE survey_id=$1",
                    sid,
                )
                # A validly signed but incomplete checkpoint is also refused when
                # the restored database already knows the missing deletion.
                original = await export_checkpoint(pool)
                incomplete = original.model_copy(update={"records": ()})
                try:
                    await reapply_checkpoint(pool, storage(), incomplete)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Known deletion silently omitted")
                (PROOF / "recovery-proof.json").write_text(
                    json.dumps(
                        {
                            "syntheticOnly": True,
                            "postBackupDeletion": True,
                            "oldActiveSurveyAndExactObjectRestored": True,
                            "signedCheckpointReappliedTwice": True,
                            "tamperedCheckpointRejected": True,
                            "knownDeletionOmissionRejected": True,
                            "answersAndExactFileErasedAgain": True,
                            "limitations": [
                                "This probe restores real PostgreSQL and RustFS backups; full Restic/operator wrapper integration is still open",
                                "Latest checkpoint must be independently retained; source-loss continuity is not proven",
                            ],
                        },
                        indent=2,
                    )
                    + "\n"
                )
                print(
                    "PASS: restored data erased again, repeat reapplication safe, known deletion omission rejected"
                )
            elif sys.argv[1] == "online":
                await call(sid, "GET", "", expected=404)
                await call(
                    sid, "GET", f"/exports/{state['job']}/download", expected=404
                )
                assert (
                    await client.get(f"/api/v1/public/surveys/{sid}")
                ).status_code == 404
                result = json.loads((PROOF / "recovery-proof.json").read_text())
                result["cliCheckpointExportMode600"] = True
                result["restoredSessionAndPublicAccessDeniedAfterRestart"] = True
                (PROOF / "recovery-proof.json").write_text(
                    json.dumps(result, indent=2) + "\n"
                )
                print(
                    "PASS: old authenticated session and public route cannot retrieve erased survey or export after startup"
                )
            else:
                raise AssertionError("Unknown stage")
    await conn.close()
    await pool.close()


asyncio.run(main())
