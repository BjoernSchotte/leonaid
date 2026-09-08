"""Real policy/API/worker retention proof using explicit short synthetic periods."""

import asyncio
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.surveys import AsyncpgSurveyRepository
from leonaid.adapters.postgres.survey_retention import sweep_retention
from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest

PROOF = Path("/proof")


async def main():
    pool = await create_pool(os.environ["CORE_DATABASE_URL"])
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    token = (PROOF / "session.env").read_text().strip().split("=", 1)[1]
    async with httpx.AsyncClient(base_url="http://api:8000", timeout=30) as client:

        async def call(method, path, body=None, expected=200, cookie=token):
            result = await client.request(
                method,
                "/api/v1" + path,
                json=body,
                headers={"Cookie": f"__Host-leonaid_session={cookie}"},
            )
            assert result.status_code == expected, (path, result.status_code, expected)
            return result

        async def policy(**changes):
            before = (await call("GET", "/survey-settings")).json()
            body = {
                "operationId": str(uuid4()),
                "expectedRevision": before["revision"],
                "inactivityTimeoutSeconds": before["inactivityTimeoutSeconds"],
                **changes,
            }
            after = await call("PUT", "/survey-settings", body)
            assert after.headers["cache-control"] == "no-store"
            assert (await call("PUT", "/survey-settings", body)).json() == after.json()
            await call(
                "PUT",
                "/survey-settings",
                {**body, "operationId": str(uuid4())},
                expected=409,
            )
            return after.json()

        if sys.argv[1] == "prepare":
            initial = (await call("GET", "/survey-settings")).json()
            assert (
                initial["endedRetentionSeconds"] is None
                and initial["trashRetentionSeconds"] is None
            )
            uid, member = uuid4(), secrets.token_urlsafe(48)
            now = datetime.now(timezone.utc)
            await conn.execute(
                "INSERT INTO user_account(id,email,display_name,status,email_verified_at) VALUES($1,$2,'Retention member','active',$3)",
                uid,
                f"{uid}@example.invalid",
                now,
            )
            await conn.execute(
                "INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$5,$5,$5)",
                uuid4(),
                uid,
                session_token_digest(member),
                now + SESSION_LIFETIME,
                now,
            )
            for method in ("GET", "PUT"):
                await call(
                    method,
                    "/survey-settings",
                    None
                    if method == "GET"
                    else {
                        "operationId": "denied",
                        "expectedRevision": initial["revision"],
                        "inactivityTimeoutSeconds": 1,
                        "trashRetentionSeconds": 1,
                    },
                    expected=403,
                    cookie=member,
                )
            for field in ("endedRetentionSeconds", "trashRetentionSeconds"):
                for invalid in (0, -1, 315360001):
                    await call(
                        "PUT",
                        "/survey-settings",
                        {
                            "operationId": str(uuid4()),
                            "expectedRevision": initial["revision"],
                            "inactivityTimeoutSeconds": 1,
                            field: invalid,
                        },
                        expected=422,
                    )
            assert (await call("GET", "/survey-settings")).json() == initial
            ids = {
                name: uuid4()
                for name in ("draft", "active", "ended", "archived", "trashed")
            }
            versions = {}
            definition = {
                "pages": [
                    {"name": "main", "elements": [{"type": "text", "name": "answer"}]}
                ]
            }

            async def transition(name, action):
                sid = ids[name]
                row = (await call("GET", f"/surveys/{sid}")).json()
                return (
                    await call(
                        "POST",
                        f"/surveys/{sid}/transition",
                        {
                            "operationId": str(uuid4()),
                            "expectedRevision": row["revision"],
                            "action": action,
                        },
                    )
                ).json()

            for name, sid in ids.items():
                await call(
                    "POST",
                    f"/surveys/{sid}",
                    {
                        "operationId": "create",
                        "title": f"Synthetic retention {name}",
                        "definition": definition,
                        "inactivityTimeoutSeconds": 1,
                    },
                )
                if name != "draft":
                    versions[name] = (
                        await call(
                            "POST",
                            f"/surveys/{sid}/publish",
                            {"operationId": "publish", "expectedRevision": 1},
                        )
                    ).json()["id"]
                if name in ("ended", "archived"):
                    await transition(name, "end")
                if name == "archived":
                    await transition(name, "archive")
                if name == "trashed":
                    await transition(name, "trash")
            await conn.execute(
                "UPDATE survey SET retention_started_at=clock_timestamp()-interval '90 days' WHERE id=ANY($1::uuid[]) AND status IN ('ended','archived')",
                list(ids.values()),
            )
            await conn.execute(
                "UPDATE survey SET deleted_at=clock_timestamp()-interval '90 days' WHERE id=$1",
                ids["trashed"],
            )
            pid = uuid4()
            await conn.execute(
                """INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,inactivity_timeout_seconds,created_at,answers)
            VALUES($1,$2,$3,$4,1,clock_timestamp()-interval '90 days','{"answer":"SENSITIVE_RETENTION_ANSWER"}')""",
                pid,
                ids["active"],
                UUID(versions["active"]),
                secrets.token_hex(32),
            )
            assert await sweep_retention(pool) == 0
            await AsyncpgSurveyRepository(pool).classify_overdue()
            assert (
                await conn.fetchval(
                    "SELECT status FROM survey_participation WHERE id=$1", pid
                )
                == "partial"
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM survey WHERE id=ANY($1::uuid[])",
                    list(ids.values()),
                )
                == 5
            )
            assert await conn.fetchval("SELECT count(*) FROM survey_deletion") == 0
            configured = await policy(
                endedRetentionSeconds=1, trashRetentionSeconds=None
            )
            omitted = await policy(inactivityTimeoutSeconds=2)
            assert (
                omitted["endedRetentionSeconds"] == 1
                and omitted["trashRetentionSeconds"] is None
            )
            assert omitted["revision"] > configured["revision"]
            # A held authoring lock is skipped without blocking policy updates.
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                    str(ids["ended"]),
                )
                assert await asyncio.wait_for(sweep_retention(pool), timeout=5) == 1
                assert (
                    await conn.fetchval(
                        "SELECT status FROM survey WHERE id=$1", ids["ended"]
                    )
                    == "ended"
                )
            assert await sweep_retention(pool) == 1
            assert await sweep_retention(pool) == 0
            for name in ("ended", "archived", "trashed"):
                assert (
                    await conn.fetchval(
                        "SELECT status FROM survey WHERE id=$1", ids[name]
                    )
                    == "deleted"
                )
            assert await conn.fetchval("SELECT count(*) FROM survey_deletion") == 0
            await policy(endedRetentionSeconds=3600)
            await transition("ended", "restore")
            restored_clock = await conn.fetchval(
                "SELECT retention_started_at FROM survey WHERE id=$1", ids["ended"]
            )
            assert restored_clock > now
            await transition("ended", "archive")
            assert (
                await conn.fetchval(
                    "SELECT retention_started_at FROM survey WHERE id=$1", ids["ended"]
                )
                == restored_clock
            )
            await transition("ended", "unarchive")
            assert (
                await conn.fetchval(
                    "SELECT retention_started_at FROM survey WHERE id=$1", ids["ended"]
                )
                == restored_clock
            )
            # Disabling both stages leaves old trash untouched, even when overdue.
            await policy(endedRetentionSeconds=None, trashRetentionSeconds=None)
            assert await sweep_retention(pool) == 0
            await policy(endedRetentionSeconds=None, trashRetentionSeconds=1)
            # Production worker restarts after this process exits and catches up.
            (PROOF / "retention-state.json").write_text(
                json.dumps(
                    {
                        "ids": {k: str(v) for k, v in ids.items()},
                        "participation": str(pid),
                    }
                )
            )
            (PROOF / "retention-member.json").write_text(json.dumps({"token": member}))
            print(
                "PASS: disabled defaults, admin-only bounded policy, idempotency, lock skipping, archive/restore clocks, inactivity preserves answers"
            )
        else:
            assert sys.argv[1] == "recover"
            state = json.loads((PROOF / "retention-state.json").read_text())
            ids = {k: UUID(v) for k, v in state["ids"].items()}
            async with asyncio.timeout(60):
                while True:
                    done = await conn.fetchval(
                        "SELECT count(*) FROM survey_deletion WHERE survey_id=ANY($1::uuid[]) AND completed_at IS NOT NULL",
                        [ids["archived"], ids["trashed"]],
                    )
                    if done == 2:
                        break
                    await asyncio.sleep(0.25)
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM survey WHERE id=ANY($1::uuid[])",
                    [ids["archived"], ids["trashed"]],
                )
                == 0
            )
            for name, expected in (
                ("draft", "draft"),
                ("active", "active"),
                ("ended", "ended"),
            ):
                assert (
                    await conn.fetchval(
                        "SELECT status FROM survey WHERE id=$1", ids[name]
                    )
                    == expected
                )
            row = await conn.fetchrow(
                "SELECT * FROM survey_participation WHERE id=$1",
                UUID(state["participation"]),
            )
            assert row["status"] == "partial" and json.loads(row["answers"]) == {
                "answer": "SENSITIVE_RETENTION_ANSWER"
            }
            for sid in (ids["archived"], ids["trashed"]):
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM outbox_event WHERE aggregate_id=$1 AND event_type='survey.delete.v1' AND status='completed'",
                        sid,
                    )
                    == 1
                )
            await policy(endedRetentionSeconds=None, trashRetentionSeconds=None)
            (PROOF / "retention-proof.json").write_text(
                json.dumps(
                    {
                        "syntheticOnly": True,
                        "disabledByDefault": True,
                        "adminOnlySettings": True,
                        "invalidAndStaleRequestsRejected": True,
                        "exactPolicyReplay": True,
                        "omittedFieldsPreservePolicy": True,
                        "busySurveySkipped": True,
                        "restoreResetsClock": True,
                        "archivePreservesClock": True,
                        "inactivityPreservesAnswers": True,
                        "restartedProductionWorkerErasedSurveys": 2,
                        "independentStages": True,
                        "activeAndDraftPreserved": True,
                        "limitations": [
                            "Backup restore and full concurrency matrix remain open"
                        ],
                    },
                    indent=2,
                )
                + "\n"
            )
            print(
                "PASS: restarted production worker completes due erasures; active responses and drafts preserved"
            )
    await conn.close()
    await pool.close()


asyncio.run(main())
