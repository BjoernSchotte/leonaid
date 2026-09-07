"""Drive real renderer failures while a browser observes the production job states."""

import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from leonaid.adapters.postgres.outbox import AsyncpgOutboxQueue
from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.survey_exports import AsyncpgSurveyExports
from leonaid.adapters.storage.s3 import S3ObjectStorage
from leonaid.application.outbox import OutboxWorker
from leonaid.domain.outbox import RetryPolicy

PROOF = Path("/proof")


async def signal(name):
    async with asyncio.timeout(90):
        path = PROOF / f"export-state-{name}.json"
        while not path.exists():
            await asyncio.sleep(0.1)
        return json.loads(path.read_text())


async def main():
    pool = await create_pool(os.environ["CORE_DATABASE_URL"])
    storage = S3ObjectStorage(
        endpoint_url=os.environ["OBJECT_STORAGE_ENDPOINT_URL"],
        access_key=os.environ["OBJECT_STORAGE_ACCESS_KEY"],
        secret_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],
        bucket=os.environ["OBJECT_STORAGE_BUCKET"],
        region=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1"),
        path_style=True,
    )
    worker = OutboxWorker(
        worker_id="survey-export-browser-state-probe",
        queue=AsyncpgOutboxQueue(pool),
        handlers={"survey.export.render.v1": AsyncpgSurveyExports(pool, storage)},
        retry_policy=RetryPolicy(base_delay=timedelta(0)),
    )

    async def run(job):
        async with pool.acquire() as conn:
            eligible = await conn.fetch(
                "SELECT aggregate_id FROM outbox_event WHERE status='pending' AND available_at<=clock_timestamp()"
            )
            assert [str(row["aggregate_id"]) for row in eligible] == [job["id"]]
        assert await worker.run_once()
        async with pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT j.status AS job_status,j.object_key,e.status,e.attempts,e.last_error_code,e.last_error_detail FROM survey_export_job j JOIN outbox_event e ON e.id=j.event_id WHERE j.id=$1",
                UUID(job["id"]),
            )

    first = await signal("queued")
    original_path = os.environ["PATH"]
    os.environ["PATH"] = "/synthetic-missing-typst"
    row = await run(first)
    assert row["status"] == "pending" and row["attempts"] == 1
    assert row["object_key"] is None
    await signal("retry-visible")
    for attempt in range(2, 6):
        row = await run(first)
        assert row["attempts"] == attempt
    assert row["status"] == "dead_letter" and row["job_status"] == "queued"
    assert row["object_key"] is None
    assert row["last_error_code"] == "survey_export_failed"
    assert row["last_error_detail"] == "survey_export_failed"
    os.environ["PATH"] = original_path
    second = await signal("replacement")
    assert second["id"] != first["id"]
    assert second["snapshotId"] == first["snapshotId"]
    row = await run(second)
    assert row["status"] == "completed" and row["job_status"] == "available"
    assert row["object_key"]
    async with pool.acquire() as conn:
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM survey_export_job WHERE snapshot_id=$1 AND product='analysis_pdf'",
                UUID(first["snapshotId"]),
            )
            == 2
        )
    await pool.close()
    (PROOF / "export-state-worker-proof.json").write_text(
        json.dumps(
            {
                "realMissingTypstFailures": 5,
                "retryVisibleBeforeFurtherAttempts": True,
                "deadLetterWithoutObject": True,
                "genericPersistedErrorOnly": True,
                "newJobSameSnapshotAfterRestoration": True,
                "replacementRenderedAndStored": True,
            },
            indent=2,
        )
    )
    print(
        "PASS: five real Typst failures, retry/dead-letter, then new browser job with actual restored renderer and storage"
    )


asyncio.run(main())
