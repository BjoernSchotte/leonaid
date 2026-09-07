"""Real process/storage/renderer recovery with production queue and export handler."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx
from openpyxl import load_workbook
from pypdf import PdfReader

from leonaid.adapters.postgres.outbox import AsyncpgOutboxQueue
from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.survey_exports import AsyncpgSurveyExports
from leonaid.adapters.storage.s3 import S3ObjectStorage
from leonaid.application.object_storage import ObjectLocation, ObjectWrite, StoredObject
from leonaid.application.outbox import OutboxWorker
from leonaid.domain.outbox import RetryPolicy

PROOF = Path("/proof")
STATE = PROOF / "export-recovery-state.json"
FORMULA_TEXT = '=HYPERLINK("https://example.invalid", "ü")'


class CrashAfterUpload(S3ObjectStorage):
    async def put_immutable(self, write: ObjectWrite) -> StoredObject:
        stored = await super().put_immutable(write)
        # The actual S3 adapter has already PUT and HEAD-verified the immutable
        # version. Terminate the process without rollback/handler completion.
        (PROOF / "export-upload-before-crash.json").write_text(
            json.dumps(
                {
                    "bucket": stored.location.bucket,
                    "key": stored.location.key,
                    "version": stored.location.version_id,
                    "sha256": stored.sha256,
                }
            )
        )
        os._exit(73)


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
    mode = sys.argv[1]
    if mode in {"crash", "renderer-fail"}:
        pool = await create_pool(os.environ["CORE_DATABASE_URL"])
        state = json.loads(STATE.read_text())
        async with pool.acquire() as conn:
            eligible = await conn.fetch(
                "SELECT id FROM outbox_event WHERE status='pending' AND available_at<=clock_timestamp()"
            )
            assert [str(r["id"]) for r in eligible] == [state["eventId"]]
        target = storage(CrashAfterUpload if mode == "crash" else S3ObjectStorage)
        if mode == "renderer-fail":
            os.environ["PATH"] = "/synthetic-missing-typst"
        worker = OutboxWorker(
            worker_id="survey-export-recovery-probe",
            queue=AsyncpgOutboxQueue(pool),
            handlers={"survey.export.render.v1": AsyncpgSurveyExports(pool, target)},
            retry_policy=RetryPolicy(base_delay=timedelta(seconds=1)),
        )
        assert await worker.run_once()
        assert mode != "crash", "Expected abrupt process exit after real upload"
        await pool.close()
        print(
            "PASS: actual missing Typst executable processed through production handler/outbox failure path"
        )
        return

    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    token = (PROOF / "session.env").read_text().strip().split("=", 1)[1]
    async with httpx.AsyncClient(
        base_url="http://api:8000",
        headers={"Cookie": f"__Host-leonaid_session={token}"},
        timeout=60,
    ) as client:

        async def call(method, path, body=None, expected=200):
            response = await client.request(method, path, json=body)
            assert response.status_code == expected, (
                path,
                response.status_code,
                expected,
            )
            return response

        if mode == "seed":
            scenario = sys.argv[2]
            product = (
                "responses_xlsx"
                if scenario == "crash"
                else "analysis_pdf"
                if scenario == "renderer"
                else "responses_csv"
            )
            sid = uuid4()
            path = f"/api/v1/surveys/{sid}"
            fixture = json.loads(
                Path("tests/fixtures/surveys/analysis-golden.json").read_text()
            )
            await call(
                "POST",
                path,
                {
                    "operationId": "create",
                    "title": "Synthetic export recovery",
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
            now = datetime.now(timezone.utc)
            answers = {**fixture["responses"][0], "text": FORMULA_TEXT, "number": ""}
            for response_answers in (answers, {}):
                await conn.execute(
                    """INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,status,answers,current_page,inactivity_timeout_seconds,created_at,last_answer_changed_at,completed_at)
                VALUES($1,$2,$3,$4,'completed',$5::jsonb,'main',3600,$6,$6,$6)""",
                    uuid4(),
                    sid,
                    UUID(version["id"]),
                    hashlib.sha256(os.urandom(48)).hexdigest(),
                    json.dumps(response_answers),
                    now,
                )
            snapshot = (
                await call(
                    "POST",
                    path + "/analysis",
                    {"operationId": "snapshot", "filter": {"versionId": version["id"]}},
                )
            ).json()
            body = {
                "operationId": scenario,
                "snapshotId": snapshot["id"],
                "product": product,
            }
            job = (await call("POST", path + "/exports", body)).json()
            assert job["status"] == "queued"
            event = await conn.fetchval(
                "SELECT event_id FROM survey_export_job WHERE id=$1", UUID(job["id"])
            )
            STATE.write_text(
                json.dumps(
                    {
                        "scenario": scenario,
                        "path": path,
                        "body": body,
                        "jobId": job["id"],
                        "eventId": str(event),
                    }
                )
            )
            print(f"PASS: {scenario} fixture queued through real API")
        else:
            state = json.loads(STATE.read_text())
            jid, eid = UUID(state["jobId"]), UUID(state["eventId"])
            job_path = state["path"] + "/exports/" + str(jid)
            if mode == "inspect-crash":
                row = await conn.fetchrow(
                    "SELECT j.status,j.bucket,e.status AS event_status,e.attempts FROM survey_export_job j JOIN outbox_event e ON e.id=j.event_id WHERE j.id=$1",
                    jid,
                )
                assert dict(row) == {
                    "status": "queued",
                    "bucket": None,
                    "event_status": "processing",
                    "attempts": 1,
                }
                uploaded = json.loads(
                    (PROOF / "export-upload-before-crash.json").read_text()
                )
                actual = await storage().get(
                    ObjectLocation(
                        uploaded["bucket"], uploaded["key"], uploaded["version"]
                    )
                )
                assert hashlib.sha256(actual.content).hexdigest() == uploaded["sha256"]
                await call("GET", job_path + "/download", expected=409)
                # Advance only this crashed fixture claim; production reclaim
                # code still decides whether the lease is eligible.
                await conn.execute(
                    "UPDATE outbox_event SET claimed_at=clock_timestamp()-interval '10 minutes' WHERE id=$1",
                    eid,
                )
                print(
                    "PASS: process died after real upload; transaction rolled back, download denied, stale claim made eligible"
                )
            elif mode == "inspect-failure":
                for _ in range(160):
                    row = await conn.fetchrow(
                        "SELECT status,last_error_code,last_error_detail FROM outbox_event WHERE id=$1",
                        eid,
                    )
                    if row["last_error_code"]:
                        break
                    await asyncio.sleep(0.25)
                assert (
                    row["last_error_code"]
                    == row["last_error_detail"]
                    == "survey_export_failed"
                )
                job = (await call("GET", job_path)).json()
                assert job["status"] in {"retrying", "processing", "failed"}
                assert (
                    await conn.fetchval(
                        "SELECT bucket FROM survey_export_job WHERE id=$1", jid
                    )
                    is None
                )
                await call("GET", job_path + "/download", expected=409)
                print(
                    "PASS: real failure persisted only stable error code; no false available file or download"
                )
            elif mode == "recover":
                for _ in range(240):
                    job = (await call("GET", job_path)).json()
                    if job["status"] in {"available", "failed"}:
                        break
                    await asyncio.sleep(0.25)
                assert job["status"] == "available", job["status"]
                response = await call("GET", job_path + "/download")
                row = await conn.fetchrow(
                    "SELECT j.*,e.attempts,e.status AS event_status FROM survey_export_job j JOIN outbox_event e ON e.id=j.event_id WHERE j.id=$1",
                    jid,
                )
                assert row["attempts"] >= 2 and row["event_status"] == "completed"
                assert hashlib.sha256(response.content).hexdigest() == row["sha256"]
                assert token.encode() not in response.content
                if state["scenario"] == "renderer":
                    reader = PdfReader(io.BytesIO(response.content))
                    assert len(reader.pages) >= 1
                    assert FORMULA_TEXT not in "\n".join(
                        page.extract_text() for page in reader.pages
                    )
                else:
                    if state["scenario"] == "crash":
                        book = load_workbook(
                            io.BytesIO(response.content), data_only=False
                        )
                        sheet = book["Responses"]
                        rows = list(sheet.values)
                        records = [dict(zip(rows[0], row)) for row in rows[1:]]
                        assert all(
                            cell.data_type != "f" and cell.hyperlink is None
                            for sheet in book
                            for row in sheet
                            for cell in row
                        )
                        expected_text = FORMULA_TEXT
                    else:
                        records = [
                            r
                            for r in csv.DictReader(
                                io.StringIO(response.content.decode("utf-8-sig"))
                            )
                            if r["record_type"] == "response"
                        ]
                        expected_text = "'" + FORMULA_TEXT
                    assert len(records) == 2
                    filled = next(r for r in records if r["q:text:type"] == "string")
                    empty = next(r for r in records if r["q:text:type"] == "missing")
                    assert filled["q:text"] == expected_text
                    assert (
                        filled["q:number"] in (None, "")
                        and filled["q:number:type"] == "string"
                    )
                    assert (
                        empty["q:number"] in (None, "")
                        and empty["q:number:type"] == "missing"
                    )
                    assert json.loads(filled["q:matrix"]) == {"r1": "good", "r2": "bad"}
                    assert json.loads(filled["q:multi"]) == ["a", "b"]
                assert (
                    await call("POST", state["path"] + "/exports", state["body"])
                ).json()["id"] == str(jid)
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM survey_export_job WHERE survey_id=$1",
                        row["survey_id"],
                    )
                    == 1
                )
                versions = await asyncio.to_thread(
                    storage()._client.list_object_versions,
                    Bucket=row["bucket"],
                    Prefix=row["object_key"],
                )
                exact = [
                    v
                    for v in versions.get("Versions", [])
                    if v["Key"] == row["object_key"]
                ]
                assert (
                    len(exact) == 1 and exact[0]["VersionId"] == row["object_version"]
                )
                if state["scenario"] == "crash":
                    uploaded = json.loads(
                        (PROOF / "export-upload-before-crash.json").read_text()
                    )
                    assert (
                        row["object_version"] == uploaded["version"]
                        and row["sha256"] == uploaded["sha256"]
                    )
                result_path = PROOF / "export-recovery-proof.json"
                result = (
                    json.loads(result_path.read_text()) if result_path.exists() else {}
                )
                result[state["scenario"]] = {
                    "sameJobRecovered": True,
                    "attempts": row["attempts"],
                    "immutableObjectVersions": len(exact),
                    "downloadHashVerified": True,
                    "idempotentRequestReplay": True,
                    "actualFileParsed": True,
                    "formulaUnicodeEmptyMatrixChecked": state["scenario"] != "renderer",
                }
                result_path.write_text(json.dumps(result, indent=2))
                print(
                    f"PASS: {state['scenario']} recovered same job with one immutable object version and verified authenticated download"
                )
            else:
                raise ValueError("Unknown phase")
    await conn.close()


asyncio.run(main())
