"""Observe real PostgreSQL contention for competing lifecycle operations."""

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx


async def main():
    env = dict(
        line.split("=", 1)
        for line in Path("/proof/session.env").read_text().splitlines()
    )
    admin = {"Cookie": "__Host-leonaid_session=" + env["SURVEY_ADMIN_SESSION"]}
    definition = {
        "pages": [{"name": "one", "elements": [{"type": "text", "name": "answer"}]}]
    }
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    evidence = []
    try:
        async with httpx.AsyncClient(base_url="http://api:8000", timeout=30) as client:

            async def request(method, path, body=None, headers=None):
                return await client.request(
                    method,
                    path,
                    json=body,
                    headers=admin if headers is None else headers,
                )

            async def good(method, path, body=None, headers=None):
                result = await request(method, path, body, headers)
                assert result.status_code == 200, (method, "setup", result.status_code)
                return result.json()

            async def ordered_pair(sid, operations):
                tasks = []
                observed = []
                try:
                    async with conn.transaction():
                        await conn.fetchrow(
                            "SELECT * FROM survey WHERE id=$1 FOR UPDATE", sid
                        )
                        backend = await conn.fetchval("SELECT pg_backend_pid()")
                        for operation in operations:
                            tasks.append(asyncio.create_task(request(*operation)))
                            async with asyncio.timeout(10):
                                while True:
                                    await conn.execute(
                                        "SELECT pg_stat_clear_snapshot()"
                                    )
                                    blocked = await conn.fetchval(
                                        """WITH RECURSIVE blocked(pid) AS (
                                        SELECT pid FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid))
                                        UNION
                                        SELECT a.pid FROM pg_stat_activity a JOIN blocked b ON b.pid=ANY(pg_blocking_pids(a.pid))
                                    ) SELECT count(*) FROM blocked""",
                                        backend,
                                    )
                                    assert not any(task.done() for task in tasks), (
                                        "Request bypassed persistence barrier"
                                    )
                                    if blocked >= len(tasks):
                                        observed.append(blocked)
                                        break
                                    await asyncio.sleep(0.02)
                except BaseException:
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise
                return await asyncio.gather(*tasks), observed

            # Each ordering uses a fresh survey and actual HTTP operations.
            orders = [
                ("save-a", "save-b"),
                ("save-b", "save-a"),
                ("save-a", "publish"),
                ("publish", "save-a"),
                ("publish-a", "publish-b"),
                ("publish-b", "publish-a"),
                ("end", "complete"),
                ("complete", "end"),
            ]
            for first, second in orders:
                sid = uuid4()
                base = f"/api/v1/surveys/{sid}"
                await good(
                    "POST",
                    base,
                    {
                        "operationId": "create",
                        "title": "Ordered lifecycle fixture",
                        "definition": definition,
                    },
                )

                def body(name, revision=1):
                    return {"operationId": name, "expectedRevision": revision}

                calls = {}
                for name in [first, second]:
                    if name.startswith("save"):
                        calls[name] = (
                            "PUT",
                            base + "/draft",
                            {**body(name), "definition": {**definition, "title": name}},
                            None,
                        )
                    elif name.startswith("publish"):
                        calls[name] = ("POST", base + "/publish", body(name), None)
                pid = None
                if first in {"end", "complete"}:
                    await good("POST", base + "/publish", body("initial-publication"))
                    secret = uuid4().hex + uuid4().hex
                    public = f"/api/v1/public/surveys/{sid}/participations"
                    participation = await good(
                        "POST",
                        public,
                        {"operationId": "start", "resumeSecret": secret},
                        {},
                    )
                    pid = UUID(participation["id"])
                    credentials = {"Cookie": f"__Host-survey_{pid}={secret}"}
                    path = public + f"/{pid}"
                    await good(
                        "PUT",
                        path,
                        {
                            **body("initial-save"),
                            "answers": {"answer": "Acknowledged before cutoff"},
                            "currentPage": "one",
                        },
                        credentials,
                    )
                    summary = await good("GET", base)
                    calls["end"] = (
                        "POST",
                        base + "/transition",
                        {**body("end", summary["revision"]), "action": "end"},
                        None,
                    )
                    calls["complete"] = (
                        "POST",
                        path + "/complete",
                        body("complete", 2),
                        credentials,
                    )
                results, waits = await ordered_pair(sid, [calls[first], calls[second]])
                statuses = [r.status_code for r in results]
                expected = [200, 200] if first == "complete" else [200, 409]
                assert statuses == expected, (first, second, statuses, expected)
                if pid is None:
                    draft = await conn.fetchrow(
                        "SELECT revision,definition FROM survey_draft WHERE survey_id=$1",
                        sid,
                    )
                    assert draft["revision"] == 2
                    expected_definition = (
                        {**definition, "title": first}
                        if first.startswith("save")
                        else definition
                    )
                    assert json.loads(draft["definition"]) == expected_definition
                    versions = await conn.fetch(
                        "SELECT definition FROM survey_version WHERE survey_id=$1", sid
                    )
                    assert len(versions) == int(first.startswith("publish"))
                    if versions:
                        assert json.loads(versions[0]["definition"]) == definition
                else:
                    row = await conn.fetchrow(
                        "SELECT status,revision,answers,completed_at FROM survey_participation WHERE id=$1",
                        pid,
                    )
                    assert row["status"] == (
                        "completed" if first == "complete" else "partial"
                    )
                    assert row["revision"] == (3 if first == "complete" else 2)
                    assert bool(row["completed_at"]) == (first == "complete")
                    assert json.loads(row["answers"]) == {
                        "answer": "Acknowledged before cutoff"
                    }
                    assert (await good("GET", base))["status"] == "ended"
                    late = await request(
                        "PUT",
                        path,
                        {
                            **body("late", row["revision"]),
                            "answers": {
                                "answer": "Must not replace acknowledged content"
                            },
                        },
                        credentials,
                    )
                    assert late.status_code == 409
                    assert (
                        await conn.fetchval(
                            "SELECT answers FROM survey_participation WHERE id=$1", pid
                        )
                        == row["answers"]
                    )

                # Replay remains subject to current lifecycle guards. An ended
                # survey rejects even an already committed public completion.
                async def persisted_state():
                    state = {}
                    for table in (
                        "survey",
                        "survey_draft",
                        "survey_version",
                        "survey_participation",
                        "survey_operation",
                    ):
                        key = "id" if table == "survey" else "survey_id"
                        rows = await conn.fetch(
                            f"SELECT to_jsonb(t)::text AS value FROM {table} t WHERE {key}=$1",
                            sid,
                        )
                        state[table] = sorted(row["value"] for row in rows)
                    return state

                before_retry = await persisted_state()
                retried = await request(*calls[first])
                if first == "complete":
                    assert retried.status_code == 409
                    assert retried.json()["error"]["code"] == "closed"
                else:
                    assert retried.status_code == 200
                    assert retried.json() == results[0].json()
                assert (await request(*calls[second])).status_code == expected[1]
                assert await persisted_state() == before_retry
                evidence.append(
                    {
                        "order": [first, second],
                        "blockedRequestsObserved": waits,
                        "httpStatuses": statuses,
                        "persistedOutcomeVerified": True,
                    }
                )
            Path("/proof/lifecycle-concurrency.json").write_text(
                json.dumps({"syntheticOnly": True, "cases": evidence}, indent=2) + "\n"
            )
            print(
                "PASS: eight observed PostgreSQL contention orders; winning draft/version, both end/completion cutoffs, exact retries and unchanged acknowledged answers"
            )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
