"""Exercise changed authority and foreign child IDs through existing HTTP sessions."""

import json
from pathlib import Path


async def verify_boundaries(
    conn, call, actors, resources, actions, own_jobs, fingerprint
):
    standalone, linked, foreign = resources[:3]
    before = await fingerprint()
    counts = {
        "revokedGrants": 0,
        "expiredMemberships": 0,
        "suspendedAccounts": 0,
        "foreignChildRequests": 0,
    }

    # Each probe targets the actor's own capability, not an unrelated denied route.
    def operation(name, resource):
        path = resource["path"]
        reads = {
            "design": "/draft",
            "publish": "/publication",
            "view_aggregates": "/analysis/" + resource["snapshot"],
            "read_responses": "/response-selections/" + resource["snapshot"],
            "manage_invitations": "/invitations",
        }
        if name in reads:
            return "GET", path + reads[name], None
        if name in {"export_raw", "export_reports"}:
            product = "responses_csv" if name == "export_raw" else "analysis_xlsx"
            return (
                "GET",
                path + "/exports/" + own_jobs[(name, resource["kind"], product)],
                None,
            )
        return (
            "POST",
            path + "/transition",
            {
                "operationId": "changed-authority-denied",
                "expectedRevision": 1,
                "action": "trash" if name == "delete" else "archive",
            },
        )

    async def hidden(name, resource):
        await call("GET", resource["path"], actor=name, expected=404)
        listing = await call(
            "GET", "/api/v1/surveys?search=Permission%20matrix", actor=name
        )
        assert str(resource["id"]) not in {item["id"] for item in listing["items"]}
        method, path, body = operation(name, resource)
        await call(method, path, body, actor=name, expected=404)
        for product in ["responses_csv", "analysis_xlsx"]:
            jid = own_jobs.get((name, resource["kind"], product))
            if jid:
                for suffix in ["", "/download"]:
                    await call(
                        "GET",
                        resource["path"] + "/exports/" + jid + suffix,
                        actor=name,
                        expected=404,
                    )
        return listing

    caps = [
        name
        for name in actors
        if name not in {"admin", "owner", "manager", "member", "outsider"}
    ]
    for name in caps:
        uid = actors[name]["id"]
        await conn.execute(
            "DELETE FROM survey_grant WHERE survey_id=$1 AND user_id=$2 AND capability=$3",
            standalone["id"],
            uid,
            name,
        )
        try:
            listing = await hidden(name, standalone)
            assert listing["total"] == 1
            assert {item["id"] for item in listing["items"]} == {str(linked["id"])}
        finally:
            await conn.execute(
                "INSERT INTO survey_grant(survey_id,user_id,capability) VALUES($1,$2,$3)",
                standalone["id"],
                uid,
                name,
            )
        restored = await call("GET", standalone["path"], actor=name)
        assert restored["capabilities"] == [name]
        counts["revokedGrants"] += 1

    for name in [*caps, "owner", "manager"]:
        uid = actors[name]["id"]
        original = await conn.fetchval(
            "SELECT active_until FROM action_membership WHERE action_id=$1 AND user_id=$2",
            actions[0],
            uid,
        )
        await conn.execute(
            "UPDATE action_membership SET active_until=clock_timestamp() - interval '1 millisecond' WHERE action_id=$1 AND user_id=$2",
            actions[0],
            uid,
        )
        try:
            listing = await hidden(name, linked)
            assert listing["total"] == (0 if name == "manager" else 1)
            assert not listing["actions"]
        finally:
            await conn.execute(
                "UPDATE action_membership SET active_until=$3 WHERE action_id=$1 AND user_id=$2",
                actions[0],
                uid,
                original,
            )
        await call("GET", linked["path"], actor=name)
        counts["expiredMemberships"] += 1

    for name in actors:
        if name == "admin":
            continue
        uid = actors[name]["id"]
        await conn.execute(
            "UPDATE user_account SET status='suspended' WHERE id=$1", uid
        )
        try:
            for path in [
                "/api/v1/surveys",
                standalone["path"],
                linked["path"] + "/draft",
            ]:
                await call("GET", path, actor=name, expected=401)
            for resource in [standalone, linked]:
                for product in ["responses_csv", "analysis_xlsx"]:
                    jid = own_jobs.get((name, resource["kind"], product))
                    if jid:
                        for suffix in ["", "/download"]:
                            await call(
                                "GET",
                                resource["path"] + "/exports/" + jid + suffix,
                                actor=name,
                                expected=401,
                            )
        finally:
            await conn.execute(
                "UPDATE user_account SET status='active' WHERE id=$1", uid
            )
        await call("GET", "/api/v1/surveys", actor=name)
        counts["suspendedAccounts"] += 1

    # Admin can access both parents: rejection must arise from parent-child binding.
    path, snap = standalone["path"], foreign["snapshot"]
    foreign_reads = [
        "/analysis/" + snap,
        "/response-selections/" + snap,
        "/response-selections/" + snap + "/responses",
        "/response-selections/" + snap + "/free-text/answer",
        "/response-selections/" + snap + "/responses/" + foreign["participation"],
        "/response-selections/"
        + standalone["snapshot"]
        + "/responses/"
        + foreign["participation"],
    ]
    for product in ["responses_csv", "analysis_xlsx"]:
        foreign_reads.extend(
            "/exports/" + foreign["jobs"][product]["id"] + suffix
            for suffix in ["", "/download"]
        )
    for suffix in foreign_reads:
        await call("GET", path + suffix, expected=404)
        counts["foreignChildRequests"] += 1
    for suffix in ["/analysis", "/response-selections", "/export-selections"]:
        await call(
            "POST",
            path + suffix,
            {
                "operationId": "foreign-version-denied",
                "filter": {"versionId": foreign["version"]},
            },
            expected=404,
        )
        counts["foreignChildRequests"] += 1
    for product in ["responses_csv", "analysis_xlsx"]:
        await call(
            "POST",
            path + "/exports",
            {
                "operationId": "foreign-snapshot-denied",
                "snapshotId": snap,
                "product": product,
            },
            expected=404,
        )
        counts["foreignChildRequests"] += 1
    assert await fingerprint() == before, (
        "Boundary probes changed persisted survey state"
    )
    result = {
        "syntheticOnly": True,
        **counts,
        "sameSessionRechecks": True,
        "fixtureAuthorityRestored": True,
        "surveySqlFingerprintUnchanged": True,
    }
    Path("/proof/permission-boundaries-proof.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print("PASS: changed authority and foreign child ID boundaries", counts)
