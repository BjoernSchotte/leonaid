"""Verify publisher-only browser output against actual persisted versions."""

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID
import asyncpg


async def main():
    data = json.loads(Path("/proof/publisher-browser.json").read_text())
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    sid = UUID(data.pop("survey"))
    assert await conn.fetchval("SELECT status FROM survey WHERE id=$1", sid) == "active"
    versions = await conn.fetch(
        "SELECT definition FROM survey_version WHERE survey_id=$1", sid
    )
    assert len(versions) == 1
    assert (
        json.loads(versions[0]["definition"])["pages"][0]["elements"][0]["title"]
        == "Reviewed revision two"
    )
    assert (
        await conn.fetchval(
            "SELECT count(*) FROM survey_participation WHERE survey_id=$1", sid
        )
        == 0
    )
    assert (
        await conn.fetchval("SELECT revision FROM survey_draft WHERE survey_id=$1", sid)
        == 3
    )
    await conn.close()
    Path("/proof/publisher-proof.json").write_text(
        json.dumps(
            {
                **data,
                "syntheticOnly": True,
                "publishedVersions": 1,
                "persistedParticipations": 0,
                "publishedReviewedRevision": True,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        "PASS: publisher-only exact retry created one reviewed version and no preview participation"
    )


asyncio.run(main())
