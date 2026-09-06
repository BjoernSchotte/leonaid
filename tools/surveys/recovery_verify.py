"""Inspect the real participation and completion ledger after browser fault injection."""

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID
import asyncpg


async def main():
    state = json.loads(Path("/proof/survey-recovery.json").read_text())
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        row = await conn.fetchrow(
            "SELECT status, revision, answers, completed_at FROM survey_participation WHERE id=$1 AND survey_id=$2",
            UUID(state["participation"]),
            UUID(state["survey"]),
        )
        assert row["status"] == "completed" and row["completed_at"] is not None
        assert row["revision"] == state["revision"]
        assert json.loads(row["answers"]) == state["answers"] == {"source": "4"}
        operations = await conn.fetch(
            "SELECT operation_id, response FROM survey_operation WHERE survey_id=$1 AND scope=$2",
            UUID(state["survey"]),
            f"participation:{state['participation']}:complete",
        )
        assert len(operations) == 1
        assert operations[0]["operation_id"] == state["operation"]
        response = json.loads(operations[0]["response"])
        assert (
            response["revision"] == row["revision"]
            and response["status"] == "completed"
        )
        starts = await conn.fetchval(
            "SELECT count(*) FROM survey_operation WHERE survey_id=$1 AND scope LIKE 'start:%' AND response->>'id'=$2",
            UUID(state["survey"]),
            state["participation"],
        )
        assert starts == 1
        print(
            "PASS: reordered two-tab saves retain winning answer; one participation start and one durable completion operation after lost acknowledgement/retry"
        )
    finally:
        await conn.close()


asyncio.run(main())
