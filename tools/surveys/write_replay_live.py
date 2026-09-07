"""Concurrent exact retries for every survey write against real HTTP/PostgreSQL."""

import asyncio
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
import re
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.entrypoints.fastapi.schemas import ApiErrorResponse
from leonaid.entrypoints.fastapi.surveys import router

# Exact row-count deltas for two concurrent identical requests, not just equality
# of HTTP bodies. All unlisted survey/outbox tables must retain their row counts.
DELTAS = {
    "createSurvey": {"survey": 1, "survey_draft": 1, "survey_operation": 1},
    "saveSurveyDraft": {"survey_operation": 1},
    "validateSurveyDraft": {},
    "publishSurvey": {"survey_version": 1, "survey_operation": 1},
    "updateSurveySettings": {"survey_settings_operation": 1},
    "updateSurveyTimeout": {"survey_operation": 1},
    "scheduleSurveyEnd": {"survey_operation": 1},
    "updateSurveyAccess": {"survey_operation": 1},
    "transitionSurvey": {"survey_operation": 1},
    "duplicateSurvey": {"survey": 1, "survey_draft": 1, "survey_operation": 1},
    "deleteSurveyPermanently": {"survey_deletion": 1, "outbox_event": 1},
    "createSurveyInvitation": {
        "survey_invitation": 1,
        "outbox_event": 1,
        "survey_operation": 1,
    },
    "revokeSurveyInvitation": {"survey_operation": 1},
    "createSurveyAnalysis": {"survey_analysis_snapshot": 1, "survey_operation": 1},
    "createSurveyResponseSelection": {
        "survey_analysis_snapshot": 1,
        "survey_operation": 1,
    },
    "createSurveyExportSelection": {
        "survey_analysis_snapshot": 1,
        "survey_operation": 1,
    },
    "createSurveyExport": {"survey_export_job": 1, "outbox_event": 1},
    "startSurveyParticipation": {"survey_participation": 1, "survey_operation": 1},
    "redeemSurveyInvitation": {"survey_participation": 1},
    "saveSurveyResponse": {"survey_operation": 1},
    "completeSurveyResponse": {"survey_operation": 1},
}


REVISION_POLICIES = {
    "saveSurveyDraft": "revision_conflict",
    "validateSurveyDraft": None,
    "publishSurvey": "revision_conflict",
    "updateSurveySettings": "revision_conflict",
    "updateSurveyTimeout": "revision_conflict",
    "scheduleSurveyEnd": "revision_conflict",
    "updateSurveyAccess": "revision_conflict",
    "transitionSurvey": "revision_conflict",
    "duplicateSurvey": None,
    "deleteSurveyPermanently": "idempotency_conflict",
    "createSurveyInvitation": None,
    "revokeSurveyInvitation": None,
    "saveSurveyResponse": "revision_conflict",
    "completeSurveyResponse": "closed",
}


