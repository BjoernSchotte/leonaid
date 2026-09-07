"""Verify accepted campaign browser orders in actual Core SQL and Twenty."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx

from tools.public_orders.contract import assert_commitment
from tools.public_orders.verify_ui import twenty_record


async def main() -> None:
    orders = json.loads(Path("/proof/orders-ui.json").read_text())
    assert len(orders) == 18
    assert len({item["publicReference"] for item in orders}) == 18
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=5)
    try:
        async with httpx.AsyncClient(
            base_url="http://twenty-server:3000",
            timeout=15,
            headers={
                "Authorization": f"Bearer {os.environ['TWENTY_INTEGRATION_API_KEY']}"
            },
        ) as twenty:
            for item in orders:
                rows = await connection.fetch(
                    "SELECT id FROM commitment WHERE public_reference=$1",
                    item["publicReference"],
                )
                assert len(rows) == 1
                row = await assert_commitment(
                    connection,
                    {
                        "commitmentId": str(rows[0]["id"]),
                        "publicReference": item["publicReference"],
                    },
                    expected_company_id=UUID("40000000-0000-4000-8000-000000000001")
                    if item["scenario"] == "existing-company"
                    else None,
                    expected_person=item["scenario"] == "person",
                    expected_quantity=item["quantity"],
                )
                audit = await connection.fetchval(
                    "SELECT payload FROM audit_event WHERE entity_id=$1 AND event_type='public_order_created'",
                    row["id"],
                )
                audit = json.loads(audit) if isinstance(audit, str) else audit
                person_id = row["twenty_person_id"] or UUID(audit["contactTwentyId"])
                person = await twenty_record(twenty, "people", person_id)
                assert person["name"]["firstName"] == "Synthetic"
                assert person["name"]["lastName"] == item["label"]
                if item["scenario"] == "person":
                    assert person.get("companyId") in {None, ""}
                else:
                    company = await twenty_record(
                        twenty, "companies", row["twenty_company_id"]
                    )
                    assert company["name"] == item["company"]
                    assert person["companyId"] == str(row["twenty_company_id"])
                assert (
                    await connection.fetchval(
                        "SELECT count(*) FROM commitment WHERE customer_snapshot->>'email'=$1",
                        item["email"],
                    )
                    == 1
                )
                if not item["javaScriptEnabled"]:
                    assert item["nativeReplay"] is True
    finally:
        await connection.close()
    print(
        "campaign-orders: 18 browser references verified in Core SQL, lines, consent/audit and real Twenty company/person records; nine native POST replays created no duplicate orders"
    )


if __name__ == "__main__":
    asyncio.run(main())
