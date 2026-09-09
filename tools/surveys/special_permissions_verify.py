"""Verify single-grant invitation writes and requester-scoped completed deletion APIs."""

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx


async def main():
    proof = Path("/proof")
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    invitation_fixture = json.loads(
        (proof / "invitation-roles-private.json").read_text()
    )
    journeys = []
    for journey in invitation_fixture["journeys"]:
        sid = UUID(journey["id"])
        survey = await conn.fetchrow(
            "SELECT owner_user_id,action_id FROM survey WHERE id=$1", sid
        )
        assert str(survey["owner_user_id"]) != invitation_fixture["actorId"]
        assert (str(survey["action_id"]) if survey["action_id"] else None) == journey[
            "actionId"
        ]
        grants = await conn.fetch(
            "SELECT capability FROM survey_grant WHERE survey_id=$1 AND user_id=$2",
            sid,
            UUID(invitation_fixture["actorId"]),
        )
        assert [row["capability"] for row in grants] == ["manage_invitations"]
        rows = await conn.fetch(
            "SELECT i.*,p.status AS response_status,p.answers FROM survey_invitation i JOIN survey_participation p ON p.id=i.participation_id AND p.survey_id=i.survey_id WHERE i.survey_id=$1",
            sid,
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["sent_at"] and row["redeemed_at"] and row["revoked_at"]
        assert row["mail_payload"] is None and row["response_status"] == "completed"
        assert json.loads(row["answers"]) == {
            "answer": "Invitation-only journey response"
        }
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM survey_invitation WHERE survey_id=$1", sid
            )
            == 1
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM survey_participation WHERE survey_id=$1", sid
            )
            == 1
        )
        # Verify actual operation ownership, not just UI output or fixture grants.
        for operation in ["invitation-create", "invitation-revoke"]:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM survey_operation WHERE survey_id=$1 AND scope=$2",
                    sid,
                    f"author:{invitation_fixture['actorId']}:{operation}",
                )
                == 1
            )
        result = json.loads(
            (
                proof
                / f"invitation-role-{journey['kind']}-{str(journey['mobile']).lower()}.json"
            ).read_text()
        )
        journeys.append(result)

    personas = json.loads((proof / "permission-browser-private.json").read_text())[
        "actors"
    ]
    lifecycle = json.loads((proof / "role-journeys-private.json").read_text())
    deletion_counts = {
        "positiveStatusReads": 0,
        "deniedStatusReads": 0,
        "exactRequesterReplays": 0,
        "deniedForeignReplays": 0,
    }
    async with httpx.AsyncClient(base_url="http://api:8000") as client:

        async def call(method, path, actor, body=None, expected=200):
            response = await client.request(
                method,
                path,
                json=body,
                headers={
                    "Cookie": "__Host-leonaid_session=" + personas[actor]["token"]
                },
            )
            assert response.status_code == expected, (
                actor,
                method,
                response.status_code,
                expected,
            )
            return response.json()

        for journey in lifecycle["journeys"]:
            if not journey["mobile"]:
                continue
            sid = UUID(journey["id"])
            path = f"/api/v1/surveys/{sid}"
            original = await conn.fetchval(
                "SELECT row_to_json(d)::text FROM survey_deletion d WHERE survey_id=$1",
                sid,
            )
            mutation = json.loads(
                (proof / f"role-deletion-{journey['kind']}-private.json").read_text()
            )
            for name in personas:
                allowed = name in {"admin", "delete"}
                status = await call(
                    "GET", path + "/deletion", name, expected=200 if allowed else 404
                )
                if allowed:
                    assert status["status"] == "completed"
                    assert status.get("retryEventId") is None
                deletion_counts[
                    "positiveStatusReads" if allowed else "deniedStatusReads"
                ] += 1
                replay = await call(
                    "POST",
                    path + "/delete-permanently",
                    name,
                    mutation,
                    expected=200 if name == "delete" else 404,
                )
                if name == "delete":
                    assert replay["status"] == "completed"
                    deletion_counts["exactRequesterReplays"] += 1
                else:
                    deletion_counts["deniedForeignReplays"] += 1
            conflict = await call(
                "POST",
                path + "/delete-permanently",
                "delete",
                {**mutation, "operationId": "different-request"},
                expected=409,
            )
            assert conflict["error"]["code"] == "idempotency_conflict"
            assert (
                await conn.fetchval(
                    "SELECT row_to_json(d)::text FROM survey_deletion d WHERE survey_id=$1",
                    sid,
                )
                == original
            )
            assert not await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM survey WHERE id=$1)", sid
            )
    # Every parallel case owns its output; aggregate only after all browser
    # workers have joined. Require the complete role x viewport matrix.
    invitation_controls = []
    assert len(personas) == 14
    for mobile in (False, True):
        cases = []
        for name in personas:
            result = json.loads(
                (
                    proof / f"invitation-controls-{name}-{str(mobile).lower()}.json"
                ).read_text()
            )
            assert result == {
                "name": name,
                "mobile": mobile,
                "pairs": 2,
                "recipientDataScoped": True,
            }
            cases.append(result)
        invitation_controls.append(
            {
                "mobile": mobile,
                "pairs": sum(case["pairs"] for case in cases),
                "recipientDataScoped": True,
            }
        )
    await conn.close()
    (proof / "special-permissions-proof.json").write_text(
        json.dumps(
            {
                "syntheticOnly": True,
                "invitationControlMatrix": invitation_controls,
                "invitationJourneys": journeys,
                "invitationSqlAndOperationOwnershipVerified": True,
                "deletion": deletion_counts,
                "deletionLedgerUnchanged": True,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        "PASS: four single-grant invitation journeys and completed deletion scope",
        deletion_counts,
    )


asyncio.run(main())