async def main(competing=False):
    routes = {
        r.operation_id: r
        for r in router.routes
        if r.methods & {"POST", "PUT", "PATCH", "DELETE"}
    }
    assert set(routes) == set(DELTAS), "Concurrent write inventory drift"
    if competing:
        revision_routes = {
            name
            for name, route in routes.items()
            if "expectedRevision" in route.body_field.type_.model_fields
        }
        assert revision_routes == set(REVISION_POLICIES), "Revision inventory drift"
    env = dict(
        line.split("=", 1)
        for line in Path("/proof/session.env").read_text().splitlines()
    )
    admin = {"Cookie": "__Host-leonaid_session=" + env["SURVEY_ADMIN_SESSION"]}
    definition = {
        "pages": [{"name": "one", "elements": [{"type": "text", "name": "answer"}]}]
    }
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    tables = [
        row["tablename"]
        for row in await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'survey_%' OR tablename='survey' OR tablename='outbox_event') ORDER BY tablename"
        )
    ]

    async def state():
        counts, digests = {}, {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            values = await conn.fetch(
                f"SELECT to_jsonb(t)::text AS value FROM {quoted} t"
            )
            counts[table] = len(values)
            digests[table] = hashlib.sha256(
                json.dumps(sorted(r["value"] for r in values)).encode()
            ).hexdigest()
        return counts, digests

    def mutation(revision=1):
        return {"operationId": str(uuid4()), "expectedRevision": revision}

    evidence = []
    try:
        async with httpx.AsyncClient(base_url="http://api:8000", timeout=30) as client:

            async def send(name, body, ids, headers=None):
                route = routes[name]
                return await client.request(
                    next(iter(route.methods)),
                    route.path.format(**ids),
                    json=body,
                    headers=admin if headers is None else headers,
                )

            async def good(name, body, ids, headers=None):
                response = await send(name, body, ids, headers)
                assert response.status_code == 200, (
                    name,
                    "setup",
                    response.status_code,
                )
                return response.json()

            async def summary(ids):
                response = await client.get(
                    "/api/v1/surveys/" + ids["survey_id"], headers=admin
                )
                assert response.status_code == 200
                return response.json()

            for name in REVISION_POLICIES if competing else DELTAS:
                ids = {"survey_id": str(uuid4())}
                body = mutation()
                headers = admin
                create = {
                    "operationId": str(uuid4()),
                    "title": "Concurrent contract fixture",
                    "definition": definition,
                }
                if name != "createSurvey":
                    await good("createSurvey", create, ids)
                if name in {
                    "createSurveyInvitation",
                    "revokeSurveyInvitation",
                    "redeemSurveyInvitation",
                }:
                    await good(
                        "updateSurveyAccess",
                        {**mutation(), "accessMode": "invitation"},
                        ids,
                    )
                if name in {
                    "transitionSurvey",
                    "createSurveyInvitation",
                    "revokeSurveyInvitation",
                    "redeemSurveyInvitation",
                    "createSurveyAnalysis",
                    "createSurveyResponseSelection",
                    "createSurveyExportSelection",
                    "createSurveyExport",
                    "startSurveyParticipation",
                    "saveSurveyResponse",
                    "completeSurveyResponse",
                }:
                    version = await good("publishSurvey", mutation(), ids)
                    body = mutation((await summary(ids))["revision"])
                if name in {"revokeSurveyInvitation", "redeemSurveyInvitation"}:
                    invitation = await good(
                        "createSurveyInvitation",
                        {
                            **mutation((await summary(ids))["revision"]),
                            "recipientEmail": "recipient@example.com",
                        },
                        ids,
                    )
                    ids["invitation_id"] = invitation["id"]
                if name in {"saveSurveyResponse", "completeSurveyResponse"}:
                    secret = uuid4().hex + uuid4().hex
                    participation = await good(
                        "startSurveyParticipation",
                        {
                            "operationId": str(uuid4()),
                            "resumeSecret": secret,
                        },
                        ids,
                        {},
                    )
                    ids["participation_id"] = participation["id"]
                    headers = {
                        "Cookie": f"__Host-survey_{participation['id']}={secret}"
                    }
                    body = mutation()
                    if name == "completeSurveyResponse":
                        saved = await good(
                            "saveSurveyResponse",
                            {
                                **mutation(),
                                "answers": {"answer": "Stored before completion"},
                                "currentPage": "one",
                            },
                            ids,
                            headers,
                        )
                        body = mutation(saved["revision"])
                if name == "createSurvey":
                    body = create
                elif name == "saveSurveyDraft":
                    body = {
                        **body,
                        "definition": {**definition, "title": "Accepted draft"},
                    }
                elif name == "validateSurveyDraft":
                    body = {"expectedRevision": 1}
                elif name == "updateSurveySettings":
                    settings = await client.get(
                        "/api/v1/survey-settings", headers=admin
                    )
                    assert settings.status_code == 200
                    body = {
                        **mutation(settings.json()["revision"]),
                        "inactivityTimeoutSeconds": 3600,
                    }
                elif name == "updateSurveyTimeout":
                    body = {**body, "inactivityTimeoutSeconds": 3600}
                elif name == "scheduleSurveyEnd":
                    body = {**body, "endsAt": None}
                elif name == "updateSurveyAccess":
                    body = {**body, "accessMode": "invitation"}
                elif name == "transitionSurvey":
                    body = {**body, "action": "end"}
                elif name == "duplicateSurvey":
                    body = {
                        **body,
                        "targetSurveyId": str(uuid4()),
                        "title": "Independent copy",
                    }
                elif name == "deleteSurveyPermanently":
                    trashed = await good(
                        "transitionSurvey", {**mutation(), "action": "trash"}, ids
                    )
                    body = mutation(trashed["revision"])
                elif name == "createSurveyInvitation":
                    body = {**body, "recipientEmail": "recipient@example.com"}
                elif name == "redeemSurveyInvitation":
                    encrypted = await conn.fetchval(
                        "SELECT mail_payload FROM survey_invitation WHERE id=$1",
                        UUID(ids["invitation_id"]),
                    )
                    text = SecureMailPayload(
                        os.environ["LEONAID_SESSION_ENCRYPTION_KEY"]
                    ).reveal(encrypted)["text"]
                    body = {
                        "token": re.search(r"#invitation=([A-Za-z0-9_-]+)", text).group(
                            1
                        )
                    }
                    headers = {}
                elif name in {
                    "createSurveyAnalysis",
                    "createSurveyResponseSelection",
                    "createSurveyExportSelection",
                }:
                    body = {
                        "operationId": str(uuid4()),
                        "filter": {"versionId": version["id"]},
                    }
                elif name == "createSurveyExport":
                    selection = await good(
                        "createSurveyExportSelection",
                        {
                            "operationId": str(uuid4()),
                            "filter": {"versionId": version["id"]},
                        },
                        ids,
                    )
                    body = {
                        "operationId": str(uuid4()),
                        "snapshotId": selection["id"],
                        "product": "responses_csv",
                    }
                elif name == "startSurveyParticipation":
                    body = {"operationId": str(uuid4()), "resumeSecret": "s" * 48}
                    headers = {}
                elif name == "saveSurveyResponse":
                    body = {
                        **body,
                        "answers": {"answer": "Concurrent accepted answer"},
                        "currentPage": "one",
                    }

                second = copy.deepcopy(body)
                if competing:
                    if "operationId" in second:
                        second["operationId"] = str(uuid4())
                    if name == "duplicateSurvey":
                        second["targetSurveyId"] = str(uuid4())
                        second["title"] = "Second independent copy"
                    elif name == "createSurveyInvitation":
                        second["recipientEmail"] = "second-recipient@example.com"
                    elif name == "saveSurveyDraft":
                        second["definition"]["title"] = "Rejected competing draft"
                    elif name in {"updateSurveySettings", "updateSurveyTimeout"}:
                        second["inactivityTimeoutSeconds"] = 7200
                    elif name == "saveSurveyResponse":
                        second["answers"] = {"answer": "Rejected competing answer"}
                before = await state()
                # Hold the real persistence lock until both HTTP calls demonstrably
                # wait on it, so fast execution cannot turn this into a serial test.
                tasks = []
                try:
                    async with conn.transaction():
                        if name == "updateSurveySettings":
                            await conn.fetchrow(
                                "SELECT * FROM survey_settings WHERE singleton FOR UPDATE"
                            )
                        elif name in {
                            "startSurveyParticipation",
                            "redeemSurveyInvitation",
                            "saveSurveyResponse",
                            "completeSurveyResponse",
                        }:
                            await conn.fetchrow(
                                "SELECT * FROM survey WHERE id=$1 FOR UPDATE",
                                UUID(ids["survey_id"]),
                            )
                        else:
                            await conn.execute(
                                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                                ids["survey_id"],
                            )
                        backend = await conn.fetchval("SELECT pg_backend_pid()")
                        # Observe A blocked before dispatching B: winning values are deterministic.
                        tasks = [asyncio.create_task(send(name, body, ids, headers))]
                        if not competing:
                            tasks.append(
                                asyncio.create_task(send(name, body, ids, headers))
                            )
                        async with asyncio.timeout(10):
                            while True:
                                await conn.execute("SELECT pg_stat_clear_snapshot()")
                                blocked = await conn.fetchval(
                                    """WITH RECURSIVE blocked(pid) AS (
                                    SELECT pid FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid))
                                    UNION
                                    SELECT a.pid FROM pg_stat_activity a JOIN blocked b ON b.pid=ANY(pg_blocking_pids(a.pid))
                                ) SELECT count(*) FROM blocked""",
                                    backend,
                                )
                                if competing and len(tasks) == 1 and blocked >= 1:
                                    tasks.append(
                                        asyncio.create_task(
                                            send(name, second, ids, headers)
                                        )
                                    )
                                    continue
                                if blocked >= 2:
                                    break
                                assert not any(t.done() for t in tasks), (
                                    name,
                                    "request bypassed expected persistence lock",
                                )
                                await asyncio.sleep(0.02)
                except BaseException:
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise
                results = await asyncio.gather(*tasks)
                conflict_code = REVISION_POLICIES[name] if competing else None
                statuses = [200, 409 if conflict_code else 200]
                assert [r.status_code for r in results] == statuses, (
                    name,
                    "concurrent",
                    [r.status_code for r in results],
                )
                if not competing:
                    assert results[0].json() == results[1].json(), (
                        name,
                        "replay response differs",
                    )
                elif conflict_code:
                    ApiErrorResponse.model_validate(results[1].json())
                    assert results[1].json()["error"]["code"] == conflict_code, (
                        name,
                        "competing conflict code",
                    )
                else:
                    routes[name].response_model.model_validate(results[1].json())
                    if name == "duplicateSurvey":
                        second_row = await conn.fetchrow(
                            "SELECT title,status FROM survey WHERE id=$1",
                            UUID(second["targetSurveyId"]),
                        )
                        assert (
                            second_row["title"] == second["title"]
                            and second_row["status"] == "draft"
                        )
                        assert await conn.fetchval(
                            "SELECT definition FROM survey_draft WHERE survey_id=$1",
                            UUID(second["targetSurveyId"]),
                        ) == await conn.fetchval(
                            "SELECT definition FROM survey_draft WHERE survey_id=$1",
                            UUID(body["targetSurveyId"]),
                        )
                    elif name == "createSurveyInvitation":
                        assert results[0].json()["id"] != results[1].json()["id"]
                        assert (
                            await conn.fetchval(
                                "SELECT recipient_email FROM survey_invitation WHERE id=$1",
                                UUID(results[1].json()["id"]),
                            )
                            == second["recipientEmail"]
                        )
                routes[name].response_model.model_validate(results[0].json())
                result = results[0].json()
                sid = UUID(ids["survey_id"])
                survey = await conn.fetchrow("SELECT * FROM survey WHERE id=$1", sid)
                if name in {"createSurvey", "duplicateSurvey"}:
                    selected = (
                        UUID(body["targetSurveyId"])
                        if name == "duplicateSurvey"
                        else sid
                    )
                    row = await conn.fetchrow(
                        "SELECT * FROM survey WHERE id=$1", selected
                    )
                    assert row["title"] == body["title"] and row["revision"] == 1
                    draft = await conn.fetchrow(
                        "SELECT * FROM survey_draft WHERE survey_id=$1", selected
                    )
                    assert json.loads(draft["definition"]) == definition
                elif name == "saveSurveyDraft":
                    draft = await conn.fetchrow(
                        "SELECT * FROM survey_draft WHERE survey_id=$1", sid
                    )
                    assert json.loads(draft["definition"]) == body["definition"]
                    assert draft["revision"] == body["expectedRevision"] + 1
                elif name == "publishSurvey":
                    row = await conn.fetchrow(
                        "SELECT * FROM survey_version WHERE id=$1", UUID(result["id"])
                    )
                    assert (
                        row["survey_id"] == sid
                        and json.loads(row["definition"]) == definition
                    )
                    assert (
                        survey["published_version_id"] == row["id"]
                        and survey["status"] == "active"
                    )
                elif name == "updateSurveySettings":
                    row = await conn.fetchrow(
                        "SELECT * FROM survey_settings WHERE singleton"
                    )
                    assert (
                        row["inactivity_timeout_seconds"]
                        == body["inactivityTimeoutSeconds"]
                    )
                    assert row["revision"] == body["expectedRevision"] + 1
                elif name in {
                    "updateSurveyTimeout",
                    "scheduleSurveyEnd",
                    "updateSurveyAccess",
                    "transitionSurvey",
                }:
                    field, value = {
                        "updateSurveyTimeout": ("inactivity_timeout_seconds", 3600),
                        "scheduleSurveyEnd": ("ends_at", None),
                        "updateSurveyAccess": ("access_mode", "invitation"),
                        "transitionSurvey": ("status", "ended"),
                    }[name]
                    assert (
                        survey[field] == value
                        and survey["revision"] == body["expectedRevision"] + 1
                    )
                elif name == "deleteSurveyPermanently":
                    row = await conn.fetchrow(
                        "SELECT * FROM survey_deletion WHERE survey_id=$1", sid
                    )
                    assert (
                        row["operation_hash"]
                        == hashlib.sha256(body["operationId"].encode()).hexdigest()
                    )
                    assert (
                        row["expected_revision"] == body["expectedRevision"]
                        and row["completed_at"] is None
                    )
                    assert (
                        await conn.fetchval(
                            "SELECT payload FROM outbox_event WHERE id=$1",
                            row["event_id"],
                        )
                        == "{}"
                    )
                elif name in {"createSurveyInvitation", "revokeSurveyInvitation"}:
                    row = await conn.fetchrow(
                        "SELECT * FROM survey_invitation WHERE id=$1",
                        UUID(result["id"]),
                    )
                    assert row["survey_id"] == sid
                    if name == "createSurveyInvitation":
                        assert (
                            row["recipient_email"] == body["recipientEmail"]
                            and row["mail_payload"]
                        )
                    else:
                        assert (
                            row["revoked_at"] is not None
                            and row["mail_payload"] is None
                        )
                elif name in {
                    "createSurveyAnalysis",
                    "createSurveyResponseSelection",
                    "createSurveyExportSelection",
                }:
                    row = await conn.fetchrow(
                        "SELECT * FROM survey_analysis_snapshot WHERE id=$1",
                        UUID(result["id"]),
                    )
                    assert (
                        row["survey_id"] == sid
                        and str(row["version_id"]) == body["filter"]["versionId"]
                    )
                elif name == "createSurveyExport":
                    row = await conn.fetchrow(
                        "SELECT * FROM survey_export_job WHERE id=$1",
                        UUID(result["id"]),
                    )
                    assert (
                        row["survey_id"] == sid
                        and str(row["snapshot_id"]) == body["snapshotId"]
                    )
                    assert (
                        row["product"] == body["product"] and row["status"] == "queued"
                    )
                    assert (
                        await conn.fetchval(
                            "SELECT payload FROM outbox_event WHERE id=$1",
                            row["event_id"],
                        )
                        == "{}"
                    )
                elif name in {
                    "startSurveyParticipation",
                    "redeemSurveyInvitation",
                    "saveSurveyResponse",
                    "completeSurveyResponse",
                }:
                    pid = (
                        result["id"]
                        if name
                        in {"startSurveyParticipation", "redeemSurveyInvitation"}
                        else ids["participation_id"]
                    )
                    row = await conn.fetchrow(
                        "SELECT * FROM survey_participation WHERE id=$1", UUID(pid)
                    )
                    assert (
                        row["survey_id"] == sid
                        and row["version_id"] == survey["published_version_id"]
                    )
                    if name == "saveSurveyResponse":
                        assert (
                            json.loads(row["answers"]) == body["answers"]
                            and row["current_page"] == body["currentPage"]
                        )
                        assert row["revision"] == body["expectedRevision"] + 1
                    elif name == "completeSurveyResponse":
                        assert json.loads(row["answers"]) == {
                            "answer": "Stored before completion"
                        }
                        assert (
                            row["status"] == "completed"
                            and row["completed_at"] is not None
                        )
                        assert row["revision"] == body["expectedRevision"] + 1
                    else:
                        assert json.loads(row["answers"]) == {} and row["revision"] == 1
                        if name == "redeemSurveyInvitation":
                            assert (
                                await conn.fetchval(
                                    "SELECT participation_id FROM survey_invitation WHERE id=$1",
                                    UUID(ids["invitation_id"]),
                                )
                                == row["id"]
                            )
                after = await state()
                delta = {
                    t: after[0][t] - before[0][t]
                    for t in tables
                    if after[0][t] != before[0][t]
                }
                multiplier = 2 if competing and not conflict_code else 1
                expected_delta = {
                    table: count * multiplier for table, count in DELTAS[name].items()
                }
                assert delta == expected_delta, (name, "unexpected row delta", delta)
                if name == "validateSurveyDraft":
                    assert before == after, "Validation mutated persistent state"
                repeated = await send(name, body, ids, headers)
                assert (
                    repeated.status_code == 200 and repeated.json() == results[0].json()
                ), (name, "later replay")
                assert await state() == after, (name, "later replay wrote data")
                if competing:
                    repeated_second = await send(name, second, ids, headers)
                    assert repeated_second.status_code == statuses[1]
                    if statuses[1] == 200:
                        assert repeated_second.json() == results[1].json()
                    else:
                        assert repeated_second.json()["error"]["code"] == conflict_code
                    assert await state() == after, (
                        name,
                        "second operation replay wrote data",
                    )
                changed = copy.deepcopy(body)
                if "expectedRevision" in body:
                    changed["expectedRevision"] += 100
                elif name == "createSurvey":
                    changed["title"] = "Changed under same key"
                elif name in {
                    "createSurveyAnalysis",
                    "createSurveyResponseSelection",
                    "createSurveyExportSelection",
                }:
                    changed["filter"]["statuses"] = ["completed"]
                elif name == "createSurveyExport":
                    changed["product"] = "responses_xlsx"
                else:
                    changed = None  # Start identity is secret-scoped; redemption has no operation ID.
                code = None
                if changed is not None:
                    conflict = await send(name, changed, ids, headers)
                    assert conflict.status_code == 409, (
                        name,
                        "changed key",
                        conflict.status_code,
                    )
                    payload = conflict.json()
                    ApiErrorResponse.model_validate(payload)
                    code = (
                        "revision_conflict"
                        if name == "validateSurveyDraft"
                        else "idempotency_conflict"
                    )
                    assert payload["error"]["code"] == code, (name, "conflict code")
                    assert await state() == after, (name, "conflict wrote data")
                evidence.append(
                    {
                        "operationId": name,
                        "concurrentStatuses": statuses,
                        "identicalResponse": results[0].json() == results[1].json(),
                        "competingRevision": competing,
                        "secondOperationConflictCode": conflict_code,
                        "bothRequestsObservedBlockedOnPersistenceLock": True,
                        "storedOperationOutcomeVerified": True,
                        "exactRowDeltas": delta,
                        "laterReplayPreservedAllRows": True,
                        "changedRequestConflictCode": code,
                    }
                )
                print(
                    "PASS: competing revision and exact retry:"
                    if competing
                    else "PASS: concurrent and later replay:",
                    name,
                )
            if competing:
                Path("/proof/write-competing-revisions.json").write_text(
                    json.dumps(
                        {
                            "syntheticOnly": True,
                            "operations": evidence,
                            "tablesChecked": tables,
                            "scope": "All revision-bearing transport operations; two different operation keys at one revision with observed ordered lock contention and exact later retries",
                        },
                        indent=2,
                    )
                    + "\n"
                )
                return
            # A syntactically valid credential may collide across survey scopes.
            # Hold the participation table to force both independent inserts to wait
            # before its global uniqueness constraint selects one winner.
            collision_ids = [{"survey_id": str(uuid4())} for _ in range(2)]
            for target in collision_ids:
                await good(
                    "createSurvey",
                    {
                        "operationId": str(uuid4()),
                        "title": "Credential collision fixture",
                        "definition": definition,
                    },
                    target,
                )
                await good("publishSurvey", mutation(), target)
            secret = uuid4().hex + uuid4().hex
            shared = {"operationId": str(uuid4()), "resumeSecret": secret}
            before = await state()
            tasks = []
            try:
                async with conn.transaction():
                    await conn.execute("LOCK TABLE survey_participation IN SHARE MODE")
                    backend = await conn.fetchval("SELECT pg_backend_pid()")
                    tasks = [
                        asyncio.create_task(
                            send("startSurveyParticipation", shared, target, {})
                        )
                        for target in collision_ids
                    ]
                    async with asyncio.timeout(10):
                        while True:
                            await conn.execute("SELECT pg_stat_clear_snapshot()")
                            blocked = await conn.fetchval(
                                "SELECT count(*) FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid))",
                                backend,
                            )
                            if blocked >= 2:
                                break
                            assert not any(t.done() for t in tasks), (
                                "Collision request bypassed table barrier"
                            )
                            await asyncio.sleep(0.02)
            except BaseException:
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
            raced = await asyncio.gather(*tasks)
            assert sorted(r.status_code for r in raced) == [200, 409], (
                "Credential collision must not return 500 or create two participations"
            )
            winner = next(i for i, r in enumerate(raced) if r.status_code == 200)
            after = await state()
            assert {
                t: after[0][t] - before[0][t]
                for t in tables
                if after[0][t] != before[0][t]
            } == {"survey_participation": 1, "survey_operation": 1}
            winning_id = UUID(raced[winner].json()["id"])
            row = await conn.fetchrow(
                "SELECT * FROM survey_participation WHERE id=$1", winning_id
            )
            assert str(row["survey_id"]) == collision_ids[winner]["survey_id"]
            assert row["resume_digest"] == hashlib.sha256(secret.encode()).hexdigest()
            assert json.loads(row["answers"]) == {} and row["revision"] == 1
            for i, target in enumerate(collision_ids):
                replay = await send("startSurveyParticipation", shared, target, {})
                assert replay.status_code == (200 if i == winner else 409)
                if i == winner:
                    assert replay.json() == raced[i].json()
                else:
                    ApiErrorResponse.model_validate(replay.json())
                    assert replay.json()["error"]["code"] == "idempotency_conflict"
                    assert (
                        secret not in replay.text and str(winning_id) not in replay.text
                    )
                assert await state() == after, "Collision replay changed data"
            changed_key = await send(
                "startSurveyParticipation",
                {**shared, "operationId": str(uuid4())},
                collision_ids[winner],
                {},
            )
            assert (
                changed_key.status_code == 409
                and changed_key.json()["error"]["code"] == "idempotency_conflict"
            )
            assert await state() == after, (
                "Reused credential with new operation changed data"
            )
            print(
                "PASS: overlapping cross-survey credential collision yields one participation and a stable 409; exact winner replay and changed-key denial preserve rows"
            )
        Path("/proof/write-replay.json").write_text(
            json.dumps(
                {
                    "syntheticOnly": True,
                    "crossSurveyCredentialCollision": {
                        "overlappingInsertsObserved": True,
                        "statuses": [200, 409],
                        "participationDelta": 1,
                        "stableReplayAndNoExtraWrites": True,
                    },
                    "operations": evidence,
                    "tablesChecked": tables,
                    "scope": "Concurrent identical requests and changed-key rejection; independent competing revisions and cross-operation races require their separate proofs",
                },
                indent=2,
            )
            + "\n"
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--competing-revisions"]):
        raise SystemExit("usage: write_replay_live.py [--competing-revisions]")
    asyncio.run(main(competing=bool(sys.argv[1:])))
