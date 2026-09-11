"""Read-only verification of the local delivery demo before/after service restart."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx

from tools.public_orders.contract import twenty_collection


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


async def main() -> None:
    assert sys.argv[1:] in (["snapshot"], ["check"])
    state = json.loads(Path("/proof/public-orders-state.json").read_text())
    assert len(state["receipts"]) == 7
    assert {item["label"] for item in state["receipts"]} == {
        "anna-demo",
        "public-0-js",
        "public-0-native",
        "public-1-js",
        "public-1-native",
        "public-2-js",
        "public-2-native",
    }
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=5)
    try:
        windows = await connection.fetch(
            "SELECT * FROM action_delivery_window WHERE action_id=$1 ORDER BY id",
            UUID(state["actionId"]),
        )
        assert len([row for row in windows if not row["retired"]]) == 6
        rows = []
        for item in state["receipts"]:
            row = await connection.fetchrow(
                "SELECT * FROM commitment WHERE id=$1", UUID(item["orderId"])
            )
            assert row and row["action_id"] == UUID(state["actionId"])
            assert row["status"] == "review_ready"
            assert str(row["delivery_window_id"]) == item["windowId"]
            address = decoded(row["delivery_recipient_snapshot"])
            assert address["recipientName"] == "Musterwerk Warenannahme"
            assert address["streetLine1"] == "Lieferweg 22"
            assert (
                decoded(row["invoice_recipient_snapshot"])["streetLine1"]
                == "Rechnungsweg 11"
            )
            assert decoded(row["delivery_contact_snapshot"]) == {
                "name": "Test Warenannahme",
                "phone": "+49 123 / 456",
            }
            snapshot = decoded(row["delivery_window_snapshot"])
            window = next(
                value for value in windows if value["id"] == row["delivery_window_id"]
            )
            assert snapshot["timezone"] == "Europe/Berlin"
            assert datetime.fromisoformat(snapshot["startsAt"]) == window["starts_at"]
            assert datetime.fromisoformat(snapshot["endsAt"]) == window["ends_at"]
            if "commandId" in item:
                receipt = await connection.fetchrow(
                    "SELECT completed_at,result FROM command_receipt WHERE idempotency_key=$1",
                    f"public.order:{state['actionId']}:{item['commandId']}",
                )
                assert receipt and receipt["completed_at"]
                assert decoded(receipt["result"])["commitmentId"] == item["orderId"]
            rows.append(dict(row))
        configuration = await connection.fetchrow(
            "SELECT * FROM action_delivery_configuration WHERE action_id=$1",
            UUID(state["actionId"]),
        )
        assert configuration and configuration["enabled"]
        history = json.loads(Path("/proof/historical-order-state.json").read_text())
        historical_order = await connection.fetchrow(
            "SELECT * FROM commitment WHERE id=$1", UUID(history["orderId"])
        )
        historical_window = await connection.fetchrow(
            "SELECT * FROM action_delivery_window WHERE id=$1",
            UUID(history["windowId"]),
        )
        assert historical_order and historical_window and historical_window["retired"]
        assert str(historical_order["delivery_window_id"]) == history["windowId"]
        assert historical_order["delivery_window_snapshot"]
        async with httpx.AsyncClient(
            base_url="http://twenty-server:3000",
            timeout=15,
            headers={
                "Authorization": f"Bearer {os.environ['TWENTY_INTEGRATION_API_KEY']}"
            },
        ) as twenty:
            people = await twenty_collection(twenty, "people")
            assert len(people) < 100
            assert not any(
                " ".join(
                    [
                        person["name"]["firstName"] or "",
                        person["name"]["lastName"] or "",
                    ]
                ).strip()
                == "Test Warenannahme"
                for person in people
            ), "Delivery contact leaked into CRM master data"
        content = json.dumps(
            {
                "orders": rows,
                "windows": [dict(row) for row in windows],
                "configuration": dict(configuration),
                "historicalOrder": dict(historical_order),
                "historicalWindow": dict(historical_window),
            },
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(content.encode()).hexdigest()
        baseline = Path("/proof/delivery-db-baseline.json")
        if sys.argv[1] == "snapshot":
            baseline.write_text(json.dumps({"digest": digest}))
        else:
            assert json.loads(baseline.read_text())["digest"] == digest, (
                "Delivery data changed across restart"
            )
        print(
            f"delivery-demo {sys.argv[1]} PASS: seven accepted orders, six active December windows, separate invoice/address/contact, UTC snapshots, receipts, no separate CRM delivery contact"
        )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
