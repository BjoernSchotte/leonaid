"""Independent persona/resource expectations against actual survey HTTP and SQL."""

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

# Deliberately independent of the production permission function.
CAPS = [
    "design",
    "publish",
    "archive",
    "view_aggregates",
    "read_responses",
    "export_raw",
    "export_reports",
    "manage_invitations",
    "delete",
]
DEFINITION = {
    "pages": [{"name": "one", "elements": [{"type": "text", "name": "answer"}]}]
}


async def main():
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    admin_token = Path("/proof/session.env").read_text().strip().split("=", 1)[1]
    actors = {"admin": {"token": admin_token}}
    now = datetime.now(timezone.utc)
    for name in [*CAPS, "owner", "manager", "member", "outsider"]:
        uid, token = uuid4(), secrets.token_urlsafe(48)
        await conn.execute(
            "INSERT INTO user_account(id,email,display_name,status,email_verified_at) VALUES($1,$2,$3,'active',$4)",
            uid,
            f"{uid}@example.invalid",
            "Synthetic matrix " + name,
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
        actors[name] = {"id": uid, "token": token}
    actions = [uuid4(), uuid4()]
    for aid in actions:
        await conn.execute(
            "INSERT INTO charity_action(id,carrier_name,name,purpose,status,starts_on,ends_on,archive_slug,goal_value,actual_value,goal_unit,currency) VALUES($1,'Synthetic charity','Permission matrix','Synthetic proof','draft','2026-09-01','2026-11-15',$2,0,0,'cent','EUR')",
            aid,
            f"matrix-{aid}",
        )
    for name in [*CAPS, "owner", "manager", "member"]:
        await conn.execute(
            "INSERT INTO action_membership(id,action_id,user_id,role) VALUES($1,$2,$3,$4)",
            uuid4(),
            actions[0],
            actors[name]["id"],
            "charity_admin" if name == "manager" else "acquirer",
        )
    counts = {
        "positiveReads": 0,
        "deniedReads": 0,
        "deniedWrites": 0,
        "personaResourcePairs": 0,
    }
    async with httpx.AsyncClient(base_url="http://api:8000", timeout=60) as client:

        async def call(method, path, body=None, actor="admin", expected=200):
            response = await client.request(
                method,
                path,
                json=body,
                headers={"Cookie": "__Host-leonaid_session=" + actors[actor]["token"]},
            )
            assert response.status_code == expected, (
                actor,
                method,
                path.split("/")[-1],
                response.status_code,
                expected,
            )
            return response.json()

        resources = []
        for kind, aid in [
            ("standalone", None),
            ("member-action", actions[0]),
            ("foreign-action", actions[1]),
            ("foreign-standalone", None),
        ]:
            sid = uuid4()
            path = f"/api/v1/surveys/{sid}"
            await call(
                "POST",
                path,
                {
                    "operationId": "create",
                    "title": "Permission matrix " + kind,
                    "definition": DEFINITION,
                    "actionId": str(aid) if aid else None,
                },
            )
            if kind != "foreign-standalone":
                # Explicit ownership fixture includes the negative owner-without-membership case.
                await conn.execute(
                    "UPDATE survey SET owner_user_id=$2 WHERE id=$1",
                    sid,
                    actors["owner"]["id"],
                )
                for cap in CAPS:
                    await conn.execute(
                        "INSERT INTO survey_grant(survey_id,user_id,capability) VALUES($1,$2,$3)",
                        sid,
                        actors[cap]["id"],
                        cap,
                    )
            version = await call(
                "POST",
                path + "/publish",
                {"operationId": "publish", "expectedRevision": 1},
            )
            async with httpx.AsyncClient(base_url="http://api:8000") as public:
                secret = secrets.token_urlsafe(48)
                url = f"/api/v1/public/surveys/{sid}/participations"
                started = await public.post(
                    url, json={"operationId": "anonymous", "resumeSecret": secret}
                )
                assert started.status_code == 200
                pid = started.json()["id"]
                cookie = {"Cookie": f"__Host-survey_{pid}={secret}"}
                saved = await public.put(
                    url + "/" + pid,
                    json={
                        "operationId": "save",
                        "expectedRevision": 1,
                        "answers": {"answer": "Synthetic matrix answer"},
                    },
                    headers=cookie,
                )
                assert saved.status_code == 200
                completed = await public.post(
                    url + "/" + pid + "/complete",
                    json={"operationId": "complete", "expectedRevision": 2},
                    headers=cookie,
                )
                assert completed.status_code == 200
            assert not await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM survey_invitation WHERE participation_id=$1)",
                UUID(pid),
            )
            snapshot = await call(
                "POST",
                path + "/analysis",
                {"operationId": "snapshot", "filter": {"versionId": version["id"]}},
            )
            jobs = {}
            for product in ["responses_csv", "analysis_xlsx"]:
                jobs[product] = await call(
                    "POST",
                    path + "/exports",
                    {
                        "operationId": product,
                        "snapshotId": snapshot["id"],
                        "product": product,
                    },
                )
            resources.append(
                {
                    "id": sid,
                    "path": path,
                    "kind": kind,
                    "version": version["id"],
                    "snapshot": snapshot["id"],
                    "participation": pid,
                    "jobs": jobs,
                }
            )

        def expected_caps(name, kind):
            if name == "admin":
                return set(CAPS)
            if kind == "member-action" and name in {"owner", "manager"}:
                return set(CAPS)
            if kind == "standalone" and name == "owner":
                return set(CAPS)
            if kind in {"standalone", "member-action"} and name in CAPS:
                return {name}
            return set()

        async def fingerprint():
            values = []
            for table in [
                "survey",
                "survey_draft",
                "survey_participation",
                "survey_version",
                "survey_operation",
                "survey_analysis_snapshot",
                "survey_invitation",
                "survey_export_job",
                "survey_deletion",
                "outbox_event",
            ]:
                rows = await conn.fetch(
                    f"SELECT row_to_json(t)::text AS value FROM {table} t ORDER BY row_to_json(t)::text"
                )
                values.extend(row["value"] for row in rows)
            return hashlib.sha256("\n".join(values).encode()).hexdigest()

        own_jobs = {}
        for name in actors:
            for resource in resources:
                caps = expected_caps(name, resource["kind"])
                for product, cap in [
                    ("responses_csv", "export_raw"),
                    ("analysis_xlsx", "export_reports"),
                ]:
                    if cap in caps:
                        job = await call(
                            "POST",
                            resource["path"] + "/exports",
                            {
                                "operationId": "own-matrix-" + product,
                                "snapshotId": resource["snapshot"],
                                "product": product,
                            },
                            actor=name,
                        )
                        own_jobs[(name, resource["kind"], product)] = job["id"]
        before = await fingerprint()
        for name in actors:
            expected_ids = {
                str(r["id"]) for r in resources if expected_caps(name, r["kind"])
            }
            for suffix in ["", "&status=active", "&offset=1"]:
                listing = await call(
                    "GET",
                    "/api/v1/surveys?search=Permission%20matrix" + suffix,
                    actor=name,
                )
                assert listing["total"] == len(expected_ids)
                actual = {item["id"] for item in listing["items"]}
                assert actual <= expected_ids
                assert len(actual) == max(
                    0, len(expected_ids) - (1 if "offset" in suffix else 0)
                )
                if "offset" not in suffix:
                    assert actual == expected_ids
            allowed_actions = (
                set(map(str, actions))
                if name == "admin"
                else ({str(actions[0])} if name == "manager" else set())
            )
            assert {item["id"] for item in listing["actions"]} == allowed_actions
            for resource in resources:
                counts["personaResourcePairs"] += 1
                caps = expected_caps(name, resource["kind"])
                path, snap = resource["path"], resource["snapshot"]
                summary = await call(
                    "GET", path, actor=name, expected=200 if caps else 404
                )
                if caps:
                    assert set(summary["capabilities"]) == caps
                reads = [
                    ("/draft", {"design"}),
                    ("/analysis/versions", {"view_aggregates"}),
                    ("/analysis/" + snap, {"view_aggregates"}),
                    ("/response-selections/versions", {"read_responses"}),
                    ("/response-selections/" + snap, {"read_responses"}),
                    ("/response-selections/" + snap + "/responses", {"read_responses"}),
                    (
                        "/response-selections/" + snap + "/free-text/answer",
                        {"read_responses"},
                    ),
                    ("/export-selections/versions", {"export_raw", "export_reports"}),
                    ("/invitations", {"manage_invitations"}),
                    (
                        "/response-selections/"
                        + snap
                        + "/responses/"
                        + resource["participation"],
                        {"read_responses"},
                    ),
                    (
                        "/exports/" + resource["jobs"]["responses_csv"]["id"],
                        {"export_raw"} if name == "admin" else set(),
                    ),
                    (
                        "/exports/" + resource["jobs"]["analysis_xlsx"]["id"],
                        {"export_reports"} if name == "admin" else set(),
                    ),
                ]
                for suffix, required in reads:
                    allowed = bool(caps & required)
                    await call(
                        "GET",
                        path + suffix,
                        actor=name,
                        expected=200 if allowed else 404,
                    )
                    counts["positiveReads" if allowed else "deniedReads"] += 1
                for product in ["responses_csv", "analysis_xlsx"]:
                    jid = own_jobs.get((name, resource["kind"], product))
                    if jid:
                        await call("GET", path + "/exports/" + jid, actor=name)
                        counts["positiveReads"] += 1
                mutation = {"operationId": "matrix-denied", "expectedRevision": 1}
                selection = {
                    "operationId": "matrix-denied",
                    "filter": {"versionId": resource["version"]},
                }
                writes = [
                    (
                        "PUT",
                        "/draft",
                        {**mutation, "definition": DEFINITION},
                        {"design"},
                    ),
                    ("POST", "/draft/validate", {"expectedRevision": 1}, {"design"}),
                    (
                        "PUT",
                        "/settings",
                        {**mutation, "inactivityTimeoutSeconds": 90},
                        {"design"},
                    ),
                    (
                        "POST",
                        "/duplicate",
                        {
                            **mutation,
                            "targetSurveyId": str(uuid4()),
                            "title": "Denied duplicate",
                        },
                        {"design"},
                    ),
                    ("POST", "/publish", mutation, {"publish"}),
                    ("PUT", "/schedule", {**mutation, "endsAt": None}, {"publish"}),
                    (
                        "PUT",
                        "/access",
                        {**mutation, "accessMode": "invitation"},
                        {"publish"},
                    ),
                    *[
                        ("POST", "/transition", {**mutation, "action": action}, {cap})
                        for action, cap in [
                            ("end", "publish"),
                            ("archive", "archive"),
                            ("unarchive", "archive"),
                            ("trash", "delete"),
                            ("restore", "delete"),
                        ]
                    ],
                    ("POST", "/delete-permanently", mutation, {"delete"}),
                    ("POST", "/analysis", selection, {"view_aggregates"}),
                    ("POST", "/response-selections", selection, {"read_responses"}),
                    (
                        "POST",
                        "/export-selections",
                        selection,
                        {"export_raw", "export_reports"},
                    ),
                    (
                        "POST",
                        "/invitations",
                        {
                            **mutation,
                            "recipientEmail": "matrix@example.com",
                            "expiresInDays": 30,
                        },
                        {"manage_invitations"},
                    ),
                    *[
                        (
                            "POST",
                            "/exports",
                            {
                                "operationId": "matrix-denied",
                                "snapshotId": snap,
                                "product": product,
                            },
                            {cap},
                        )
                        for product, cap in [
                            ("responses_csv", "export_raw"),
                            ("analysis_xlsx", "export_reports"),
                        ]
                    ],
                ]
                for method, suffix, body, required in writes:
                    if caps & required:
                        continue  # Authorized mutations have separate lifecycle/export/invitation proofs.
                    await call(method, path + suffix, body, actor=name, expected=404)
                    counts["deniedWrites"] += 1
                for product, cap in [
                    ("responses_csv", "export_raw"),
                    ("analysis_xlsx", "export_reports"),
                ]:
                    if name != "admin" or cap not in caps:
                        await call(
                            "GET",
                            path
                            + "/exports/"
                            + resource["jobs"][product]["id"]
                            + "/download",
                            actor=name,
                            expected=404,
                        )
                        counts["deniedReads"] += 1
        assert await fingerprint() == before, (
            "Matrix requests changed persisted author state"
        )
    await conn.close()
    Path("/proof/permissions-proof.json").write_text(
        json.dumps(
            {
                "syntheticOnly": True,
                "personas": list(actors),
                "resourceKinds": [r["kind"] for r in resources],
                **counts,
                "listsCountsSearchPaginationScoped": True,
                "deniedOperationsPreserveSqlFingerprint": True,
            },
            indent=2,
        )
        + "\n"
    )
    print("PASS: independent persona/resource HTTP matrix and unchanged SQL", counts)


asyncio.run(main())
