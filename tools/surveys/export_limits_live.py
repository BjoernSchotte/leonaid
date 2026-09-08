"""Actual export admission, expiry selection, worker/storage and log fixtures."""

import asyncio
import csv
import io
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx
from openpyxl import load_workbook
from pypdf import PdfReader

from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest


async def main():
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    token = Path("/proof/session.env").read_text().strip().split("=", 1)[1]
    marker = "EXPORT_PRIVATE_" + secrets.token_hex(16)
    markers = [token, marker]
    async with httpx.AsyncClient(
        base_url="http://api:8000",
        headers={"Cookie": f"__Host-leonaid_session={token}"},
        timeout=90,
    ) as client:

        async def call(method, path, body=None, expected=200, headers=None):
            response = await client.request(method, path, json=body, headers=headers)
            assert response.status_code == expected, (response.status_code, expected)
            return response

        surveys = []
        for _ in range(2):
            sid = uuid4()
            path = f"/api/v1/surveys/{sid}"
            await call(
                "POST",
                path,
                {
                    "operationId": "create",
                    "title": "Synthetic export limit",
                    "definition": {
                        "pages": [
                            {
                                "name": "one",
                                "elements": [
                                    {
                                        "type": "comment",
                                        "name": "answer",
                                        "title": "Feedback",
                                    }
                                ],
                            }
                        ]
                    },
                },
            )
            version = (
                await call(
                    "POST",
                    path + "/publish",
                    {"operationId": "publish", "expectedRevision": 1},
                )
            ).json()
            secret = secrets.token_urlsafe(48)
            markers.append(secret)
            public = f"/api/v1/public/surveys/{sid}/participations"
            participation = (
                await call(
                    "POST", public, {"operationId": "start", "resumeSecret": secret}
                )
            ).json()
            resume = {"Cookie": f"__Host-survey_{participation['id']}={secret}"}
            response_path = public + "/" + participation["id"]
            await call(
                "PUT",
                response_path,
                {
                    "operationId": "save",
                    "expectedRevision": 1,
                    "answers": {"answer": marker},
                    "currentPage": "one",
                },
                headers=resume,
            )
            await call(
                "POST",
                response_path + "/complete",
                {"operationId": "complete", "expectedRevision": 2},
                headers=resume,
            )
            snapshot = (
                await call(
                    "POST",
                    path + "/analysis",
                    {"operationId": "snapshot", "filter": {"versionId": version["id"]}},
                )
            ).json()
            surveys.append((sid, path, snapshot["id"]))
        sid, path, snapshot = surveys[0]
        body = {
            "operationId": "first",
            "snapshotId": snapshot,
            "product": "responses_csv",
        }
        first = (await call("POST", path + "/exports", body)).json()
        source = await conn.fetchrow(
            "SELECT * FROM survey_export_job WHERE id=$1", UUID(first["id"])
        )
        uid = source["requested_by"]

        async def seed_history(expired=False):
            ids = []
            # Cancelled/completed fixture history still consumes the quota when
            # recent; it never schedules 58 redundant renderer executions.
            for _ in range(58):
                jid, eid = uuid4(), uuid4()
                await conn.execute(
                    "INSERT INTO outbox_event(id,aggregate_type,aggregate_id,event_type,idempotency_key,payload,status) VALUES($1,'survey_export',$2,'survey.export.render.v1',$3,'{}','completed')",
                    eid,
                    jid,
                    f"fixture:{jid}",
                )
                await conn.execute(
                    """INSERT INTO survey_export_job(id,survey_id,snapshot_id,requested_by,operation_id,request_hash,title,product,event_id,status,created_at)
                VALUES($1,$2,$3,$4,$5,$6,$7,'responses_csv',$8,'cancelled',clock_timestamp()-($9 * interval '1 second'))""",
                    jid,
                    sid,
                    UUID(snapshot),
                    uid,
                    str(jid),
                    source["request_hash"],
                    "Synthetic quota history",
                    eid,
                    601 if expired else 0,
                )
                ids.append((jid, eid))
            return ids

        history = await seed_history()
        attempts = [
            {"operationId": "race", "snapshotId": item[2], "product": "analysis_xlsx"}
            for item in surveys
        ]
        results = await asyncio.gather(
            *[
                client.post(item[1] + "/exports", json=attempt)
                for item, attempt in zip(surveys, attempts)
            ]
        )
        assert sorted(r.status_code for r in results) == [200, 429]
        assert (
            next(r for r in results if r.status_code == 429).json()["error"]["code"]
            == "limit_exceeded"
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM survey_export_job WHERE requested_by=$1", uid
            )
            == 60
        )
        other_uid, other_token = uuid4(), secrets.token_urlsafe(48)
        markers.append(other_token)
        now = datetime.now(timezone.utc)
        await conn.execute(
            "INSERT INTO user_account(id,email,display_name,status,email_verified_at) VALUES($1,$2,'Synthetic independent exporter','active',$3)",
            other_uid,
            f"{other_uid}@example.invalid",
            now,
        )
        await conn.execute(
            "INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$5,$5,$5)",
            uuid4(),
            other_uid,
            session_token_digest(other_token),
            now + SESSION_LIFETIME,
            now,
        )
        await conn.execute(
            "INSERT INTO survey_grant(survey_id,user_id,capability) VALUES($1,$2,'export_raw')",
            sid,
            other_uid,
        )
        await call(
            "POST",
            path + "/exports",
            {**body, "operationId": "other-user"},
            headers={"Cookie": f"__Host-leonaid_session={other_token}"},
        )
        before_events = await conn.fetchval(
            "SELECT count(*) FROM outbox_event WHERE event_type='survey.export.render.v1'"
        )
        blocked = {**body, "operationId": "blocked"}
        await call("POST", path + "/exports", blocked, 429)
        assert (await call("POST", path + "/exports", body)).json()["id"] == first["id"]
        await call("POST", path + "/exports", {**body, "product": "analysis_pdf"}, 409)
        await call("POST", path + "/exports", blocked, 401, {"Cookie": ""})
        await call("POST", f"/api/v1/surveys/{uuid4()}/exports", blocked, 404)
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM outbox_event WHERE event_type='survey.export.render.v1'"
            )
            == before_events
        )
        assert not await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM survey_export_job WHERE requested_by=$1 AND operation_id='blocked')",
            uid,
        )

        # Replace only synthetic history with expired rows; actual job timestamps
        # remain immutable. This deterministically tests the rolling-window SQL.
        for jid, eid in history:
            await conn.execute("DELETE FROM survey_export_job WHERE id=$1", jid)
            await conn.execute("DELETE FROM outbox_event WHERE id=$1", eid)
        await seed_history(expired=True)
        resumed = (await call("POST", path + "/exports", blocked)).json()
        assert resumed["id"] != first["id"]
        assert (await call("POST", path + "/exports", blocked)).json()["id"] == resumed[
            "id"
        ]
        jobs = {"responses_csv": resumed["id"]}
        print(
            "PASS: admission, cross-survey concurrency, independent requester, authorization, replay and expired-history selection",
            flush=True,
        )
        for product in ("responses_xlsx", "analysis_xlsx", "analysis_pdf"):
            jobs[product] = (
                await call(
                    "POST",
                    path + "/exports",
                    {
                        "operationId": product,
                        "snapshotId": snapshot,
                        "product": product,
                    },
                )
            ).json()["id"]
        for product, jid in jobs.items():
            try:
                async with asyncio.timeout(90):
                    while True:
                        status = (await call("GET", path + f"/exports/{jid}")).json()[
                            "status"
                        ]
                        assert status not in {"failed", "cancelled"}, (product, status)
                        if status == "available":
                            break
                        await asyncio.sleep(0.2)
            except TimeoutError:
                diagnostic = await conn.fetchrow(
                    "SELECT j.status,e.status AS event_status,e.attempts,e.last_error_code FROM survey_export_job j JOIN outbox_event e ON e.id=j.event_id WHERE j.id=$1",
                    UUID(jid),
                )
                raise AssertionError((product, dict(diagnostic))) from None
            content = (await call("GET", path + f"/exports/{jid}/download")).content
            if product == "responses_csv":
                assert any(
                    marker in cell
                    for row in csv.reader(io.StringIO(content.decode("utf-8-sig")))
                    for cell in row
                )
            elif product.endswith("xlsx"):
                workbook = load_workbook(io.BytesIO(content), data_only=True)
                text = " ".join(
                    str(cell.value)
                    for sheet in workbook
                    for row in sheet
                    for cell in row
                )
                assert (marker in text) == (product == "responses_xlsx")
            else:
                assert marker not in " ".join(
                    page.extract_text() for page in PdfReader(io.BytesIO(content)).pages
                )
            assert token.encode() not in content
            row = await conn.fetchrow(
                "SELECT status,size_bytes,object_version FROM survey_export_job WHERE id=$1",
                UUID(jid),
            )
            assert (
                row["status"] == "available"
                and row["size_bytes"] == len(content)
                and row["object_version"]
            )
    await conn.close()
    Path("/proof/export-limit-markers.json").write_text(json.dumps(markers))
    Path("/proof/export-limits-proof.json").write_text(
        json.dumps(
            {
                "syntheticOnly": True,
                "jobsPerWindow": 60,
                "windowSeconds": 600,
                "syntheticHistoryRows": 58,
                "concurrentCrossSurveyStatuses": [200, 429],
                "noRejectedJobOrOutboxReceipt": True,
                "replaySurvivesExhaustion": True,
                "authorizationPrecedesQuota": True,
                "expiredHistoryAllowsExactRejectedOperation": True,
                "otherAuthorizedRequesterHasIndependentQuota": True,
                "realWorkerProductsDownloadedAndParsed": sorted(jobs),
                "rawAnswerPresentOnlyInRawProducts": True,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        "PASS: cross-survey export quota, concurrent last permit, authorized replay, no rejection receipts, expired-history recovery, four real worker/storage products"
    )


asyncio.run(main())
