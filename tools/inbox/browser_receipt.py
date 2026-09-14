"""Verify a browser-confirmed Inbox reference against real PostgreSQL and Twenty."""

import argparse
import asyncio
import os
from uuid import UUID

import asyncpg
from pydantic import SecretStr

from leonaid.adapters.twenty.gateway import TwentyCrmGateway, TwentyGatewaySettings


async def main(reference: UUID, action_id: UUID, linked: bool) -> None:
    db = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        rows = await db.fetch(
            "SELECT c.*,o.status AS job_status FROM inbox_case c JOIN outbox_event o ON o.id=c.contact_job_id WHERE c.public_reference=$1",
            reference,
        )
        assert len(rows) == 1, "Expected exactly one confirmed case and contact job"
        row = rows[0]
        assert row["action_id"] == action_id
        if linked:
            assert row["contact_status"] == "linked"
            assert row["job_status"] == "completed"
            assert row["status"] == "in_progress" and row["revision"] == 2
            async with TwentyCrmGateway(
                TwentyGatewaySettings(
                    base_url=os.environ["TWENTY_BASE_URL"],
                    api_key=SecretStr(os.environ["TWENTY_INTEGRATION_API_KEY"]),
                    max_rate_limit_retries=0,
                )
            ) as crm:
                person = await crm.get_person(
                    row["contact_create_id"], correlation_id="inbox-browser-recovery"
                )
                assert person is not None
                assert person.twenty_id == row["twenty_person_id"]
                matches = await crm.search_people(
                    given_name=row["given_name"],
                    family_name=row["family_name"],
                    correlation_id="inbox-browser-duplicates",
                )
                assert len(matches) == 1, "Expected one synthetic test contact"
            print(
                "PASS one confirmed case/job, correlated Twenty contact, no duplicate test contact, preserved case edit"
            )
        else:
            assert row["contact_status"] in ("pending", "failed")
            assert row["job_status"] in ("pending", "processing", "dead_letter")
            print("PASS one confirmed case/job with pending contact resolution")
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=UUID, required=True)
    parser.add_argument("--action-id", type=UUID, required=True)
    parser.add_argument("--linked", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.reference, args.action_id, args.linked))
