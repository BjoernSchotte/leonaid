"""Exercise separate raw-response permissions against actual API and PostgreSQL."""

import asyncio
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest


async def main():
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    admin_token = Path("/proof/session.env").read_text().strip().split("=", 1)[1]
    admin = {"Cookie": f"__Host-leonaid_session={admin_token}"}
    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient(base_url="http://api:8000", timeout=60) as client:

        async def call(method, path, body=None, auth=admin, expected=200):
            result = await client.request(method, path, json=body, headers=auth)
            assert result.status_code == expected, (path, result.status_code, expected)
            if "/response-selections" in path and expected == 200:
                assert result.headers.get("cache-control") == "no-store"
            return result.json()

        definition = json.loads(
            Path("tests/fixtures/surveys/analysis-golden.json").read_text()
        )["definition"]

        for page in definition["pages"]:
            for question in page["elements"]:
                if question["name"] == "matrix":
                    question["title"] = "Bewertung"
                    question["rows"] = [
                        {"value": "r1", "text": "Organisation"},
                        {"value": "r2", "text": "Verpflegung"},
                    ]
                    question["columns"] = [
                        {"value": "good", "text": "Gut"},
                        {"value": "bad", "text": "Verbesserungsbedarf"},
                    ]
                elif question["name"] == "text":
                    question["title"] = "Rückmeldung"

        async def create_survey(title):
            sid = uuid4()
            path = f"/api/v1/surveys/{sid}"
            await call(
                "POST",
                path,
                {"operationId": "create", "title": title, "definition": definition},
            )
            version = await call(
                "POST",
                path + "/publish",
                {"operationId": "publish", "expectedRevision": 1},
            )
            return sid, path, UUID(version["id"])

        sid, path, version = await create_survey("Synthetic individual responses")
        foreign, foreign_path, foreign_version = await create_survey(
            "Synthetic other response scope"
        )
        endpoint = path + "/response-selections"
        principals = []
        for capability in ("read_responses", "view_aggregates"):
            uid, token = uuid4(), secrets.token_urlsafe(48)
            await conn.execute(
                "INSERT INTO user_account(id,email,display_name,status,email_verified_at) VALUES($1,$2,'Synthetic response reader','active',$3)",
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
            await conn.execute(
                "INSERT INTO survey_grant(survey_id,user_id,capability) VALUES($1,$2,$3)",
                sid,
                uid,
                capability,
            )
            principals.append(
                (uid, token, {"Cookie": f"__Host-leonaid_session={token}"})
            )
        reader_id, reader_token, reader = principals[0]
        analyst_id, analyst_token, analyst = principals[1]

        async def seed(answers, status="completed", test=False):
            pid, token = uuid4(), secrets.token_urlsafe(48)
            await conn.execute(
                "INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,status,answers,current_page,inactivity_timeout_seconds,is_test,created_at,last_answer_changed_at,completed_at) VALUES($1,$2,$3,$4,$5,$6::jsonb,'main',3600,$7,$8,$8,$9)",
                pid,
                sid,
                version,
                hashlib.sha256(token.encode()).hexdigest(),
                status,
                json.dumps(answers),
                test,
                now,
                now if status == "completed" else None,
            )
            return pid, token

        literal = '<img src=x onerror="window.rawAnswerExecuted=true"> Synthetic literal feedback'
        first, _ = await seed(
            {
                "text": literal,
                "nps": 10,
                "multi": ["a", "b"],
                "matrix": {"r1": "good", "r2": "bad"},
            }
        )
        partial, resume = await seed(
            {"text": "Saved partial feedback", "nps": 0}, "partial"
        )
        await seed({"text": "Open feedback", "nps": 5}, "in_progress")
        for _ in range(49):
            await seed({})
        test_id, _ = await seed({"text": "SENSITIVE_TEST_ONLY"}, test=True)
        filters = {"versionId": str(version)}
        body = {"operationId": "raw-selection", "filter": filters}
        selection = await call("POST", endpoint, body, reader)
        assert selection["total"] == 51
        assert selection == await call("POST", endpoint, body, reader)
        selected_path = endpoint + "/" + selection["id"]
        assert selection == await call("GET", selected_path, auth=reader)
        assert all(
            set(q) == {"id", "title", "kind", "choices", "rows"}
            for q in selection["questions"]
        )
        assert "statusCounts" not in selection and "answers" not in json.dumps(
            selection
        )
        await call(
            "POST",
            endpoint,
            {**body, "filter": {**filters, "statuses": ["completed"]}},
            reader,
            409,
        )
        pages = [
            await call(
                "GET", selected_path + f"/responses?offset={offset}", auth=reader
            )
            for offset in (0, 50, 100)
        ]
        assert [len(p["items"]) for p in pages] == [50, 1, 0]
        ids = [r["participationId"] for p in pages for r in p["items"]]
        assert len(set(ids)) == 51 and str(test_id) not in ids
        assert all("answers" not in item for p in pages for item in p["items"])
        detail_path = selected_path + f"/responses/{first}"
        detail = await call("GET", detail_path, auth=reader)
        assert detail["answers"]["text"] == literal
        texts_path = selected_path + "/free-text/text"
        texts = await call("GET", texts_path, auth=reader)
        assert texts["total"] == 2 and {t["text"] for t in texts["items"]} == {
            literal,
            "Saved partial feedback",
        }
        await call("GET", selected_path + "/free-text/nps", auth=reader, expected=404)
        await call(
            "GET", selected_path + "/free-text/missing", auth=reader, expected=404
        )
        await call(
            "GET", selected_path + "/responses?offset=-1", auth=reader, expected=422
        )
        await call(
            "GET", selected_path + "/responses?offset=5001", auth=reader, expected=422
        )
        await call(
            "GET", selected_path + f"/responses/{uuid4()}", auth=reader, expected=404
        )
        await call(
            "GET",
            foreign_path + "/response-selections/" + selection["id"],
            expected=404,
        )
        await call(
            "POST",
            endpoint,
            {
                "operationId": "foreign-version",
                "filter": {"versionId": str(foreign_version)},
            },
            reader,
            404,
        )
        assert (
            len((await call("GET", endpoint + "/versions", auth=reader))["items"]) == 1
        )
        await call("GET", path + "/analysis/versions", auth=reader, expected=404)

        for target in (
            endpoint + "/versions",
            selected_path,
            selected_path + "/responses",
            detail_path,
            texts_path,
        ):
            await call("GET", target, auth=analyst, expected=404)
            await call("GET", target, auth={}, expected=401)
        await call("POST", endpoint, body, analyst, 404)
        await call("POST", endpoint, body, {}, 401)
        test_body = {
            "operationId": "test-selection",
            "filter": {**filters, "isTest": True},
        }
        await call("POST", endpoint, test_body, reader, 404)
        test_selection = await call("POST", endpoint, test_body)
        assert test_selection["total"] == 1
        for suffix in ("", "/responses", f"/responses/{test_id}", "/free-text/text"):
            await call(
                "GET",
                endpoint + "/" + test_selection["id"] + suffix,
                auth=reader,
                expected=404,
            )

        # A real subsequent answer edit cannot rewrite a frozen selection.
        await call(
            "PUT",
            f"/api/v1/public/surveys/{sid}/participations/{partial}",
            {
                "operationId": "raw-change",
                "expectedRevision": 1,
                "answers": {"text": "Updated partial feedback", "nps": 0},
                "currentPage": "main",
            },
            {"Cookie": f"__Host-survey_{partial}={resume}"},
        )
        assert (
            await call("GET", selected_path + f"/responses/{partial}", auth=reader)
        )["answers"]["text"] == "Saved partial feedback"
        assert await call("GET", texts_path, auth=reader) == texts
        all_selection = await call(
            "POST",
            endpoint,
            {
                "operationId": "all-statuses",
                "filter": {
                    **filters,
                    "statuses": ["in_progress", "partial", "completed"],
                },
            },
            reader,
        )
        assert all_selection["total"] == 52
        latest = await call(
            "GET",
            endpoint + "/" + all_selection["id"] + f"/responses/{partial}",
            auth=reader,
        )
        assert latest["answers"]["text"] == "Updated partial feedback"

        await conn.execute(
            "DELETE FROM survey_grant WHERE survey_id=$1 AND user_id=$2", sid, reader_id
        )
        for target in (
            endpoint + "/versions",
            selected_path,
            selected_path + "/responses",
            detail_path,
            texts_path,
        ):
            await call("GET", target, auth=reader, expected=404)
        await call("POST", endpoint, body, reader, 404)
        await conn.execute(
            "INSERT INTO survey_grant(survey_id,user_id,capability) VALUES($1,$2,'read_responses')",
            sid,
            reader_id,
        )

        public = await call(
            "POST",
            path + "/analysis",
            {"operationId": "aggregate-privacy", "filter": filters},
            analyst,
        )
        assert literal not in json.dumps(public) and "feedback" not in json.dumps(
            public
        )
        serialized = json.dumps([selection, pages, detail, texts])
        assert all(
            secret not in serialized
            for secret in (reader_token, analyst_token, resume, admin_token)
        )
        assert all(
            key not in serialized
            for key in (
                "resume_digest",
                "recipient_email",
                "recipient_name",
                "SENSITIVE_TEST_ONLY",
            )
        )
        # Credentials are confined to the temporary harness directory for browser verification.
        Path("/proof/raw-response-access.json").write_text(
            json.dumps(
                {
                    "surveyId": str(sid),
                    "versionId": str(version),
                    "snapshotId": selection["id"],
                    "participationId": str(first),
                    "readerToken": reader_token,
                    "analystToken": analyst_token,
                    "literal": literal,
                }
            )
        )
        Path("/proof/raw-response-proof.json").write_text(
            json.dumps(
                {
                    "pagination": [50, 1, 0],
                    "selected": 51,
                    "allStatuses": 52,
                    "freeTextCount": 2,
                    "frozenAfterActualSave": True,
                    "separateReadCapability": True,
                    "revocationRechecked": True,
                    "testDataExcluded": True,
                    "credentialsExcluded": True,
                }
            )
        )
        print(
            "PASS: real raw-response capability isolation, frozen individual/free-text views, pagination, test/foreign rejection and revocation"
        )
    await conn.close()


asyncio.run(main())
