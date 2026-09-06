"""Real API/database condition parity and stopped/paused adapter recovery."""

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import httpx

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.surveys.validation import validate_answers as baseline_answers


async def main() -> None:
    mode = sys.argv[1]
    proof = Path("/proof/validator-failure.json")
    token = Path("/proof/session.env").read_text().strip().split("=", 1)[1]
    cases = json.loads(
        Path("tests/fixtures/surveys/condition-candidate-cases.json").read_text()
    )
    if mode == "cases":
        baseline = json.loads(
            Path("tests/fixtures/surveys/validation-cases.json").read_text()
        )
        for case in baseline:
            case["definition"] = case.get("definition") or json.loads(
                Path(f"tests/fixtures/surveys/{case['fixture']}.json").read_text()
            )
            try:
                case["expectedAnswers"] = baseline_answers(
                    case["definition"], case["answers"], complete=False
                )
                case["expectedPartial"] = True
            except DomainInvariantError:
                case["expectedPartial"] = False
            try:
                baseline_answers(case["definition"], case["answers"], complete=True)
                case["expectedComplete"] = True
            except DomainInvariantError:
                case["expectedComplete"] = False
        cases += baseline
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    async with httpx.AsyncClient(base_url="http://api:8000", timeout=15) as client:

        async def call(method, path, body=None, cookies=None, expected=200):
            response = await client.request(method, path, json=body, cookies=cookies)
            assert response.status_code == expected, (
                path,
                response.status_code,
                response.text,
            )
            return response.json()

        async def create(case):
            sid = str(uuid4())
            admin = f"/api/v1/surveys/{sid}"
            auth = {"__Host-leonaid_session": token}
            await call(
                "POST",
                admin,
                {
                    "operationId": str(uuid4()),
                    "title": "Synthetic core parity",
                    "definition": case["definition"],
                },
                auth,
            )
            await call(
                "POST",
                admin + "/publish",
                {"operationId": str(uuid4()), "expectedRevision": 1},
                auth,
            )
            secret = secrets.token_urlsafe(48)
            path = f"/api/v1/public/surveys/{sid}/participations"
            participant = await call(
                "POST", path, {"operationId": str(uuid4()), "resumeSecret": secret}
            )
            pid = participant["id"]
            return {
                "path": path + "/" + pid,
                "pid": pid,
                "cookies": {f"__Host-survey_{pid}": secret},
                "body": {
                    "operationId": str(uuid4()),
                    "expectedRevision": 1,
                    "answers": case["answers"],
                    "currentPage": case["definition"]["pages"][0]["name"],
                },
            }

        async def state(pid):
            return dict(
                await conn.fetchrow(
                    "SELECT answers::text,revision,status,completed_at,last_answer_changed_at FROM survey_participation WHERE id=$1::uuid",
                    pid,
                )
            )

        if mode == "cases":
            for case in cases:
                item = await create(case)
                initial = await state(item["pid"])
                saved = await call(
                    "PUT",
                    item["path"],
                    item["body"],
                    item["cookies"],
                    200 if case["expectedPartial"] else 422,
                )
                if not case["expectedPartial"]:
                    assert await state(item["pid"]) == initial, case["name"]
                    continue
                assert saved["answers"] == case["expectedAnswers"], case["name"]
                before = await state(item["pid"])
                assert json.loads(before["answers"]) == case["expectedAnswers"]
                await call(
                    "POST",
                    item["path"] + "/complete",
                    {
                        "operationId": str(uuid4()),
                        "expectedRevision": saved["revision"],
                    },
                    item["cookies"],
                    200 if case["expectedComplete"] else 422,
                )
                after = await state(item["pid"])
                if case["expectedComplete"]:
                    assert after["status"] == "completed" and after["completed_at"]
                else:
                    assert after == before, case["name"]
            print(
                f"PASS: {len(cases)} actual API/PostgreSQL condition, cleanup and required-completion cases"
            )
        elif mode == "seed":
            proof.write_text(json.dumps(await create(cases[0])))
            print("Prepared synthetic adapter-failure participation")
        elif mode in {"unavailable", "recover"}:
            item = json.loads(proof.read_text())
            before = await state(item["pid"])
            if mode == "unavailable":
                for method, path, body in [
                    ("PUT", item["path"], item["body"]),
                    (
                        "POST",
                        item["path"] + "/complete",
                        {
                            "operationId": "unavailable-completion",
                            "expectedRevision": 1,
                        },
                    ),
                ]:
                    await call(method, path, body, item["cookies"], 503)
                    assert await state(item["pid"]) == before
                print(
                    "PASS: unavailable adapter rejects save/completion with HTTP 503 and unchanged PostgreSQL state"
                )
            else:
                saved = await call("PUT", item["path"], item["body"], item["cookies"])
                assert saved["answers"] == cases[0]["expectedAnswers"]
                assert saved["revision"] == 2
                # Retry the exact previously failed save and then its successful replay.
                assert saved == await call(
                    "PUT", item["path"], item["body"], item["cookies"]
                )
                await call(
                    "POST",
                    item["path"] + "/complete",
                    {"operationId": "unavailable-completion", "expectedRevision": 2},
                    item["cookies"],
                )
                assert (await state(item["pid"]))["status"] == "completed"
                print(
                    "PASS: recovered adapter accepts exact save retry once and completes correct snapshot"
                )
        else:
            raise AssertionError(mode)
    await conn.close()


asyncio.run(main())
