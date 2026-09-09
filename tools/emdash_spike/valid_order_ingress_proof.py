"""Prove real valid orders cannot mutate Core or Twenty through public ingress."""

from __future__ import annotations

import asyncio
import json
import os
import ssl
from uuid import uuid4

import asyncpg
import httpx

from tools.public_orders.contract import (
    assert_commitment,
    order_body,
    twenty_collection,
)


async def snapshot(
    connection: asyncpg.Connection, twenty: httpx.AsyncClient
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    tables = (
        "commitment",
        "commitment_line",
        "consent_record",
        "audit_event",
        "public_submission_attempt",
        "command_receipt",
        "outbox_event",
    )
    database = []
    for table in tables:
        # Fixed identifiers only. Retain snapshots in memory, never print PII.
        database.append(
            await connection.fetchval(
                f"SELECT COALESCE(jsonb_agg(value ORDER BY value::text), '[]'::jsonb) "
                f"FROM (SELECT to_jsonb(t) AS value FROM {table} t) records"
            )
        )
    crm = []
    for collection in ("companies", "people"):
        records = await twenty_collection(twenty, collection)
        assert len(records) < 100, "CRM proof must not silently truncate its snapshot"
        crm.append(
            json.dumps(sorted(records, key=lambda record: record["id"]), sort_keys=True)
        )
    return tuple(database), tuple(crm)


async def main() -> None:
    assert os.environ["LEONAID_ENV"] == "test"
    key = os.environ["LEONAID_ORDER_SUBMISSION_KEY"]
    assert len(key) == 64
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=5)
    try:
        async with (
            httpx.AsyncClient(base_url="http://api:8000", timeout=15) as core,
            httpx.AsyncClient(
                verify=ssl.create_default_context(cafile="/proof/root.crt"), timeout=5
            ) as edge,
            httpx.AsyncClient(
                base_url="http://twenty-server:3000",
                timeout=15,
                headers={
                    "Authorization": f"Bearer {os.environ['TWENTY_INTEGRATION_API_KEY']}"
                },
            ) as twenty,
        ):
            context = await core.get("/api/v1/public/actions/alias/krapfentaxi")
            assert context.status_code == 200
            published = context.json()
            assert published["submissionsAllowed"] is True
            body = order_body(
                token=published["action"]["orderForm"]["accessToken"],
                command=uuid4(),
                given_name="Synthetic",
                family_name="IngressControl",
                email="ingress-control@leonaid.invalid",
                company_name=None,
                quantity=1,
            )
            before = await snapshot(connection, twenty)
            attempts = 0
            for origin in ("http://proxy:8080", "https://proxy:8443"):
                for suffix in ("", "/"):
                    for method in (
                        "GET",
                        "HEAD",
                        "POST",
                        "PUT",
                        "PATCH",
                        "DELETE",
                        "OPTIONS",
                    ):
                        for credential in (None, "0" * 64, key):
                            headers = {
                                "X-Forwarded-For": "127.0.0.1",
                                "X-Forwarded-Host": "api:8000",
                                "X-Forwarded-Proto": "https",
                                "Forwarded": "for=127.0.0.1;host=api:8000;proto=https",
                                "X-EmDash-Request": "1",
                            }
                            if credential is not None:
                                headers["X-LeonAid-Order-Key"] = credential
                            response = await edge.request(
                                method,
                                f"{origin}/api/v1/public/actions/krapfentaxi/orders{suffix}",
                                headers=headers,
                                json=body,
                            )
                            assert response.status_code == 404
                            assert response.text == (
                                "" if method == "HEAD" else "Not Found"
                            )
                            assert response.headers["cache-control"] == "no-store"
                            assert "location" not in response.headers
                            assert "set-cookie" not in response.headers
                            attempts += 1
            assert await snapshot(connection, twenty) == before, (
                "Public ingress changed persistent state"
            )
            path = "/api/v1/public/actions/krapfentaxi/orders"
            denied = await core.post(path, json=body)
            assert denied.status_code == 404
            assert await snapshot(connection, twenty) == before, (
                "Unauthenticated internal call changed state"
            )
            # Positive control: exactly the payload denied above is actually
            # admissible when sent directly with the authorized caller key.
            accepted = await core.post(
                path,
                json=body,
                headers={
                    "X-LeonAid-Order-Key": key,
                    "User-Agent": "LeonAidIngressPositiveControl",
                },
            )
            assert accepted.status_code == 201
            await assert_commitment(
                connection,
                accepted.json(),
                expected_company_id=None,
                expected_person=True,
                expected_quantity=1,
            )
            assert (
                await edge.get("https://proxy:8443/api/v1/platform")
            ).status_code == 200
            print(
                f"valid-order-ingress: {attempts} valid-payload public requests denied, even with valid service key; seven Core tables and real Twenty unchanged; unauthorized internal denial and authorized positive control verified"
            )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
