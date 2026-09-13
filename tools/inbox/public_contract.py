#!/usr/bin/env python3
"""Public Inbox ingress, bounded requests and durable quotas on real PostgreSQL."""

import asyncio
import os
from uuid import uuid4
from collections.abc import AsyncIterator

import asyncpg
import httpx
from starlette.requests import Request

from leonaid.configuration import Settings
from leonaid.entrypoints.fastapi.platform import create_app
from leonaid.entrypoints.fastapi.security import request_fingerprint


async def main() -> None:
    settings = Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-http-proof-secret-only-32-characters",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-http-proof-encryption-32-characters",
            "LEONAID_PUBLIC_BASE_URL": "https://inbox.leonaid.invalid",
            "LEONAID_ALLOWED_ORIGINS": "https://inbox.leonaid.invalid",
            "TWENTY_BASE_URL": "http://127.0.0.1:9",
            "TWENTY_HEALTH_URL": "http://127.0.0.1:9/health",
            "RUSTFS_HEALTH_URL": "http://127.0.0.1:9/health",
            "OBJECT_STORAGE_ENDPOINT_URL": "http://127.0.0.1:9",
            "OBJECT_STORAGE_BUCKET": "leonaid",
            "OBJECT_STORAGE_ACCESS_KEY": "synthetic-proof",
            "OBJECT_STORAGE_SECRET_KEY": "synthetic-proof",
        }
    )
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    keys = [uuid4() for _ in range(4)]
    references = []
    fingerprints = []
    root = "/api/v1/public/inbox-cases"
    body = {
        "idempotencyKey": str(keys[0]),
        "subject": "Public proof",
        "message": "Synthetische Anfrage",
        "givenName": "Test",
        "familyName": "Person",
        "email": "test@example.org",
    }
    headers = {"Origin": "https://inbox.leonaid.invalid"}
    app = create_app(settings)
    try:
        async with app.router.lifespan_context(app):
            for address in ("192.0.2.10", "192.0.2.11", "192.0.2.12"):
                fingerprints.append(
                    request_fingerprint(
                        Request(
                            {"type": "http", "headers": [], "client": (address, 1234)}
                        ),
                        secret=app.state.security_secret,
                        trust_proxy_headers=False,
                        address_only=True,
                    )
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=("192.0.2.10", 1234)),
                base_url="https://inbox.leonaid.invalid",
            ) as client:
                response = await client.post(root, headers=headers, json=body)
                assert response.status_code == 201, response.text
                assert response.headers["cache-control"] == "no-store"
                assert set(response.json()) == {"reference"}
                references.append(response.json()["reference"])
                assert (
                    await client.post(root, headers=headers, json=body)
                ).json() == response.json()
                assert (
                    await client.post(
                        root,
                        headers=headers,
                        json={
                            **body,
                            "idempotencyKey": str(keys[1]),
                            "email": "broken",
                        },
                    )
                ).status_code == 422
                assert (
                    await client.post(
                        root,
                        headers=headers,
                        json={
                            **body,
                            "idempotencyKey": str(keys[1]),
                            "message": "Changed",
                        },
                    )
                ).status_code == 201
                # Four attempts consumed. Session/agent/forwarded-address changes
                # and the optional trailing slash must share the final slot.
                responses = await asyncio.gather(
                    *(
                        client.post(
                            root + suffix,
                            headers={
                                **headers,
                                "User-Agent": str(uuid4()),
                                "Cookie": f"__Host-leonaid_session={uuid4()}",
                                "X-Forwarded-For": str(uuid4()),
                            },
                            json={**body, "idempotencyKey": str(key)},
                            follow_redirects=True,
                        )
                        for suffix, key in (("", keys[2]), ("/", keys[3]))
                    )
                )
                assert sorted(item.status_code for item in responses) == [201, 429]
                limited = next(item for item in responses if item.status_code == 429)
                assert limited.headers["retry-after"] == "600"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=("192.0.2.11", 1234)),
                base_url="https://inbox.leonaid.invalid",
            ) as client:
                assert (
                    await client.post(
                        root, headers={"Origin": "https://evil.invalid"}, json=body
                    )
                ).status_code == 403
                assert (
                    await client.post(
                        root, headers=headers, json={**body, "actionId": str(uuid4())}
                    )
                ).status_code == 409
                missing = {
                    **body,
                    "idempotencyKey": str(uuid4()),
                    "actionId": str(uuid4()),
                }
                assert (
                    await client.post(root, headers=headers, json=missing)
                ).status_code == 404
                assert (
                    await client.get(root + "/" + references[0], headers=headers)
                ).status_code == 404
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=("192.0.2.12", 1234)),
                base_url="https://inbox.leonaid.invalid",
            ) as client:

                async def oversized() -> AsyncIterator[bytes]:
                    for _ in range(70):
                        yield b"x" * 1024

                assert (
                    await client.post(
                        root,
                        headers={**headers, "Content-Type": "application/json"},
                        content=oversized(),
                    )
                ).status_code == 413
            count = await conn.fetchval(
                "SELECT count(*) FROM command_receipt WHERE idempotency_key=ANY($1::text[])",
                [f"inbox.submit:{key}" for key in keys],
            )
            assert count == 3
            events = await conn.fetch(
                "SELECT o.event_type FROM outbox_event o JOIN inbox_case c ON c.contact_job_id=o.id JOIN audit_event a ON a.entity_id=c.id WHERE a.request_id=ANY($1::text[])",
                [f"inbox.submit:{key}" for key in keys],
            )
            assert len(events) == 3 and all(
                row["event_type"] == "inbox.contact_link.v1" for row in events
            )
        # Same persisted quota after a completely new application lifespan.
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=("192.0.2.10", 1234)),
                base_url="https://inbox.leonaid.invalid",
            ) as client:
                assert (
                    await client.post(root, headers=headers, json=body)
                ).status_code == 429
        print(
            "PASS public Inbox: receipt-only confirmation, replay, validation, real concurrent/address quota, restart persistence, origin rejection, hidden cases and streamed body limit"
        )
    finally:
        async with conn.transaction():
            case_ids = await conn.fetch(
                "SELECT entity_id FROM audit_event WHERE request_id=ANY($1::text[])",
                [f"inbox.submit:{key}" for key in keys],
            )
            ids = [row["entity_id"] for row in case_ids]
            await conn.execute("DELETE FROM inbox_case WHERE id=ANY($1::uuid[])", ids)
            await conn.execute(
                "DELETE FROM outbox_event WHERE aggregate_type='inbox_case' AND aggregate_id=ANY($1::uuid[])",
                ids,
            )
            await conn.execute(
                "DELETE FROM audit_event WHERE entity_id=ANY($1::uuid[])", ids
            )
            await conn.execute(
                "DELETE FROM command_receipt WHERE idempotency_key=ANY($1::text[])",
                [f"inbox.submit:{key}" for key in keys],
            )
            await conn.execute(
                "DELETE FROM security_rate_attempt WHERE scope='inbox.public.submit' AND fingerprint_hash=ANY($1::text[])",
                fingerprints,
            )
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
