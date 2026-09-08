"""Populated invitation permission probes and isolated single-grant browser fixtures."""

import json
from pathlib import Path
from uuid import uuid4


async def prepare_invitation_roles(conn, call, actors, resources, actions, fingerprint):
    invitations = []
    for original in resources[:2]:
        sid = uuid4()
        resource = {
            "id": sid,
            "kind": original["kind"],
            "path": f"/api/v1/surveys/{sid}",
        }
        path = resource["path"]
        await call(
            "POST",
            path,
            {
                "operationId": "create",
                "title": "Invitation scope fixture",
                "actionId": str(actions[0])
                if original["kind"] == "member-action"
                else None,
                "definition": {
                    "pages": [
                        {
                            "name": "one",
                            "elements": [{"type": "text", "name": "answer"}],
                        }
                    ]
                },
            },
        )
        await conn.execute(
            "UPDATE survey SET owner_user_id=$2 WHERE id=$1", sid, actors["owner"]["id"]
        )
        for name in actors:
            if name in {"admin", "owner", "manager", "member", "outsider"}:
                continue
            await conn.execute(
                "INSERT INTO survey_grant(survey_id,user_id,capability) VALUES($1,$2,$3)",
                sid,
                actors[name]["id"],
                name,
            )
        summary = await call("GET", path)
        await call(
            "PUT",
            path + "/access",
            {
                "operationId": "invitation-matrix-access",
                "expectedRevision": summary["revision"],
                "accessMode": "invitation",
            },
        )
        await call(
            "POST", path + "/publish", {"operationId": "publish", "expectedRevision": 1}
        )
        summary = await call("GET", path)
        invitation = await call(
            "POST",
            path + "/invitations",
            {
                "operationId": "invitation-matrix-create",
                "expectedRevision": summary["revision"],
                "recipientEmail": "matrix-recipient@example.com",
                "expiresInDays": 30,
            },
        )
        invitations.append((resource, invitation, summary["revision"]))
    before = await fingerprint()
    positive, denied = 0, 0
    for index, (resource, invitation, revision) in enumerate(invitations):
        for name in actors:
            allowed = name in {"admin", "owner", "manage_invitations"} or (
                name == "manager" and resource["kind"] == "member-action"
            )
            for suffix in ["", "?offset=1"]:
                result = await call(
                    "GET",
                    resource["path"] + "/invitations" + suffix,
                    actor=name,
                    expected=200 if allowed else 404,
                )
                if allowed:
                    assert result["total"] == 1
                    assert [item["id"] for item in result["items"]] == (
                        [] if suffix else [invitation["id"]]
                    )
                    positive += 1
                else:
                    denied += 1
            if not allowed:
                await call(
                    "POST",
                    resource["path"] + "/invitations/" + invitation["id"] + "/revoke",
                    {"operationId": "denied-revoke", "expectedRevision": revision},
                    actor=name,
                    expected=404,
                )
                denied += 1
        await call(
            "POST",
            resource["path"]
            + "/invitations/"
            + invitations[1 - index][1]["id"]
            + "/revoke",
            {"operationId": "foreign-invitation", "expectedRevision": revision},
            expected=404,
        )
        denied += 1
    assert await fingerprint() == before
    # Prevent matrix fixture mail from mixing with the browser's own delivery proof.
    for resource, invitation, revision in invitations:
        await call(
            "POST",
            resource["path"] + "/invitations/" + invitation["id"] + "/revoke",
            {"operationId": "matrix-cleanup", "expectedRevision": revision},
        )

    journeys = []
    for kind, aid in [("standalone", None), ("action", actions[0])]:
        for mobile in [False, True]:
            sid = uuid4()
            path = f"/api/v1/surveys/{sid}"
            await call(
                "POST",
                path,
                {
                    "operationId": "create",
                    "title": "Single-role invitation journey",
                    "actionId": str(aid) if aid else None,
                    "definition": {
                        "pages": [
                            {
                                "name": "one",
                                "elements": [{"type": "text", "name": "answer"}],
                            }
                        ]
                    },
                },
            )
            await conn.execute(
                "INSERT INTO survey_grant(survey_id,user_id,capability) VALUES($1,$2,'manage_invitations')",
                sid,
                actors["manage_invitations"]["id"],
            )
            await call(
                "PUT",
                path + "/access",
                {
                    "operationId": "access",
                    "expectedRevision": 1,
                    "accessMode": "invitation",
                },
            )
            await call(
                "POST",
                path + "/publish",
                {"operationId": "publish", "expectedRevision": 1},
            )
            journeys.append(
                {
                    "id": str(sid),
                    "kind": kind,
                    "mobile": mobile,
                    "actionId": str(aid) if aid else None,
                }
            )
    Path("/proof/invitation-roles-private.json").write_text(
        json.dumps(
            {
                "token": actors["manage_invitations"]["token"],
                "actorId": str(actors["manage_invitations"]["id"]),
                "journeys": journeys,
                "scopes": [
                    {"id": str(resource["id"]), "kind": resource["kind"]}
                    for resource, _, _ in invitations
                ],
            }
        )
    )
    Path("/proof/invitation-scope-proof.json").write_text(
        json.dumps(
            {
                "syntheticOnly": True,
                "positivePopulatedReads": positive,
                "deniedRequests": denied,
                "sqlFingerprintUnchanged": True,
            },
            indent=2,
        )
        + "\n"
    )
    print("PASS: populated invitation lists/revocation scope", positive, denied)
