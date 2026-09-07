"""Independent SQL checks after browser writes by separate single-grant members."""

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID
import asyncpg


async def main():
    proof = Path("/proof")
    fixture = json.loads((proof / "role-journeys-private.json").read_text())
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    results = []
    for journey in fixture["journeys"]:
        sid = UUID(journey["id"])
        result = json.loads(
            (
                proof
                / f"role-lifecycle-{journey['kind']}-{str(journey['mobile']).lower()}.json"
            ).read_text()
        )
        if journey["mobile"]:
            for table, column in [
                ("survey", "id"),
                ("survey_draft", "survey_id"),
                ("survey_version", "survey_id"),
                ("survey_participation", "survey_id"),
                ("survey_operation", "survey_id"),
            ]:
                assert not await conn.fetchval(
                    f"SELECT EXISTS(SELECT 1 FROM {table} WHERE {column}=$1)", sid
                )
            ledger = await conn.fetchrow(
                "SELECT requested_by,completed_at FROM survey_deletion WHERE survey_id=$1",
                sid,
            )
            assert (
                ledger["completed_at"]
                and str(ledger["requested_by"]) == fixture["actors"]["delete"]["id"]
            )
        else:
            row = await conn.fetchrow(
                "SELECT status,action_id,inactivity_timeout_seconds FROM survey WHERE id=$1",
                sid,
            )
            assert row["status"] == "ended" and row["inactivity_timeout_seconds"] == 90
            assert (str(row["action_id"]) if row["action_id"] else None) == journey[
                "actionId"
            ]
            versions = await conn.fetch(
                "SELECT definition FROM survey_version WHERE survey_id=$1", sid
            )
            assert (
                len(versions) == 1
                and json.loads(versions[0]["definition"])["pages"][0]["elements"][0][
                    "title"
                ]
                == "Separate role feedback"
            )
            responses = await conn.fetch(
                "SELECT status,answers FROM survey_participation WHERE survey_id=$1",
                sid,
            )
            assert len(responses) == 1 and responses[0]["status"] == "completed"
            assert (
                json.loads(responses[0]["answers"])["answer"]
                == "Preserved role response"
            )
        results.append(result)
    await conn.close()
    (proof / "role-lifecycle-proof.json").write_text(
        json.dumps(
            {"syntheticOnly": True, "sqlVerified": True, "journeys": results}, indent=2
        )
        + "\n"
    )
    print(
        "PASS: four separate-role lifecycle journeys match persisted versions/responses or completed erasure"
    )


asyncio.run(main())
