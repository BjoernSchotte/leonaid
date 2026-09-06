"""Create published synthetic surveys through the actual authoring API."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4
import httpx


async def main():
    path = Path("/proof/session.env")
    token = next(
        line.split("=", 1)[1]
        for line in path.read_text().splitlines()
        if line.startswith("SURVEY_ADMIN_SESSION=")
    )
    async with httpx.AsyncClient(
        base_url="http://api:8000",
        headers={"Cookie": f"__Host-leonaid_session={token}"},
    ) as client:
        entries = []
        for fixture in ["krapfentaxi", "golf", "validation-boundaries"]:
            survey_id = str(uuid4())
            definition = json.loads(
                Path(f"tests/fixtures/surveys/{fixture}.json").read_text()
            )
            result = await client.post(
                f"/api/v1/surveys/{survey_id}",
                json={
                    "operationId": "browser-create",
                    "title": definition["title"],
                    "definition": definition,
                    "inactivityTimeoutSeconds": 2,
                },
            )
            assert result.status_code == 200, result.text
            result = await client.post(
                f"/api/v1/surveys/{survey_id}/publish",
                json={"operationId": "browser-publish", "expectedRevision": 1},
            )
            assert result.status_code == 200, result.text
            entries.append(
                f"SURVEY_{fixture.upper().replace(chr(45), chr(95))}_ID={survey_id}"
            )
        path.write_text(path.read_text() + "\n".join(entries) + "\n")
    print("Published synthetic browser survey fixtures through actual API")


asyncio.run(main())
