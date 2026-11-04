"""Seed the survey evaluation journey (Task 5.6b) against the actual API and PostgreSQL.

One published survey with 30 synthetic participations, a raw reader
(read_responses) and an aggregate-only member (view_aggregates). Checks the
minimum group size (k = 5) on the aggregate endpoints and fields=choice on the
listing, then leaves an access file for tests/e2e/surveys-summary.spec.mjs.
"""

import asyncio
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest

# 30 participations. NPS: detractors 6, passives 8, promoters 16, one score
# with 2 people (withheld). Matrix row r2: 3 "good" (withheld) and 27 "bad"
# (withheld too: it would reveal the 3).
NPS = [3] * 2 + [5] * 2 + [6] * 2 + [7] * 3 + [8] * 5 + [9] * 6 + [10] * 10
TEXTS = [
    "Packstation früher öffnen.",
    "Mehr Fahrer am Samstag.",
    '<img src=x onerror="window.summaryExecuted=true"> Synthetic summary quote',
]


def answers(index: int) -> dict:
    value: dict = {
        "gate": "yes" if index < 18 else "no",
        "multi": ["a", "b"] if index < 9 else ["a"] if index < 20 else ["b"],
        "nps": NPS[index],
        "number": index + 1,
        "matrix": {
            "r1": "good" if index < 22 else "bad",
            "r2": "good" if index < 3 else "bad",
        },
        "date": f"2026-10-{index % 28 + 1:02d}",
    }
    if index < len(TEXTS) * 4:
        value["text"] = TEXTS[index % len(TEXTS)]
    return value


