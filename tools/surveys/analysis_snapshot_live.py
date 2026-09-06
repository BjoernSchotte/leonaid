"""Real API/PostgreSQL analysis selection, authorization and immutable snapshot proof."""

import asyncio
import hashlib
import json
import math
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest


async def main():
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    token = Path("/proof/session.env").read_text().strip().split("=", 1)[1]
    admin = {"Cookie": f"__Host-leonaid_session={token}"}
    state_path = Path("/proof/analysis-state.json")
    async with httpx.AsyncClient(base_url="http://api:8000", timeout=60) as client:

        async def call(method, path, body=None, auth=admin, expected=200):
            r = await client.request(method, path, json=body, headers=auth)
            assert r.status_code == expected, (path, r.status_code, expected)
            return r.json()

        if sys.argv[1] == "recover":
            state = json.loads(state_path.read_text())
            for _ in range(100):
                status = await conn.fetchval(
                    "SELECT status FROM survey_participation WHERE id=$1",
                    UUID(state["overdue"]),
                )
                if status == "partial":
                    break
                await asyncio.sleep(0.1)
            assert status == "partial"
            after = await call(
                "POST",
                state["path"],
                {"operationId": "after-worker", "filter": state["filter"]},
            )
            for key in (
                "questions",
                "statusCounts",
                "participationCount",
                "lastPageCounts",
            ):
                assert after[key] == state["before"][key], key
            frozen = await call("GET", state["path"] + "/" + state["original"]["id"])
            assert frozen == state["original"]
            Path("/proof/survey-analysis-snapshot.json").write_text(
                json.dumps(state["original"])
            )
            state_path.unlink()
            print(
                "PASS: actual worker classification leaves analysis unchanged; original snapshot remains immutable after new saves and worker execution"
            )
            await conn.close()
            return

        fixture = json.loads(
            Path("tests/fixtures/surveys/analysis-golden.json").read_text()
        )
        definition = fixture["definition"]

        async def survey(title, invited=False):
            sid = uuid4()
            path = f"/api/v1/surveys/{sid}"
            await call(
                "POST",
                path,
                {"operationId": "create", "title": title, "definition": definition},
            )
            if invited:
                await call(
                    "PUT",
                    path + "/access",
                    {
                        "operationId": "access",
                        "expectedRevision": 1,
                        "accessMode": "invitation",
                    },
                )
            version = await call(
                "POST",
                path + "/publish",
                {"operationId": "publish", "expectedRevision": 1},
            )
            return sid, path, UUID(version["id"])

        sid, survey_path, version = await survey(
            "Synthetic snapshot selection", invited=True
        )
        foreign, foreign_path, foreign_version = await survey(
            "Synthetic private foreign survey"
        )
        path = survey_path + "/analysis"
        now = datetime.now(timezone.utc)
        identities = []
        for capability in ("view_aggregates", "design"):
            uid, secret = uuid4(), secrets.token_urlsafe(48)
            await conn.execute(
                "INSERT INTO user_account(id,email,display_name,status,email_verified_at) VALUES($1,$2,'Synthetic analyst','active',$3)",
                uid,
                f"{uid}@example.invalid",
                now,
            )
            await conn.execute(
                "INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$5,$5,$5)",
                uuid4(),
                uid,
                session_token_digest(secret),
                now + SESSION_LIFETIME,
                now,
            )
            await conn.execute(
                "INSERT INTO survey_grant(survey_id,user_id,capability) VALUES($1,$2,$3)",
                sid,
                uid,
                capability,
            )
            identities.append(
                (uid, secret, {"Cookie": f"__Host-leonaid_session={secret}"})
            )
        analyst_id, analyst_secret, analyst = identities[0]
        designer = identities[1][2]

        async def participation(
            answers, status="completed", vid=version, test=False, overdue=False
        ):
            pid, resume = uuid4(), secrets.token_urlsafe(48)
            created = (
                now - timedelta(minutes=2) if overdue else now - timedelta(minutes=1)
            )
            await conn.execute(
                "INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,status,answers,current_page,inactivity_timeout_seconds,is_test,created_at,last_answer_changed_at,completed_at) VALUES($1,$2,$3,$4,$5,$6::jsonb,'main',$7,$8,$9,$9,$10)",
                pid,
                sid,
                vid,
                hashlib.sha256(resume.encode()).hexdigest(),
                status,
                json.dumps(answers),
                1 if overdue else 3600,
                test,
                created,
                created if status == "completed" else None,
            )
            await conn.execute(
                "INSERT INTO survey_invitation(id,survey_id,recipient_email,recipient_name,token_digest,participation_id,redeemed_at,expires_at) VALUES($1,$2,'SENSITIVE_RECIPIENT@example.invalid','SENSITIVE_IDENTITY',$3,$4,now(),now()+interval '1 day')",
                uuid4(),
                sid,
                hashlib.sha256(resume.encode()).hexdigest(),
                pid,
            )
            return pid, resume

        participants = []
        for answers, status in zip(
            fixture["responses"],
            ["completed", "partial", "partial", "partial", "in_progress"],
            strict=True,
        ):
            participants.append(
                await participation(answers, status, overdue=status == "in_progress")
            )
        await participation({"nps": 5, "text": "SENSITIVE_IN_PROGRESS"}, "in_progress")
        await participation({"nps": 0, "text": "SENSITIVE_TEST"}, test=True)
        overdue_id, overdue_secret = participants[4]
        previous_change = await conn.fetchval(
            "SELECT last_answer_changed_at FROM survey_participation WHERE id=$1",
            overdue_id,
        )
        unchanged = await call(
            "PUT",
            f"/api/v1/public/surveys/{sid}/participations/{overdue_id}",
            {
                "operationId": "unchanged-analysis",
                "expectedRevision": 1,
                "answers": {},
                "currentPage": "main",
            },
            {"Cookie": f"__Host-survey_{overdue_id}={overdue_secret}"},
        )
        assert unchanged["status"] == "partial"
        assert (
            await conn.fetchval(
                "SELECT last_answer_changed_at FROM survey_participation WHERE id=$1",
                overdue_id,
            )
            == previous_change
        )
        await conn.execute(
            "UPDATE survey_participation SET current_page='SENSITIVE_UNKNOWN_PAGE' WHERE id=$1",
            participants[4][0],
        )

        second_version = uuid4()
        second_definition = json.loads(json.dumps(definition))
        second_definition["pages"][0]["title"] = "Second version"
        await conn.execute(
            "INSERT INTO survey_version(id,survey_id,number,definition,schema_hash,renderer_version,capability_profile) VALUES($1,$2,2,$3::jsonb,$4,'3.0.3','initial-v1')",
            second_version,
            sid,
            json.dumps(second_definition),
            hashlib.sha256(json.dumps(second_definition).encode()).hexdigest(),
        )
        await conn.execute(
            "UPDATE survey SET published_version_id=$2,revision=revision+1 WHERE id=$1",
            sid,
            second_version,
        )
        await participation({"nps": 0}, vid=second_version)
        versions = await call("GET", path + "/versions", auth=analyst)
        previous_settings = await call("GET", "/api/v1/survey-settings")
        await call(
            "PUT",
            "/api/v1/survey-settings",
            {
                "operationId": "analysis-default-change",
                "expectedRevision": previous_settings["revision"],
                "inactivityTimeoutSeconds": 5,
            },
        )
        previous_survey = await call("GET", survey_path)
        await call(
            "PUT",
            survey_path + "/settings",
            {
                "operationId": "analysis-override-change",
                "expectedRevision": previous_survey["revision"],
                "inactivityTimeoutSeconds": 2,
            },
        )
        assert [v["number"] for v in versions["items"]] == [2, 1]
        assert not any("definition" in v for v in versions["items"])
        filters = {"versionId": str(version)}
        body = {"operationId": "golden", "filter": filters}
        original = await call("POST", path, body, analyst)
        assert original == await call("POST", path, body, analyst)
        assert original == await call("GET", path + "/" + original["id"], auth=analyst)
        assert original["participationCount"] == 5
        assert original["statusCounts"] == {
            "in_progress": 1,
            "partial": 4,
            "completed": 1,
        }
        q = {row["questionId"]: row for row in original["questions"]}
        assert math.isclose(q["nps"]["nps"], 100 / 3)
        assert [(x["count"], x["percentage"]) for x in q["multi"]["counts"]] == [
            (2, 100),
            (1, 50),
        ]
        assert (q["number"]["mean"], q["follow"]["hidden"]) == (15, 2)
        public_text = json.dumps(original)
        assert [
            (row["answered"], row["unanswered"], row["invalid"])
            for row in q["matrix"]["matrixRows"]
        ] == [(2, 2, 1), (1, 3, 1)]
        assert (
            q["text"]["answered"],
            q["text"]["invalid"],
            q["date"]["answered"],
            q["date"]["invalid"],
        ) == (2, 1, 1, 1)
        assert [
            (page["pageId"], page["count"]) for page in original["lastPageCounts"]
        ] == [("main", 4), ("followup", 0), (None, 1)]
        for marker in (
            "SENSITIVE_",
            "answers",
            "private_responses",
            "recipientEmail",
            "participationId",
            token,
            analyst_secret,
            participants[0][1],
        ):
            assert marker not in public_text, "Protected data in aggregate payload"
        stored = await conn.fetchrow(
            "SELECT payload,private_responses FROM survey_analysis_snapshot WHERE id=$1",
            UUID(original["id"]),
        )
        assert "SENSITIVE_FIRST_TEXT" in stored["private_responses"]
        assert "SENSITIVE_RECIPIENT" not in stored["private_responses"]
        assert participants[0][1] not in stored["private_responses"]
        try:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE survey_analysis_snapshot SET payload='{}'::jsonb WHERE id=$1",
                    UUID(original["id"]),
                )
        except asyncpg.PostgresError as error:
            assert error.sqlstate == "23000"
        else:
            raise AssertionError("Snapshot update was accepted")

        await call(
            "POST",
            path,
            {**body, "filter": {**filters, "statuses": ["completed"]}},
            analyst,
            409,
        )
        completed = await call(
            "POST",
            path,
            {
                "operationId": "completed",
                "filter": {**filters, "statuses": ["completed"]},
            },
            analyst,
        )
        assert completed["participationCount"] == 1
        assert (
            next(q for q in completed["questions"] if q["questionId"] == "nps")["nps"]
            == 100
        )
        v2 = await call(
            "POST",
            path,
            {"operationId": "v2", "filter": {"versionId": str(second_version)}},
            analyst,
        )
        assert v2["participationCount"] == 1 and v2["versionNumber"] == 2
        assert (
            next(q for q in v2["questions"] if q["questionId"] == "nps")["nps"] == -100
        )
        test_snapshot = await call(
            "POST", path, {"operationId": "test", "filter": {**filters, "isTest": True}}
        )
        assert test_snapshot["participationCount"] == 1
        await call("GET", path + "/" + test_snapshot["id"], auth=analyst, expected=404)
        await call(
            "POST",
            path,
            {"operationId": "test-denied", "filter": {**filters, "isTest": True}},
            analyst,
            404,
        )
        for headers in (designer, {}):
            await call("POST", path, body, headers, 404 if headers else 401)
        await call(
            "POST",
            path,
            {
                "operationId": "foreign-version",
                "filter": {"versionId": str(foreign_version)},
            },
            analyst,
            404,
        )
        await call(
            "GET", foreign_path + "/analysis/versions", auth=analyst, expected=404
        )
        await call("GET", path + "/" + str(uuid4()), auth=analyst, expected=404)
        for bad in (
            {},
            {**filters, "statuses": ["unknown"]},
            {**filters, "statuses": ["partial", "partial"]},
            {**filters, "createdFrom": "2026-01-01"},
            {
                **filters,
                "createdFrom": "2026-09-02T00:00:00Z",
                "createdBefore": "2026-09-01T00:00:00Z",
            },
            {**filters, "recipientEmail": "forged"},
        ):
            await call(
                "POST", path, {"operationId": str(uuid4()), "filter": bad}, analyst, 422
            )
        empty = await call(
            "POST",
            path,
            {
                "operationId": "future",
                "filter": {**filters, "createdFrom": "2099-01-01T00:00:00Z"},
            },
            analyst,
        )
        assert empty["participationCount"] == 0 and all(
            q["nps"] is None and q["answered"] == 0 for q in empty["questions"]
        )
        before = await call(
            "POST",
            path,
            {
                "operationId": "before",
                "filter": {
                    **filters,
                    "createdBefore": (now - timedelta(seconds=90)).isoformat(),
                },
            },
            analyst,
        )
        assert (
            before["participationCount"] == 1 and before["statusCounts"]["partial"] == 1
        )
        boundary = now - timedelta(minutes=1)
        inclusive = await call(
            "POST",
            path,
            {
                "operationId": "inclusive",
                "filter": {
                    **filters,
                    "createdFrom": boundary.astimezone(
                        timezone(timedelta(hours=2))
                    ).isoformat(),
                },
            },
            analyst,
        )
        assert inclusive["participationCount"] == 4
        assert inclusive["filter"]["createdFrom"] == boundary.isoformat()
        exclusive = await call(
            "POST",
            path,
            {
                "operationId": "exclusive",
                "filter": {**filters, "createdBefore": boundary.isoformat()},
            },
            analyst,
        )
        assert exclusive["participationCount"] == 1
        await conn.execute(
            "DELETE FROM survey_grant WHERE survey_id=$1 AND user_id=$2",
            sid,
            analyst_id,
        )
        await call("GET", path + "/" + original["id"], auth=analyst, expected=404)
        await call("POST", path, body, analyst, 404)
        await call("GET", path + "/versions", auth=analyst, expected=404)
        action = uuid4()
        await conn.execute(
            "INSERT INTO charity_action(id,carrier_name,name,purpose,status,starts_on,ends_on,archive_slug,goal_value,actual_value,goal_unit,currency) VALUES($1,'Synthetic charity','Analysis scope','Synthetic proof','draft','2026-09-01','2026-11-15',$2,0,0,'cent','EUR')",
            action,
            f"analysis-{action}",
        )
        await conn.execute(
            "UPDATE survey SET action_id=$2,revision=revision+1 WHERE id=$1",
            sid,
            action,
        )
        await conn.execute(
            "INSERT INTO survey_grant(survey_id,user_id,capability) VALUES($1,$2,'view_aggregates')",
            sid,
            analyst_id,
        )
        await call("GET", path + "/" + original["id"], auth=analyst, expected=404)
        await conn.execute(
            "INSERT INTO action_membership(id,action_id,user_id,role) VALUES($1,$2,$3,'acquirer')",
            uuid4(),
            action,
            analyst_id,
        )
        assert original == await call("GET", path + "/" + original["id"], auth=analyst)
        await conn.execute(
            "DELETE FROM action_membership WHERE action_id=$1 AND user_id=$2",
            action,
            analyst_id,
        )
        await call("GET", path + "/" + original["id"], auth=analyst, expected=404)

        pid, resume = participants[1]
        await call(
            "PUT",
            f"/api/v1/public/surveys/{sid}/participations/{pid}",
            {
                "operationId": "later-answer",
                "expectedRevision": 1,
                "answers": {
                    "gate": "yes",
                    "nps": 0,
                    "number": 20,
                    "multi": ["a"],
                    "matrix": {"r1": "bad"},
                    "text": "SENSITIVE_UPDATED",
                },
                "currentPage": "main",
            },
            {"Cookie": f"__Host-survey_{pid}={resume}"},
        )
        assert original == await call("GET", path + "/" + original["id"])
        all_filters = {**filters, "statuses": ["in_progress", "partial", "completed"]}
        changed = await call(
            "POST", path, {"operationId": "after-save", "filter": all_filters}
        )
        assert changed["participationCount"] == 6
        assert (
            next(q for q in changed["questions"] if q["questionId"] == "nps")["nps"]
            == -50
        )
        assert (
            await conn.fetchval(
                "SELECT status FROM survey_participation WHERE id=$1",
                participants[4][0],
            )
            == "in_progress"
        )
        # More than one engine batch: denominators must be recomputed globally.
        await conn.execute(
            "INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,status,answers,inactivity_timeout_seconds,completed_at) SELECT gen_random_uuid(),$1,$2,md5(random()::text||n::text),'completed',CASE WHEN n<=100 THEN '{\"nps\":0}'::jsonb ELSE '{\"nps\":10}'::jsonb END,3600,now() FROM generate_series(1,101) n",
            foreign,
            foreign_version,
        )
        batched = await call(
            "POST",
            foreign_path + "/analysis",
            {"operationId": "batch", "filter": {"versionId": str(foreign_version)}},
        )
        assert batched["participationCount"] == 101
        batch_rating = next(q for q in batched["questions"] if q["questionId"] == "nps")
        assert math.isclose(batch_rating["nps"], -9900 / 101)
        assert math.isclose(batch_rating["mean"], 10 / 101)
        await call("GET", path + "/" + batched["id"], expected=404)
        await conn.execute(
            "INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,answers,inactivity_timeout_seconds) VALUES($1,$2,$3,$4,'{\"nps\":10}',3600)",
            uuid4(),
            foreign,
            foreign_version,
            str(uuid4()),
        )
        summary = await call("GET", foreign_path)
        await call(
            "PUT",
            foreign_path + "/schedule",
            {
                "operationId": "deadline",
                "expectedRevision": summary["revision"],
                "endsAt": (
                    datetime.now(timezone.utc) + timedelta(seconds=1)
                ).isoformat(),
            },
        )
        await asyncio.sleep(2.2)
        deadline = await call(
            "POST",
            foreign_path + "/analysis",
            {
                "operationId": "deadline-analysis",
                "filter": {"versionId": str(foreign_version)},
            },
        )
        assert deadline["statusCounts"] == {
            "completed": 101,
            "partial": 1,
            "in_progress": 0,
        }
        assert deadline["participationCount"] == 102
        summary = await call("GET", foreign_path)
        await call(
            "POST",
            foreign_path + "/transition",
            {
                "operationId": "end",
                "expectedRevision": summary["revision"],
                "action": "end",
            },
        )
        summary = await call("GET", foreign_path)
        await call(
            "POST",
            foreign_path + "/transition",
            {
                "operationId": "archive",
                "expectedRevision": summary["revision"],
                "action": "archive",
            },
        )
        assert batched == await call("GET", foreign_path + "/analysis/" + batched["id"])
        summary = await call("GET", foreign_path)
        await call(
            "POST",
            foreign_path + "/transition",
            {
                "operationId": "trash",
                "expectedRevision": summary["revision"],
                "action": "trash",
            },
        )
        await call("GET", foreign_path + "/analysis/" + batched["id"], expected=409)
        limit_sid, limit_path, limit_version = await survey("Synthetic analysis limits")
        limit_body = {
            "operationId": "limit",
            "filter": {"versionId": str(limit_version)},
        }
        await conn.execute(
            "INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,status,answers,inactivity_timeout_seconds,completed_at) SELECT gen_random_uuid(),$1,$2,md5(random()::text||n::text),'completed','{}',3600,now() FROM generate_series(1,5001) n",
            limit_sid,
            limit_version,
        )
        limited = await call("POST", limit_path + "/analysis", limit_body, expected=422)
        assert limited["error"]["code"] == "limit_exceeded"
        await conn.execute(
            "DELETE FROM survey_participation WHERE survey_id=$1", limit_sid
        )
        await conn.execute(
            "INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,status,answers,inactivity_timeout_seconds,completed_at) SELECT gen_random_uuid(),$1,$2,md5(random()::text||n::text),'completed',jsonb_build_object('gate','yes','text',repeat('x',10000),'follow',repeat('x',10000)),3600,now() FROM generate_series(1,1700) n",
            limit_sid,
            limit_version,
        )
        limited = await call("POST", limit_path + "/analysis", limit_body, expected=422)
        assert limited["error"]["code"] == "limit_exceeded"
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM survey_analysis_snapshot WHERE survey_id=$1",
                limit_sid,
            )
            == 0
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM survey_operation WHERE survey_id=$1 AND scope LIKE '%analysis-create'",
                limit_sid,
            )
            == 0
        )
        await conn.execute(
            "DELETE FROM survey_participation WHERE survey_id=$1", limit_sid
        )
        recovered_limit = await call("POST", limit_path + "/analysis", limit_body)
        assert recovered_limit["participationCount"] == 0
        current_survey = await call("GET", survey_path)
        await call(
            "PUT",
            survey_path + "/settings",
            {
                "operationId": "analysis-override-restore",
                "expectedRevision": current_survey["revision"],
                "inactivityTimeoutSeconds": previous_survey["inactivityTimeoutSeconds"],
            },
        )
        current_settings = await call("GET", "/api/v1/survey-settings")
        await call(
            "PUT",
            "/api/v1/survey-settings",
            {
                "operationId": "analysis-default-restore",
                "expectedRevision": current_settings["revision"],
                "inactivityTimeoutSeconds": previous_settings[
                    "inactivityTimeoutSeconds"
                ],
            },
        )
        state_path.write_text(
            json.dumps(
                {
                    "path": path,
                    "filter": all_filters,
                    "before": changed,
                    "original": original,
                    "overdue": str(participants[4][0]),
                }
            )
        )
        print(
            "PASS: actual analysis API proves version/status/date/test selection, aggregate-only privacy and revocation, idempotency, frozen raw/public snapshots, batch combination and worker-lag classification"
        )
    await conn.close()


asyncio.run(main())
