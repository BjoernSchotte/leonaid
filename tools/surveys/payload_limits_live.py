"""Actual HTTP byte/JSON boundaries with authoritative persistence assertions."""

import asyncio
import json
import os
import secrets
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.domain.surveys.validation import json_size


async def main():
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    token = Path("/proof/session.env").read_text().strip().split("=", 1)[1]
    marker = "SURVEY_PRIVATE_" + secrets.token_hex(16)
    secret = secrets.token_urlsafe(48)
    Path("/proof/payload-markers.json").write_text(json.dumps([marker, secret, token]))
    questions = [
        {"type": "comment", "name": f"q{i}", "description": ""} for i in range(27)
    ]
    definition = {"pages": [{"name": "one", "elements": questions}]}
    for question in questions:
        question["description"] = "D" * min(10000, 262144 - json_size(definition))
    assert json_size(definition) == 262144
    sid = uuid4()
    admin = f"/api/v1/surveys/{sid}"
    headers = {
        "Cookie": f"__Host-leonaid_session={token}",
        "Content-Type": "application/json",
    }
    body = {
        "operationId": "create",
        "title": "Synthetic payload boundary",
        "definition": definition,
    }
    encoded = json.dumps(body).encode()
    exact = encoded + b" " * (1048576 - len(encoded))
    async with httpx.AsyncClient(base_url="http://api:8000", timeout=30) as client:
        response = await client.post(admin, content=exact, headers=headers)
        assert response.status_code == 200, response.status_code
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM survey_draft WHERE survey_id=$1", sid
            )
            == 1
        )

        async def rejected_create(content, expected):
            rejected_sid = uuid4()
            response = await client.post(
                f"/api/v1/surveys/{rejected_sid}", content=content, headers=headers
            )
            assert response.status_code == expected, response.status_code
            assert marker not in response.text and token not in response.text
            if expected == 413:
                assert response.json()["error"]["code"] == "limit_exceeded"
                assert response.headers["Cache-Control"] == "no-store"
            assert not await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM survey WHERE id=$1)", rejected_sid
            )
            assert not await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM survey_operation WHERE survey_id=$1)",
                rejected_sid,
            )

        await rejected_create(exact + b" ", 413)

        async def chunks():
            for offset in range(0, len(exact), 65536):
                yield exact[offset : offset + 65536]
            yield b" "

        await rejected_create(chunks(), 413)
        questions[-1]["description"] += "D"
        assert json_size(definition) == 262145
        await rejected_create(json.dumps(body).encode(), 422)
        response = await client.put(
            admin + "/draft",
            headers=headers,
            json={
                "operationId": "oversize-draft",
                "expectedRevision": 1,
                "definition": definition,
            },
        )
        assert response.status_code == 422
        assert (
            await conn.fetchval(
                "SELECT revision FROM survey_draft WHERE survey_id=$1", sid
            )
            == 1
        )
        response = await client.post(
            admin + "/publish",
            headers=headers,
            json={"operationId": "publish", "expectedRevision": 1},
        )
        assert response.status_code == 200, response.status_code
        response = await client.post(
            f"/api/v1/public/surveys/{sid}/participations",
            json={"operationId": "start", "resumeSecret": secret},
        )
        assert response.status_code == 200
        pid = response.json()["id"]
        path = f"/api/v1/public/surveys/{sid}/participations/{pid}"
        resume = {"Cookie": f"__Host-survey_{pid}={secret}"}
        answers = {f"q{i}": marker if i == 0 else "" for i in range(27)}
        for key in answers:
            answers[key] += "A" * min(
                10000 - len(answers[key]), 262144 - json_size(answers)
            )
        assert json_size(answers) == 262144
        save = {
            "operationId": "save",
            "expectedRevision": 1,
            "answers": answers,
            "currentPage": "one",
        }
        response = await client.put(path, headers=resume, json=save)
        assert response.status_code == 200, response.status_code
        before = await conn.fetchrow(
            "SELECT answers,revision FROM survey_participation WHERE id=$1", UUID(pid)
        )
        assert before["revision"] == 2 and json.loads(before["answers"]) == answers
        answers["q26"] += "A"
        assert json_size(answers) == 262145
        for content, expected in (
            (
                json.dumps(
                    {**save, "operationId": "rejected", "expectedRevision": 2}
                ).encode(),
                422,
            ),
            (b" " * 1048577, 413),
        ):
            response = await client.put(
                path,
                headers={**resume, "Content-Type": "application/json"},
                content=content,
            )
            assert response.status_code == expected, response.status_code
            assert marker not in response.text and secret not in response.text
            assert (
                await conn.fetchrow(
                    "SELECT answers,revision FROM survey_participation WHERE id=$1",
                    UUID(pid),
                )
                == before
            )
        # Exercise validation errors containing a sensitive value as well as the
        # successful save. Captured logs are scanned separately without printing.
        response = await client.put(
            path,
            headers=resume,
            json={
                **save,
                "operationId": "invalid",
                "expectedRevision": 2,
                "answers": {"unknown": marker},
            },
        )
        assert response.status_code == 422
    await conn.close()
    Path("/proof/payload-limits-proof.json").write_text(
        json.dumps(
            {
                "syntheticOnly": True,
                "wireByteLimit": 1048576,
                "jsonByteLimit": 262144,
                "exactWireAndDefinitionBoundaryAccepted": True,
                "fixedAndChunkedOversizeRejected": True,
                "oversizeCreatesLeftNoRows": True,
                "oversizeDraftPreservedRevision": 1,
                "exactAnswerBoundaryAccepted": True,
                "rejectedAnswersPreservedRevision": 2,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        "PASS: exact wire/definition/answer boundaries and one-byte excess; fixed/chunked bodies; rejected writes preserve SQL state"
    )


asyncio.run(main())
