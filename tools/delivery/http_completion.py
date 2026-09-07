"""HTTP completion through actual invoice issuance after the invoice UI gate."""

import asyncio
import os
from uuid import uuid4

import asyncpg
import httpx

from tools.invoices.contract import (
    ACTION_ID,
    DRAFT_COMMITMENT_ID,
    seed_sessions,
    session_headers,
    error_code,
)


async def main() -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        tokens = await seed_sessions(connection)
        headers = session_headers(tokens["klara_fresh"])
        root = f"/api/v1/actions/{ACTION_ID}"
        path = f"{root}/commitments/{DRAFT_COMMITMENT_ID}/delivery-completion"
        invoice_path = f"{root}/commitments/{DRAFT_COMMITMENT_ID}/invoice"
        async with httpx.AsyncClient(base_url="http://api:8000", timeout=30) as client:
            listing = await client.get(f"{root}/commitments", headers=headers)
            listing.raise_for_status()
            order = next(
                item["commitment"]
                for item in listing.json()["items"]
                if item["commitment"]["id"] == str(DRAFT_COMMITMENT_ID)
            )
            current = await client.get(f"{root}/delivery", headers=headers)
            current.raise_for_status()
            window = str(uuid4())
            config = {
                "enabled": True,
                "timezone": "Europe/Berlin",
                "revision": current.json()["revision"],
                "windows": [
                    *current.json()["windows"],
                    {
                        "id": window,
                        "deliveryOn": "2026-09-03",
                        "startsAt": "09:00",
                        "endsAt": "11:00",
                        "retired": True,
                    },
                ],
            }
            response = await client.put(
                f"{root}/delivery", headers=headers, json=config
            )
            response.raise_for_status()
            history = await client.get(
                f"{root}/delivery/completion-context", headers=headers
            )
            history.raise_for_status()
            assert "no-store" in history.headers["cache-control"]
            assert any(
                item["id"] == window for item in history.json()["historicalWindows"]
            )
            assert not any(
                item["id"] == window for item in history.json()["form"]["windows"]
            )
            for name in ("anna", "finn"):
                denied_context = await client.get(
                    f"{root}/delivery/completion-context",
                    headers=session_headers(tokens[name]),
                )
                assert denied_context.status_code == 403
            assert (
                await client.get(f"{root}/delivery/completion-context")
            ).status_code == 401
            blocked = await client.post(
                invoice_path,
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"serviceOn": "2026-09-03"},
            )
            assert (
                blocked.status_code == 409
                and error_code(blocked) == "invoice_delivery_incomplete"
            )
            address = {
                "recipientName": "Delivery recipient",
                "streetLine1": "Lieferweg 4",
                "postalCode": "86150",
                "city": "Augsburg",
                "countryCode": "DE",
            }
            billing = {
                **address,
                "recipientName": "Invoice recipient",
                "streetLine1": "Rechnungsweg 8",
                "email": "invoice@example.invalid",
            }
            body = {
                "expectedVersion": order["deliveryCompletionVersion"],
                "deliveryRecipient": {
                    **address,
                    "instructions": "Abteilung A\nStock 4",
                },
                "invoiceRecipient": billing,
                "windowId": window,
            }
            for name in ("anna", "finn"):
                denied = await client.post(
                    path,
                    headers={
                        **session_headers(tokens[name]),
                        "Idempotency-Key": str(uuid4()),
                    },
                    json=body,
                )
                assert denied.status_code == 403
            anonymous = await client.post(path, json=body)
            assert anonymous.status_code == 401
            unconfirmed = await client.post(
                path, headers={**headers, "Idempotency-Key": str(uuid4())}, json=body
            )
            assert (
                unconfirmed.status_code == 422
                and error_code(unconfirmed) == "delivery_window_unavailable"
            )
            body["confirmHistoricalDelivery"] = True
            key = str(uuid4())
            response = await client.post(
                path, headers={**headers, "Idempotency-Key": key}, json=body
            )
            response.raise_for_status()
            saved = response.json()
            assert response.headers["cache-control"] == "no-store"
            assert saved["status"] == "review_ready"
            assert saved["deliveryCompletionVersion"] != body["expectedVersion"]
            assert (
                saved["totalMinor"] == order["totalMinor"]
                and saved["lines"] == order["lines"]
            )
            assert saved["invoiceRecipient"] == billing
            assert saved["deliveryRecipient"]["instructions"] == "Abteilung A\nStock 4"
            replay = await client.post(
                path, headers={**headers, "Idempotency-Key": key}, json=body
            )
            replay.raise_for_status()
            assert replay.json()["replayed"]
            conflict = await client.post(
                path, headers={**headers, "Idempotency-Key": str(uuid4())}, json=body
            )
            assert (
                conflict.status_code == 409
                and error_code(conflict) == "delivery_completion_conflict"
            )
            invoice = await client.post(
                invoice_path,
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"serviceOn": "2026-09-03"},
            )
            invoice.raise_for_status()
            assert invoice.json()["recipient"] == billing
            assert invoice.json()["grossMinor"] == order["totalMinor"]
            body["expectedVersion"] = saved["deliveryCompletionVersion"]
            closed = await client.post(
                path, headers={**headers, "Idempotency-Key": str(uuid4())}, json=body
            )
            assert (
                closed.status_code == 409
                and error_code(closed) == "delivery_completion_closed"
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM invoice WHERE commitment_id = $1",
                    DRAFT_COMMITMENT_ID,
                )
                == 1
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM audit_event WHERE entity_id = $1 AND event_type = 'commitment_delivery_completed'",
                    DRAFT_COMMITMENT_ID,
                )
                == 1
            )
        print(
            "delivery-http: PASS: authenticated completion, no-store/version conflict, exact replay, actual invoice recipient and immutable invoiced order"
        )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
