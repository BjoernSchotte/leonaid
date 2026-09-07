"""Inventory every survey write and prove strict transport rejection without writes."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.entrypoints.fastapi.surveys import router
from leonaid.entrypoints.fastapi.schemas import ApiErrorResponse


async def main():
    sid, pid, iid = (str(uuid4()) for _ in range(3))
    mutation = {"operationId": "contract-probe", "expectedRevision": 1}
    definition = {
        "pages": [{"name": "one", "elements": [{"type": "text", "name": "answer"}]}]
    }
    selection = {"operationId": "contract-probe", "filter": {"versionId": str(uuid4())}}
    # Deliberate complete inventory: a new write fails until its DTO and expected
    # denial are reviewed. Samples are syntax-valid; IDs refer to absent resources.
    bodies = {
        "createSurveyExport": {
            "operationId": "contract-probe",
            "snapshotId": str(uuid4()),
            "product": "responses_csv",
        },
        "createSurveyExportSelection": selection,
        "createSurveyAnalysis": selection,
        "createSurveyResponseSelection": selection,
        "updateSurveySettings": {**mutation, "inactivityTimeoutSeconds": 300},
        "updateSurveyTimeout": {**mutation, "inactivityTimeoutSeconds": None},
        "scheduleSurveyEnd": {**mutation, "endsAt": None},
        "createSurvey": {
            "operationId": "contract-probe",
            "title": "Contract fixture",
            "definition": definition,
        },
        "deleteSurveyPermanently": mutation,
        "transitionSurvey": {**mutation, "action": "end"},
        "duplicateSurvey": {
            **mutation,
            "targetSurveyId": str(uuid4()),
            "title": "Copy",
        },
        "validateSurveyDraft": {"expectedRevision": 1},
        "saveSurveyDraft": {**mutation, "definition": definition},
        "publishSurvey": mutation,
        "updateSurveyAccess": {**mutation, "accessMode": "anonymous"},
        "createSurveyInvitation": {
            **mutation,
            "recipientEmail": "recipient@example.com",
        },
        "revokeSurveyInvitation": mutation,
        "redeemSurveyInvitation": {"token": "x" * 48},
        "startSurveyParticipation": {
            "operationId": "contract-probe",
            "resumeSecret": "x" * 48,
        },
        "saveSurveyResponse": {**mutation, "answers": {}},
        "completeSurveyResponse": mutation,
    }
    routes = [
        r for r in router.routes if r.methods & {"POST", "PUT", "PATCH", "DELETE"}
    ]
    assert {r.operation_id for r in routes} == set(bodies), (
        "Survey write inventory drift"
    )
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    env = dict(
        line.split("=", 1)
        for line in Path("/proof/session.env").read_text().splitlines()
    )
    auth = {"Cookie": "__Host-leonaid_session=" + env["SURVEY_ADMIN_SESSION"]}
    tables = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'survey_%' OR tablename='survey' OR tablename='outbox_event') ORDER BY tablename"
    )

    async def state():
        result = {}
        for row in tables:
            table = row["tablename"]
            # The identifier originates in the database catalog, quoted defensively.
            quoted = '"' + table.replace('"', '""') + '"'
            values = await conn.fetch(
                f"SELECT to_jsonb(t)::text AS value FROM {quoted} t"
            )
            payload = json.dumps(sorted(r["value"] for r in values)).encode()
            result[table] = hashlib.sha256(payload).hexdigest()
        return result

    def error_contract(response, code, request_id):
        payload = response.json()
        ApiErrorResponse.model_validate(payload)
        assert set(payload) == {"error"}
        assert set(payload["error"]) == {"code", "message", "requestId"}
        assert payload["error"]["code"] == code
        assert payload["error"]["requestId"] == request_id
        assert response.headers["x-request-id"] == request_id
        assert (
            isinstance(payload["error"]["message"], str) and payload["error"]["message"]
        )
        assert "contract-input-canary" not in response.text
        assert "unexpectedContractField" not in response.text

    evidence = []
    try:
        async with httpx.AsyncClient(base_url="http://api:8000") as client:
            seeded_id = str(uuid4())
            seeded_path = f"/api/v1/surveys/{seeded_id}"
            created = await client.post(
                seeded_path, headers=auth, json=bodies["createSurvey"]
            )
            assert created.status_code == 200
            published = await client.post(
                seeded_path + "/publish", headers=auth, json=mutation
            )
            assert published.status_code == 200
            respondent_path = f"/api/v1/public/surveys/{seeded_id}/participations"
            started = await client.post(
                respondent_path, json=bodies["startSurveyParticipation"]
            )
            assert started.status_code == 200
            seeded_pid = started.json()["id"]
            saved = await client.put(
                respondent_path + "/" + seeded_pid,
                headers={"Cookie": f"__Host-survey_{seeded_pid}=" + "x" * 48},
                json={
                    **mutation,
                    "answers": {"answer": "Preserve this synthetic response"},
                    "currentPage": "one",
                },
            )
            assert saved.status_code == 200
            persisted = await conn.fetchval(
                "SELECT answers FROM survey_participation WHERE id=$1", UUID(seeded_pid)
            )
            assert json.loads(persisted) == {
                "answer": "Preserve this synthetic response"
            }
            before = await state()
            for route in routes:
                body = bodies[route.operation_id]
                # Validate the supposedly valid sample using the actual DTO too.
                model = route.body_field.type_
                model.model_validate(body)
                path = route.path.format(
                    survey_id=sid, participation_id=pid, invitation_id=iid
                )
                method = next(iter(route.methods))
                invalid_request_id = "surveys-contract-invalid-" + route.operation_id
                invalid = await client.request(
                    method,
                    path,
                    headers={**auth, "X-Request-ID": invalid_request_id},
                    json={**body, "unexpectedContractField": "contract-input-canary"},
                )
                assert invalid.status_code == 422, (
                    route.operation_id,
                    "extra",
                    invalid.status_code,
                )
                error_contract(invalid, "request_invalid", invalid_request_id)
                assert await state() == before, (
                    route.operation_id,
                    "invalid payload mutated survey state",
                )
                denied_request_id = "surveys-contract-denied-" + route.operation_id
                denied = await client.request(
                    method, path, json=body, headers={"X-Request-ID": denied_request_id}
                )
                expected = 404 if "/public/" in path else 401
                assert denied.status_code == expected, (
                    route.operation_id,
                    "denial",
                    denied.status_code,
                )
                denial_code = (
                    "not_found" if expected == 404 else "authentication_required"
                )
                error_contract(denied, denial_code, denied_request_id)
                assert await state() == before, (
                    route.operation_id,
                    "denial mutated survey state",
                )
                evidence.append(
                    {
                        "operationId": route.operation_id,
                        "method": method,
                        "path": route.path,
                        "requestModel": model.__name__,
                        "responseModel": route.response_model.__name__,
                        "unknownFieldStatus": 422,
                        "unknownFieldCode": "request_invalid",
                        "denialCode": denial_code,
                        "errorEnvelopeAndRequestIdVerified": True,
                        "invalidInputNotEchoed": True,
                        "unauthenticatedOrMissingResourceStatus": expected,
                        "surveyAndOutboxStateUnchanged": True,
                    }
                )
        Path("/proof/write-contracts.json").write_text(
            json.dumps(
                {"writes": evidence, "tablesChecked": [r["tablename"] for r in tables]},
                indent=2,
            )
            + "\n"
        )
        print(
            f"PASS: {len(evidence)} survey write contracts; strict DTO rejection, unauthenticated/missing-resource denial and unchanged persisted state"
        )
    finally:
        await conn.close()


asyncio.run(main())
