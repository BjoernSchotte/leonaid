"""Prove native recovery after a real, partially completed Twenty write."""

from __future__ import annotations

import asyncio
import json
import os
import re
from uuid import UUID
from urllib.parse import urlsplit

import asyncpg
import httpx

from tools.emdash_spike.native_order_deadline import ACTION, ROOT, signal, wait_file
from tools.emdash_spike.valid_order_ingress_proof import snapshot
from tools.public_orders.contract import assert_commitment


async def main() -> None:
    assert os.environ["LEONAID_ENV"] == "test"
    assert urlsplit(os.environ["CORE_DATABASE_URL"]).hostname == "core-postgres"
    assert urlsplit(os.environ["TWENTY_DATABASE_URL"]).hostname == "twenty-postgres"
    core = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=5)
    crm = await asyncpg.connect(os.environ["TWENTY_DATABASE_URL"], timeout=5)
    try:
        schemas = await crm.fetch(
            """SELECT p.table_schema FROM information_schema.tables p
            WHERE p.table_name='person' AND p.table_type='BASE TABLE'
            AND EXISTS (SELECT 1 FROM information_schema.tables c
                        WHERE c.table_schema=p.table_schema AND c.table_name='company'
                          AND c.table_type='BASE TABLE')"""
        )
        assert len(schemas) == 1, "Expected exactly one isolated Twenty workspace"
        schema = schemas[0]["table_schema"]
        assert re.fullmatch(r"[A-Za-z0-9_]+", schema)
        person_table = f'"{schema}"."person"'
        print(
            "partial-crm-order: one isolated workspace person table resolved",
            flush=True,
        )
        async with httpx.AsyncClient(
            base_url="http://twenty-server:3000",
            timeout=15,
            headers={
                "Authorization": f"Bearer {os.environ['TWENTY_INTEGRATION_API_KEY']}"
            },
        ) as twenty:
            for engine in ("chromium", "firefox", "webkit"):
                label = f"partial-{engine}-native-new-company"
                company_name = f"Synthetic {label} GmbH"
                before = await snapshot(core, twenty)
                blocker = await crm.fetchval("SELECT pg_backend_pid()")
                blocked = "SELECT count(*) FROM pg_stat_activity WHERE $1 = ANY(pg_blocking_pids(pid))"
                transaction = crm.transaction()
                await transaction.start()
                try:
                    # SHARE permits real reads/searches but blocks the contact
                    # INSERT after Twenty has already committed the company.
                    await crm.execute(f"LOCK TABLE {person_table} IN SHARE MODE")
                    signal(f"{label}-locked")
                    submitted = json.loads(await wait_file(f"{label}-submitted"))
                    command_id = str(UUID(submitted["commandId"]))
                    async with asyncio.timeout(180):
                        while not await crm.fetchval(blocked, blocker):
                            assert not (ROOT / f"{label}-timeout").exists(), (
                                "No actual CRM write blocker observed"
                            )
                            await asyncio.sleep(0.02)
                    await wait_file(f"{label}-timeout")
                    print(
                        f"partial-crm-order: {engine} actual Twenty SQL blocker observed and browser timeout received",
                        flush=True,
                    )
                    partial = await snapshot(core, twenty)
                    # Admission is deliberately persisted outside the cancelled
                    # order transaction. Allow exactly this command's one new
                    # attempt; every business/receipt/audit/outbox row is exact.
                    for index in (0, 1, 2, 3, 5, 6):
                        assert partial[0][index] == before[0][index], (
                            "Partial CRM failure changed Core business state"
                        )
                    old_attempts = json.loads(before[0][4])
                    attempts = json.loads(partial[0][4])
                    old_ids = {item["id"] for item in old_attempts}
                    added = [item for item in attempts if item["id"] not in old_ids]
                    assert len(added) == 1 and len(attempts) == len(old_attempts) + 1
                    assert [
                        item for item in attempts if item["id"] in old_ids
                    ] == old_attempts
                    assert added[0]["action_id"] == ACTION
                    assert (
                        added[0]["idempotency_key"]
                        == f"public.order:{ACTION}:{command_id}"
                    )
                    assert re.fullmatch(r"[0-9a-f]{64}", added[0]["fingerprint_hash"])
                    assert partial[1][1] == before[1][1], (
                        "Blocked contact was already visible"
                    )
                    old_companies = json.loads(before[1][0])
                    companies = json.loads(partial[1][0])
                    old_company_ids = {item["id"] for item in old_companies}
                    created = [
                        item for item in companies if item["id"] not in old_company_ids
                    ]
                    assert len(created) == 1 and created[0]["name"] == company_name
                    assert [
                        item for item in companies if item["id"] in old_company_ids
                    ] == old_companies
                    company_id = UUID(created[0]["id"])
                    print(
                        f"partial-crm-order: {engine} real blocked contact write; committed company and admission only; no Core order",
                        flush=True,
                    )
                finally:
                    await transaction.rollback()
                # No settling sleep: the abandoned CRM request may finish as
                # the same native command is retried. Final identity/count and
                # replay snapshots must cover either ordering without duplicates.
                signal(f"{label}-released")
                receipt = json.loads(await wait_file(f"{label}-accepted"))
                assert receipt["commandId"] == command_id
                rows = await core.fetch(
                    "SELECT id FROM commitment WHERE public_reference=$1",
                    receipt["reference"],
                )
                assert len(rows) == 1
                row = await assert_commitment(
                    core,
                    {
                        "commitmentId": str(rows[0]["id"]),
                        "publicReference": receipt["reference"],
                    },
                    expected_company_id=company_id,
                    expected_person=False,
                    expected_quantity=2,
                )
                command = await core.fetchrow(
                    "SELECT result, completed_at FROM command_receipt WHERE idempotency_key=$1",
                    f"public.order:{ACTION}:{command_id}",
                )
                assert command is not None and command["completed_at"] is not None
                assert json.loads(command["result"])["commitmentId"] == str(row["id"])
                after = await snapshot(core, twenty)
                companies = json.loads(after[1][0])
                people = json.loads(after[1][1])
                matched_company = [
                    item for item in companies if item["name"] == company_name
                ]
                assert len(matched_company) == 1 and matched_company[0]["id"] == str(
                    company_id
                )
                assert len(companies) == len(old_companies) + 1
                matched_people = [
                    item
                    for item in people
                    if item["name"]["firstName"] == "Synthetic"
                    and item["name"]["lastName"] == label
                ]
                assert len(matched_people) == 1
                assert matched_people[0]["companyId"] == str(company_id)
                assert len(people) == len(json.loads(before[1][1])) + 1
                audit = json.loads(
                    await core.fetchval(
                        "SELECT payload FROM audit_event WHERE entity_id=$1 AND event_type='public_order_created'",
                        row["id"],
                    )
                )
                assert audit["contactTwentyId"] == matched_people[0]["id"]
                assert (
                    audit["privacyAcknowledged"] is True
                    and audit["bindingOrderConfirmed"] is True
                )
                signal(f"{label}-replay-ready")
                await wait_file(f"{label}-replayed")
                assert await snapshot(core, twenty) == after, (
                    "Partial-write recovery replay mutated Core or CRM"
                )
                signal(f"{label}-verified")
                print(
                    f"partial-crm-order: {engine} same command reused original company, exactly one contact/order and unchanged exact replay",
                    flush=True,
                )
    finally:
        await crm.close()
        await core.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(f"partial-crm-order: failed; type={type(error).__name__}", flush=True)
        raise SystemExit(1) from None
