"""Commit real grant revocation at actual storage boundaries of export operations."""

import asyncio
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.outbox import AsyncpgOutboxQueue
from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.survey_exports import AsyncpgSurveyExports
from leonaid.adapters.storage.s3 import S3ObjectStorage
from leonaid.application.errors import ResourceNotFound
from leonaid.application.outbox import OutboxWorker
from leonaid.domain.outbox import RetryPolicy
from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest

PROOF = Path("/proof")


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
    admin = (PROOF / "session.env").read_text().strip().split("=", 1)[1]
    now = datetime.now(timezone.utc)
    sid, uid = uuid4(), uuid4()
    token = secrets.token_urlsafe(48)
    await conn.execute(
        "INSERT INTO user_account(id,email,display_name,status,email_verified_at) VALUES($1,$2,'Synthetic export permission probe','active',$3)",
        uid,
        f"{uid}@example.invalid",
        now,
    )
    await conn.execute(
        "INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$5,$5,$5)",
        uuid4(),
        uid,
        session_token_digest(token),
        now + SESSION_LIFETIME,
        now,
    )
    async with httpx.AsyncClient(base_url="http://api:8000", timeout=60) as client:

        async def request(method, suffix, body=None, *, owner=False, expected=200):
            response = await client.request(
                method,
                f"/api/v1/surveys/{sid}{suffix}",
                json=body,
                headers={
                    "Cookie": f"__Host-leonaid_session={admin if owner else token}"
                },
            )
            assert response.status_code == expected, (
                suffix,
                response.status_code,
                expected,
            )
            return response

        definition = json.loads(
            Path("tests/fixtures/surveys/analysis-golden.json").read_text()
        )["definition"]
        await request(
            "POST",
            "",
            {
                "operationId": "create",
                "title": "Synthetic export permission boundaries",
                "definition": definition,
            },
            owner=True,
        )
        published = (
            await request(
                "POST",
                "/publish",
                {"operationId": "publish", "expectedRevision": 1},
                owner=True,
            )
        ).json()

        async def grant():
            await conn.execute(
                "INSERT INTO survey_grant(survey_id,user_id,capability) VALUES($1,$2,'export_raw') ON CONFLICT DO NOTHING",
                sid,
                uid,
            )

        async def revoke():
            assert (
                await conn.execute(
                    "DELETE FROM survey_grant WHERE survey_id=$1 AND user_id=$2",
                    sid,
                    uid,
                )
                == "DELETE 1"
            )

        await grant()
        selection_body = {
            "operationId": "selection",
            "filter": {
                "versionId": published["id"],
                "statuses": ["partial", "completed"],
                "isTest": False,
                "createdFrom": None,
                "createdBefore": None,
            },
        }
        selection = (await request("POST", "/export-selections", selection_body)).json()
        assert set(selection) == {
            "id",
            "surveyId",
            "versionNumber",
            "createdAt",
            "filter",
        }

        async def create(label):
            body = {
                "operationId": label,
                "snapshotId": selection["id"],
                "product": "responses_csv",
            }
            job = (await request("POST", "/exports", body)).json()
            return job, body

        async def run(target, job):
            # The normal worker is stopped by this isolated harness. Require the
            # exact event, so an unrelated event cannot make run_once look green.
            eligible = await conn.fetch(
                "SELECT aggregate_id FROM outbox_event WHERE status='pending' AND available_at<=clock_timestamp()"
            )
            assert [str(r["aggregate_id"]) for r in eligible] == [job["id"]]
            worker = OutboxWorker(
                worker_id="survey-export-permission-probe",
                queue=AsyncpgOutboxQueue(pool),
                handlers={
                    "survey.export.render.v1": AsyncpgSurveyExports(pool, target)
                },
                retry_policy=RetryPolicy(),
            )
            assert await worker.run_once()
            row = await conn.fetchrow(
                "SELECT j.*, e.status AS event_status FROM survey_export_job j JOIN outbox_event e ON e.id=j.event_id WHERE j.id=$1",
                UUID(job["id"]),
            )
            assert row["event_status"] == "completed"
            return row

        async def denied(job, body):
            await request("POST", "/export-selections", selection_body, expected=404)
            await request("GET", "/export-selections/versions", expected=404)
            await request("POST", "/exports", body, expected=404)
            for suffix in ("", "/download"):
                response = await request(
                    "GET", f"/exports/{job['id']}{suffix}", expected=404
                )
                assert "content-disposition" not in response.headers

        queued, body = await create("queued-revoke")
        await revoke()
        row = await run(storage(), queued)
        assert row["status"] == "cancelled" and row["object_key"] is None
        await denied(queued, body)

        await grant()
        uploaded, body = await create("upload-revoke")
        reached_upload = False

        class RevokeAfterUpload(S3ObjectStorage):
            async def put_immutable(self, write):
                nonlocal reached_upload
                result = await super().put_immutable(write)
                await revoke()  # Separate committed DB transaction after real PUT.
                reached_upload = True
                return result

        row = await run(storage(RevokeAfterUpload), uploaded)
        assert reached_upload and row["status"] == "cancelled"
        assert row["object_key"] and row["object_version"] and row["sha256"]
        await denied(uploaded, body)

        await grant()
        available, body = await create("download-revoke")
        row = await run(storage(), available)
        assert row["status"] == "available"
        before = await request("GET", f"/exports/{available['id']}/download")
        assert before.content and before.headers["cache-control"] == "no-store"
        reached_read = False

        class RevokeAfterRead(S3ObjectStorage):
            async def get(self, location):
                nonlocal reached_read
                result = await super().get(location)
                await revoke()  # Commit between authorization and delivery.
                reached_read = True
                return result

        try:
            await AsyncpgSurveyExports(pool, storage(RevokeAfterRead)).download(
                uid, sid, UUID(available["id"])
            )
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Revoked download returned an artifact")
        assert reached_read
        await denied(available, body)
        # Reference retained for later retention, but no authorized download.
        assert (
            await conn.fetchval(
                "SELECT object_version FROM survey_export_job WHERE id=$1",
                UUID(available["id"]),
            )
            == row["object_version"]
        )

    await conn.close()
    await pool.close()
    (PROOF / "export-permission-boundaries.json").write_text(
        json.dumps(
            {
                "queuedRevocationCancelsWithoutObject": True,
                "revocationAfterRealUploadCancelsWithReference": True,
                "revocationDuringRealReadDeniesArtifactReturn": True,
                "revokedSelectionReplayAndVersionsDenied": True,
                "revokedJobReplayAndDownloadsDenied": True,
                "productionOutboxAndStorageAdapters": True,
            },
            indent=2,
        )
    )
    print(
        "PASS: committed grant revocation before queue processing, after real upload and during actual download; replay and selection denied"
    )


asyncio.run(main())
