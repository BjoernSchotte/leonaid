"""Real deletion-status authorization and a persisted terminal-job UI fixture."""

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest


async def main():
    proof = Path("/proof")
    sid = UUID(json.loads((proof / "recovery-state.json").read_text())["sid"])
    token = (proof / "session.env").read_text().strip().split("=", 1)[1]
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        actor = uuid4()
        outsider = secrets.token_urlsafe(48)
        now = datetime.now(timezone.utc)
        await conn.execute(
            """INSERT INTO user_account(id,email,display_name,status,email_verified_at)
            VALUES($1,'deletion-outsider@example.invalid','Synthetic outsider','active',$2)""",
            actor,
            now,
        )
        await conn.execute(
            """INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,created_at,updated_at)
            VALUES($1,$2,$3,$4,$5,$5,$5,$5)""",
            uuid4(),
            actor,
            session_token_digest(outsider),
            now + SESSION_LIFETIME,
            now,
        )
        async with httpx.AsyncClient(base_url="http://api:8000") as client:
            path = f"/api/v1/surveys/{sid}/deletion"
            denied = await client.get(
                path, headers={"Cookie": f"__Host-leonaid_session={outsider}"}
            )
            assert denied.status_code == 404
            deletion = await conn.fetchrow(
                "SELECT * FROM survey_deletion WHERE survey_id=$1", sid
            )
            assert deletion and deletion["completed_at"] is None
            # This seeds a real persisted failure state to test administration UI;
            # actual object-delete crash/reclaim is covered by deletion_live.py.
            await conn.execute(
                "UPDATE outbox_event SET status='dead_letter',attempts=5,dead_lettered_at=clock_timestamp() WHERE id=$1",
                deletion["event_id"],
            )
            status = await client.get(
                path, headers={"Cookie": f"__Host-leonaid_session={token}"}
            )
            assert status.status_code == 200
            assert status.json()["status"] == "failed"
            assert status.json()["retryEventId"] == str(deletion["event_id"])
            # The public browser's attempted late answer was never persisted.
            values = await conn.fetch(
                "SELECT answers FROM survey_participation WHERE survey_id=$1", sid
            )
            assert any("Accepted before trash" in row["answers"] for row in values)
            assert all(
                "Must not save after trash" not in row["answers"] for row in values
            )
            denied_retry = await client.post(
                f"/api/v1/admin/operations/jobs/{deletion['event_id']}/retry",
                headers={"Cookie": f"__Host-leonaid_session={outsider}"},
            )
            assert denied_retry.status_code == 403
        result = json.loads((proof / "deletion-ui-proof.json").read_text())
        result.update(
            unrelatedMemberStatusDenied=True,
            unrelatedMemberRetryDenied=True,
            rejectedSaveNeverPersisted=True,
            persistedFailureStatus=True,
        )
        (proof / "deletion-ui-proof.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        print(
            "PASS: unrelated member denied, rejected answer absent, persisted failure exposes admin-only retry"
        )
    finally:
        await conn.close()


asyncio.run(main())