async def main():
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    admin_token = Path("/proof/session.env").read_text().strip().split("=", 1)[1]
    admin = {"Cookie": f"__Host-leonaid_session={admin_token}"}
    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient(base_url="http://api:8000", timeout=120) as client:

        async def call(method, path, body=None, auth=admin, expected=200, params=None):
            result = await client.request(
                method, path, json=body, headers=auth, params=params
            )
            assert result.status_code == expected, (
                path,
                result.status_code,
                result.text,
            )
            return result.json()

        definition = json.loads(
            Path("tests/fixtures/surveys/analysis-golden.json").read_text()
        )["definition"]
        titles = {
            "gate": "Haben Sie beim Ausliefern geholfen?",
            "multi": "Welche Aufgaben hatten Sie?",
            "nps": "Wie wahrscheinlich empfehlen Sie die Aktion weiter?",
            "number": "Wie viele Stunden waren Sie dabei?",
            "matrix": "Bewertung",
            "text": "Was sollten wir anders machen?",
            "date": "Wann waren Sie dabei?",
        }
        for page in definition["pages"]:
            for question in page["elements"]:
                question["title"] = titles.get(question["name"], question["name"])
                if question["name"] == "gate":
                    question["choices"] = [
                        {"value": "yes", "text": "Ja"},
                        {"value": "no", "text": "Nein"},
                    ]
                if question["name"] == "matrix":
                    question["rows"] = [
                        {"value": "r1", "text": "Organisation"},
                        {"value": "r2", "text": "Verpflegung"},
                    ]
                    question["columns"] = [
                        {"value": "good", "text": "Gut"},
                        {"value": "bad", "text": "Verbesserungsbedarf"},
                    ]
        sid = uuid4()
        path = f"/api/v1/surveys/{sid}"
        await call(
            "POST",
            path,
            {
                "operationId": "create",
                "title": "Helferbefragung Auswertung",
                "definition": definition,
            },
        )
        version = await call(
            "POST", path + "/publish", {"operationId": "publish", "expectedRevision": 1}
        )
        principals = {}
        for capability in ("read_responses", "view_aggregates"):
            uid, token = uuid4(), secrets.token_urlsafe(48)
            await conn.execute(
                "INSERT INTO user_account(id,email,display_name,status,email_verified_at) VALUES($1,$2,'Synthetic summary member','active',$3)",
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
            principals[capability] = (
                token,
                {"Cookie": f"__Host-leonaid_session={token}"},
            )
        reader_token, reader = principals["read_responses"]
        analyst_token, analyst = principals["view_aggregates"]
        for index in range(30):
            await conn.execute(
                "INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,status,answers,current_page,inactivity_timeout_seconds,is_test,created_at,last_answer_changed_at,completed_at) VALUES($1,$2,$3,$4,'completed',$5::jsonb,'main',3600,false,$6,$6,$6)",
                uuid4(),
                sid,
                UUID(version["id"]),
                hashlib.sha256(secrets.token_bytes(16)).hexdigest(),
                json.dumps(answers(index)),
                now - timedelta(days=2),
            )
        selection = await call(
            "POST",
            path + "/response-selections",
            {"operationId": "summary", "filter": {"versionId": version["id"]}},
            reader,
        )
        assert selection["total"] == 30
        base = path + "/response-selections/" + selection["id"]
        shown = await call("GET", base + "/aggregates", auth=reader)
        q = {item["questionId"]: item for item in shown["questions"]}
        assert shown["minimumGroupSize"] == 5 and not shown["suppressed"]
        assert q["nps"]["npsSegments"] == {
            "detractors": 6,
            "passives": 8,
            "promoters": 16,
        }
        # Scores 3, 5, 6 (2 people each) and 7 (3) are withheld.
        nps_counts = {c["value"]: c["count"] for c in q["nps"]["counts"]}
        assert nps_counts[3] is None and nps_counts[10] == 10
        rows = {row["rowId"]: row for row in q["matrix"]["matrixRows"]}
        assert [c["count"] for c in rows["r1"]["counts"]] == [22, 8]
        assert [c["count"] for c in rows["r2"]["counts"]] == [None, None]
        assert "SENSITIVE" not in json.dumps(shown) and "Packstation" not in json.dumps(
            shown
        )
        # The aggregate-only member reads the same disclosed numbers through
        # the analysis endpoint, but nothing raw.
        assert shown == await call(
            "GET", path + "/analysis/" + selection["id"], auth=analyst
        )
        for suffix in ("/aggregates", "/responses", "/free-text/text"):
            await call("GET", base + suffix, auth=analyst, expected=404)
        narrow = await call(
            "POST",
            path + "/analysis",
            {
                "operationId": "narrow",
                "filter": {
                    "versionId": version["id"],
                    "createdFrom": (now - timedelta(hours=3)).isoformat(),
                },
            },
            analyst,
            422,
        )
        assert narrow["error"]["code"] == "range_too_narrow"
        # fields=choice: option labels only, never free text.
        listing = await call(
            "GET",
            base + "/responses",
            auth=reader,
            params={"limit": 5000, "fields": "choice"},
        )
        chosen = [item["choiceAnswers"] for item in listing["items"]]
        assert {
            "gate": ["Ja"],
            "multi": ["Alpha", "Beta"],
            "nps": ["3"],
            "matrix": ["Organisation: Gut", "Verpflegung: Gut"],
        } in chosen
        assert all(
            set(answer) <= {"gate", "multi", "nps", "matrix"} for answer in chosen
        )
        assert all(
            TEXTS[0] not in json.dumps(item["choiceAnswers"])
            for item in listing["items"]
        )
        plain = await call("GET", base + "/responses", auth=reader)
        assert all(item["choiceAnswers"] is None for item in plain["items"])
        await call(
            "GET",
            base + "/responses",
            auth=analyst,
            params={"fields": "choice"},
            expected=404,
        )
        Path("/proof/summary-access.json").write_text(
            json.dumps(
                {
                    "surveyId": str(sid),
                    "versionId": version["id"],
                    "snapshotId": selection["id"],
                    "readerToken": reader_token,
                    "analystToken": analyst_token,
                    "quote": TEXTS[2],
                }
            )
        )
    await conn.close()


asyncio.run(main())
