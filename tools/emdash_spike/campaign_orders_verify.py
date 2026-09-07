"""Verify accepted campaign browser orders in actual Core SQL and Twenty."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx

from tools.public_orders.contract import assert_commitment, twenty_collection


async def main() -> None:
    assert sys.argv[1:] in ([], ["--before-recovery"])
    receipt_file = (
        "/proof/pre-recovery-orders.json" if sys.argv[1:] else "/proof/orders-ui.json"
    )
    orders = json.loads(Path(receipt_file).read_text())
    assert len(orders) == 24
    assert len({item["publicReference"] for item in orders}) == 24
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=5)
    try:
        async with httpx.AsyncClient(
            base_url="http://twenty-server:3000",
            timeout=15,
            headers={
                "Authorization": f"Bearer {os.environ['TWENTY_INTEGRATION_API_KEY']}"
            },
        ) as twenty:
            people = await twenty_collection(twenty, "people")
            companies = await twenty_collection(twenty, "companies")
            print(
                f"campaign-orders: verification collection sizes people={len(people)} companies={len(companies)}",
                flush=True,
            )
            assert len(people) < 100 and len(companies) < 100
            people_by_id = {record["id"]: record for record in people}
            companies_by_id = {record["id"]: record for record in companies}
            assert len(people_by_id) == len(people)
            assert len(companies_by_id) == len(companies)
            for index, item in enumerate(orders):
                print(f"campaign-orders: verifying order {index + 1}/24", flush=True)
                rows = await connection.fetch(
                    "SELECT id FROM commitment WHERE public_reference=$1",
                    item["publicReference"],
                )
                assert len(rows) == 1
                command = UUID(item["commandId"])
                receipt = await connection.fetchrow(
                    "SELECT command_type, request_hash, result, completed_at FROM command_receipt WHERE idempotency_key=$1",
                    f"public.order:20000000-0000-4000-8000-000000000001:{command}",
                )
                assert receipt is not None
                assert receipt["command_type"] == "create_public_order_v1"
                assert receipt["completed_at"] is not None
                assert len(receipt["request_hash"]) == 64
                result = receipt["result"]
                result = json.loads(result) if isinstance(result, str) else result
                assert result["commitmentId"] == str(rows[0]["id"])
                if item["scenario"] == "mixed":
                    row = await connection.fetchrow(
                        "SELECT * FROM commitment WHERE id=$1", rows[0]["id"]
                    )
                    assert row is not None
                    assert row["action_id"] == UUID(
                        "20000000-0000-4000-8000-000000000001"
                    )
                    assert (
                        row["status"] == "review_ready"
                        and row["source"] == "public_form"
                    )
                    assert row["currency"] == "EUR" and row["total_minor"] == 11500
                    assert (
                        row["twenty_company_id"] is not None
                        and row["twenty_person_id"] is None
                    )
                    lines = await connection.fetch(
                        "SELECT unit_snapshot, quantity, pieces_per_unit_snapshot, unit_price_minor, line_total_minor FROM commitment_line WHERE commitment_id=$1 ORDER BY unit_snapshot",
                        row["id"],
                    )
                    assert [tuple(line) for line in lines] == [
                        ("box", 3, 24, 3600, 10800),
                        ("package", 2, None, 100, 200),
                        ("piece", 4, None, 100, 400),
                        ("sponsoring", 1, None, 100, 100),
                    ]
                    consent = await connection.fetchrow(
                        "SELECT normalized_recipient, text_version, purpose, evidence_kind FROM consent_record WHERE commitment_id=$1",
                        row["id"],
                    )
                    assert consent is not None
                    assert tuple(consent) == (
                        item["email"],
                        "public-order-golden-v1",
                        "public_order_fulfilment",
                        "notice_acknowledgement",
                    )
                else:
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
                assert audit["privacyAcknowledged"] is True
                assert audit["bindingOrderConfirmed"] is True
                person_id = row["twenty_person_id"] or UUID(audit["contactTwentyId"])
                person = people_by_id[str(person_id)]
                assert person["name"]["firstName"] == "Synthetic"
                assert person["name"]["lastName"] == item["label"]
                assert (
                    sum(
                        record["name"]["firstName"] == "Synthetic"
                        and record["name"]["lastName"] == item["label"]
                        for record in people
                    )
                    == 1
                ), "Retry duplicated a synthetic CRM person"
                if item["scenario"] == "person":
                    assert person.get("companyId") in {None, ""}
                else:
                    company = companies_by_id[str(row["twenty_company_id"])]
                    assert company["name"] == item["company"]
                    assert (
                        sum(record["name"] == item["company"] for record in companies)
                        == 1
                    ), "Retry duplicated a synthetic CRM company"
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
        "campaign-orders: 24 browser references including six mixed-unit orders verified in Core SQL, completed idempotency receipts, lines, consent/audit and real Twenty records; twelve native POST replays created no duplicate orders"
    )


if __name__ == "__main__":
    asyncio.run(main())
