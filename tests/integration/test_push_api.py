#!/usr/bin/env python3
"""Push notifications over HTTP and through the worker job, real PostgreSQL.

Runs as a contract script in the schema gate (``tools/schema/test.sh``) and,
with ``CORE_DATABASE_URL`` set, under pytest.

The push service of this proof is a real HTTP receiver on 127.0.0.1: it
checks the VAPID token of every request against the key LeonAid published
and decrypts the body with the private key of the subscription, as a browser
does (RFC 8291, RFC 8292). Delivery through the push services of Google,
Mozilla, Apple and Microsoft is not part of this proof.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import asyncpg
import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi import FastAPI

from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.push import AsyncpgPushRepository, enqueue_push
from leonaid.adapters.web_push import (
    VapidSigner,
    WebPushSender,
    generate_vapid_private_key,
)
from leonaid.application.push import (
    FollowUpPushJob,
    PushNotificationHandler,
    PushService,
    PushServiceUnavailable,
)
from leonaid.configuration import Settings
from leonaid.domain.outbox import ClaimedOutboxEvent, json_payload
from leonaid.domain.push import (
    PUSH_EVENT_TYPE,
    PUSH_THROTTLE,
    PushEndpointPolicy,
    PushKind,
)
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)
from leonaid.entrypoints.fastapi.platform import create_app

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.unit.web_push_receiver import (  # noqa: E402
    b64url_decode,
    decrypt_push_message,
    public_point,
)

BASE_URL = "https://push.leonaid.invalid"
SUBJECT = "mailto:push-proof@leonaid.invalid"
BERLIN = ZoneInfo("Europe/Berlin")


def settings() -> Settings:
    return Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-push-proof-secret-only-32-chars",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-push-proof-encryption-32-chars",
            "LEONAID_PUBLIC_BASE_URL": BASE_URL,
            "LEONAID_ALLOWED_ORIGINS": BASE_URL,
            "TWENTY_BASE_URL": "http://127.0.0.1:9",
            "TWENTY_HEALTH_URL": "http://127.0.0.1:9/health",
            "RUSTFS_HEALTH_URL": "http://127.0.0.1:9/health",
            "OBJECT_STORAGE_ENDPOINT_URL": "http://127.0.0.1:9",
            "OBJECT_STORAGE_BUCKET": "leonaid",
            "OBJECT_STORAGE_ACCESS_KEY": "synthetic-proof",
            "OBJECT_STORAGE_SECRET_KEY": "synthetic-proof",
        }
    )


def b64url(value: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


@dataclass
class Received:
    path: str
    headers: dict[str, str]
    body: bytes


class Receiver:
    """A push service on 127.0.0.1 that keeps what it receives."""

    def __init__(self) -> None:
        self.requests: list[Received] = []
        # Path → statuses to answer with, in order; then 201.
        self.answers: dict[str, list[int]] = {}
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server contract
                length = int(self.headers.get("Content-Length", "0"))
                receiver.requests.append(
                    Received(
                        self.path,
                        {key.lower(): value for key, value in self.headers.items()},
                        self.rfile.read(length),
                    )
                )
                queue = receiver.answers.get(self.path, [])
                self.send_response(queue.pop(0) if queue else 201)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def take(self) -> list[Received]:
        taken, self.requests = self.requests, []
        return taken


@dataclass
class Device:
    """One browser: its subscription keys, as PushManager.subscribe makes them."""

    receiver: Receiver
    name: str
    private_key: ec.EllipticCurvePrivateKey = field(
        default_factory=lambda: ec.generate_private_key(ec.SECP256R1())
    )
    auth: bytes = field(default_factory=lambda: os.urandom(16))

    @property
    def path(self) -> str:
        return f"/push/{self.name}"

    @property
    def endpoint(self) -> str:
        return self.receiver.origin + self.path

    def subscription(self) -> dict[str, object]:
        return {
            "endpoint": self.endpoint,
            "keys": {
                "p256dh": b64url(public_point(self.private_key)),
                "auth": b64url(self.auth),
            },
        }

    def read(self, request: Received, *, public_key: str) -> dict[str, Any]:
        """What the device shows: the checked and decrypted payload."""

        assert request.path == self.path
        assert request.headers["content-encoding"] == "aes128gcm"
        assert request.headers["ttl"] == "86400"
        token, key = (
            request.headers["authorization"].removeprefix("vapid t=").split(", k=")
        )
        # The token is signed by the key LeonAid hands to the browsers.
        assert key == public_key
        head, claims, signature = token.split(".")
        raw = b64url_decode(signature)
        ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), b64url_decode(key)
        ).verify(
            encode_dss_signature(
                int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
            ),
            f"{head}.{claims}".encode(),
            ec.ECDSA(hashes.SHA256()),
        )
        assert json.loads(b64url_decode(head)) == {"typ": "JWT", "alg": "ES256"}
        claim = json.loads(b64url_decode(claims))
        assert claim["aud"] == self.receiver.origin
        assert claim["sub"] == SUBJECT
        assert 0 < claim["exp"] - time.time() <= 24 * 3600
        payload = json.loads(
            decrypt_push_message(
                request.body, ua_private=self.private_key, auth_secret=self.auth
            )
        )
        # D-P2: a kind, a count and a path; nothing else ever.
        assert set(payload) == {"kind", "count", "path"}
        assert request.headers["topic"] == payload["kind"]
        return dict(payload)


class Fixture:
    """One action; an acquirer, a driver, an admin and an outsider."""

    def __init__(self) -> None:
        self.tag = f"push{uuid4().hex[:10]}"
        self.action = uuid4()
        self.users: dict[str, UUID] = {
            name: uuid4() for name in ("admin", "acquirer", "driver", "outsider")
        }
        self.tokens = {name: uuid4().hex + uuid4().hex for name in self.users}
        self.sessions = {name: uuid4() for name in self.users}
        self.window = uuid4()
        self.offering = uuid4()
        self.orders = [uuid4(), uuid4(), uuid4()]

    async def create(self, connection: asyncpg.Connection[Any]) -> None:
        for name, user_id in self.users.items():
            await connection.execute(
                "INSERT INTO user_account (id, email, display_name, status) "
                "VALUES ($1, $2, $3, 'active')",
                user_id,
                f"{name}.{self.tag}@leonaid.invalid",
                f"{name.title()} {self.tag}",
            )
            await self.session(connection, name, self.sessions[name], self.tokens[name])
        await connection.execute(
            """
            INSERT INTO charity_action (
                id, carrier_name, name, purpose, status, starts_on, ends_on,
                archive_slug
            )
            VALUES ($1, 'Push proof', $2, 'Proof', 'active',
                    '2026-01-01', '2099-12-31', $3)
            """,
            self.action,
            f"Aktion {self.tag}",
            f"push-proof-{self.action}",
        )
        await connection.execute(
            "INSERT INTO beneficiary "
            "(id, action_id, organization_name, public_description, sort_order) "
            "VALUES ($1, $2, 'Push proof beneficiary', 'Proof', 0)",
            uuid4(),
            self.action,
        )
        for capability in ("acquisition", "ordering", "delivery"):
            await connection.execute(
                "INSERT INTO charity_action_capability (action_id, capability) "
                "VALUES ($1, $2)",
                self.action,
                capability,
            )
        for name, role in (
            ("admin", "charity_admin"),
            ("acquirer", "acquirer"),
            ("driver", "driver"),
        ):
            await connection.execute(
                # Members since last month: the daily push is asked for at
                # 08:00, which may lie before this proof started.
                "INSERT INTO action_membership "
                "(id, action_id, user_id, role, active_from) "
                "VALUES ($1, $2, $3, $4, now() - interval '30 days')",
                uuid4(),
                self.action,
                self.users[name],
                role,
            )
        # Follow-ups of the acquirer: two due (overdue, today), one later,
        # one handed over, one without a date.
        today = datetime.now(BERLIN).replace(hour=12, minute=0, second=0, microsecond=0)
        for status, due_at in (
            ("open", today - timedelta(days=3)),
            ("contacted", today),
            ("open", today + timedelta(days=2)),
            ("handed_over", today - timedelta(days=1)),
            ("open", None),
        ):
            await connection.execute(
                """
                INSERT INTO acquisition_assignment (
                    id, action_id, twenty_company_id, acquirer_user_id,
                    status, next_action, due_at
                )
                VALUES ($1, $2, $3, $4, $5, 'Anrufen', $6)
                """,
                uuid4(),
                self.action,
                uuid4(),
                self.users["acquirer"],
                status,
                due_at,
            )
        await self._deliveries(connection)

    async def session(
        self,
        connection: asyncpg.Connection[Any],
        name: str,
        session_id: UUID,
        token: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at, last_seen_at,
                fresh_login_at, device_hint, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $5, 'Push proof', $5, $5)
            """,
            session_id,
            self.users[name],
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )

    async def _deliveries(self, connection: asyncpg.Connection[Any]) -> None:
        await connection.execute(
            "INSERT INTO action_delivery_configuration (action_id, enabled) "
            "VALUES ($1, true) "
            "ON CONFLICT (action_id) DO UPDATE SET enabled = true",
            self.action,
        )
        starts_at = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(
            days=3
        )
        await connection.execute(
            "INSERT INTO action_delivery_window (id, action_id, starts_at, ends_at) "
            "VALUES ($1, $2, $3, $4)",
            self.window,
            self.action,
            starts_at,
            starts_at + timedelta(hours=2),
        )
        await connection.execute(
            """
            INSERT INTO offering (
                id, action_id, code, name, status, unit,
                allowed_quantity_units, pieces_per_unit,
                unit_price_minor, currency
            )
            VALUES ($1, $2, $3, 'Krapfenbox', 'active', 'box',
                    ARRAY['box']::text[], 24, 3600, 'EUR')
            """,
            self.offering,
            self.action,
            f"box-{self.offering.hex[:12]}",
        )
        recipient = {
            "recipientName": f"Firma {self.tag}",
            "streetLine1": "Werkstraße 1",
            "postalCode": "86150",
            "city": "Augsburg",
            "countryCode": "DE",
            "email": None,
        }
        for order_id in self.orders:
            party = uuid4()
            await connection.execute(
                """
                INSERT INTO commitment (
                    id, action_id, twenty_company_id, source, status,
                    customer_snapshot, invoice_recipient_snapshot,
                    delivery_recipient_snapshot, delivery_window_id,
                    delivery_window_snapshot, currency, total_minor,
                    idempotency_key
                )
                VALUES ($1, $2, $3, 'admin', 'review_ready', $4::jsonb,
                        $5::jsonb, $5::jsonb, $6, $7::jsonb, 'EUR', 7200, $8)
                """,
                order_id,
                self.action,
                party,
                json.dumps(
                    {
                        "partyKind": "company",
                        "twentyId": str(party),
                        "displayName": f"Firma {self.tag}",
                        "email": None,
                    }
                ),
                json.dumps(recipient),
                self.window,
                json.dumps(
                    {
                        "windowId": str(self.window),
                        "startsAt": starts_at.isoformat(),
                        "endsAt": (starts_at + timedelta(hours=2)).isoformat(),
                    }
                ),
                f"push-proof:{order_id}",
            )
            await connection.execute(
                """
                INSERT INTO commitment_line (
                    id, commitment_id, offering_id, description_snapshot,
                    quantity, unit_snapshot, pieces_per_unit_snapshot,
                    unit_price_minor, line_total_minor
                )
                VALUES ($1, $2, $3, 'Krapfenbox', 2, 'box', 24, 3600, 7200)
                """,
                uuid4(),
                order_id,
                self.offering,
            )

    async def remove(self, connection: asyncpg.Connection[Any]) -> None:
        """Take away what would reach other proofs: jobs and devices."""

        users = list(self.users.values())
        await connection.execute(
            "DELETE FROM outbox_event WHERE event_type = $1 "
            "AND aggregate_id = ANY($2::uuid[])",
            PUSH_EVENT_TYPE,
            users,
        )
        for table in ("push_subscription", "push_preference", "push_dispatch"):
            await connection.execute(
                f"DELETE FROM {table} WHERE user_id = ANY($1::uuid[])", users
            )
        await connection.execute(
            "UPDATE user_session SET revoked_at = COALESCE(revoked_at, now()) "
            "WHERE user_id = ANY($1::uuid[])",
            users,
        )


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class Proof:
    def __init__(
        self,
        app: FastAPI,
        client: httpx.AsyncClient,
        connection: asyncpg.Connection[Any],
        pool: asyncpg.Pool[Any],
        data: Fixture,
        receiver: Receiver,
        signer: VapidSigner,
        push_client: httpx.AsyncClient,
    ) -> None:
        self.app = app
        self.client = client
        self.connection = connection
        self.pool = pool
        self.data = data
        self.receiver = receiver
        self.signer = signer
        self.clock = Clock()
        self.driver_phone = Device(receiver, "driver-phone")
        self.policy = PushEndpointPolicy(extra_origins=frozenset({receiver.origin}))
        self.repository = AsyncpgPushRepository(pool)
        self.flags = app.state.feature_flag_service
        self.handler = PushNotificationHandler(
            self.repository,
            WebPushSender(signer, push_client, self.policy),
            self.flags,
            clock=self.clock,
        )

    def headers(self, name: str, token: str | None = None) -> dict[str, str]:
        return {
            "Cookie": f"{SESSION_COOKIE_NAME}={token or self.data.tokens[name]}",
            "Origin": BASE_URL,
        }

    async def flag(self, enabled: bool) -> None:
        await self.connection.execute(
            "UPDATE feature_flag SET enabled = $1, revision = revision + 1 "
            "WHERE key = 'pwa.push' AND enabled <> $1",
            enabled,
        )

    def service(
        self, *, public_key: str | None, policy: PushEndpointPolicy
    ) -> PushService:
        return PushService(
            self.repository,
            self.flags,
            public_key=public_key,
            endpoints=policy,
            tasks_enabled=True,
        )

    async def configuration(self, name: str) -> dict[str, Any]:
        response = await self.client.get(
            "/api/v1/push/configuration", headers=self.headers(name)
        )
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        return dict(response.json())

    async def subscribe(
        self, name: str, device: Device, token: str | None = None
    ) -> str:
        response = await self.client.put(
            "/api/v1/push/subscriptions",
            headers={**self.headers(name, token), "User-Agent": "Push proof browser"},
            json=device.subscription(),
        )
        assert response.status_code == 200, response.text
        return str(response.json()["id"])

    async def prefer(self, name: str, **kinds: bool) -> httpx.Response:
        return await self.client.put(
            "/api/v1/push/preferences",
            headers=self.headers(name),
            json={
                "preferences": [
                    {"kind": kind, "enabled": enabled}
                    for kind, enabled in kinds.items()
                ]
            },
        )

    async def jobs(self, name: str) -> list[asyncpg.Record]:
        return list(
            await self.connection.fetch(
                "SELECT id, payload, available_at, idempotency_key "
                "FROM outbox_event WHERE event_type = $1 AND aggregate_id = $2 "
                "AND status = 'pending' ORDER BY available_at, created_at, id",
                PUSH_EVENT_TYPE,
                self.data.users[name],
            )
        )

    async def run(self, job: asyncpg.Record, *, done: bool = True) -> None:
        """Run one job as the worker does, then mark it completed."""

        await self.handler.handle(
            ClaimedOutboxEvent(
                id=job["id"],
                aggregate_type="user_account",
                aggregate_id=UUID(str(json_payload(job["payload"])["userId"])),
                event_type=PUSH_EVENT_TYPE,
                idempotency_key=str(job["idempotency_key"]),
                payload=json_payload(job["payload"]),
                attempts=1,
                claim_token=uuid4(),
                claimed_by="push-proof",
            )
        )
        if done:
            await self.connection.execute(
                "UPDATE outbox_event SET status = 'completed', completed_at = now() "
                "WHERE id = $1",
                job["id"],
            )

    async def run_all(self, name: str) -> int:
        """Run every job that is due at the proof's clock."""

        # Jobs of the real writers carry the real time; the proof's clock
        # only ever runs ahead of it.
        due = max(self.clock.now, datetime.now(timezone.utc))
        ran = 0
        for job in await self.jobs(name):
            if job["available_at"] <= due:
                await self.run(job)
                ran += 1
        return ran

    async def devices(self, name: str) -> list[asyncpg.Record]:
        return list(
            await self.connection.fetch(
                "SELECT id, endpoint, session_id, user_agent, last_success_at, "
                "failure_count FROM push_subscription WHERE user_id = $1 "
                "ORDER BY created_at, id",
                self.data.users[name],
            )
        )

    async def audits(self, event_type: str, name: str) -> list[dict[str, Any]]:
        rows = await self.connection.fetch(
            "SELECT payload FROM audit_event WHERE event_type = $1 "
            "AND actor_user_id = $2 ORDER BY occurred_at, id",
            event_type,
            self.data.users[name],
        )
        return [dict(json_payload(row["payload"])) for row in rows]

    # -- the proofs -------------------------------------------------------

    async def switched_off_and_unconfigured(self) -> None:
        await self.flag(False)
        for method, path, body in (
            ("GET", "/api/v1/push/configuration", None),
            ("PUT", "/api/v1/push/subscriptions", Device(self.receiver, "x")),
            ("POST", "/api/v1/push/test", None),
        ):
            response = await self.client.request(
                method,
                path,
                headers=self.headers("acquirer"),
                json=(
                    body.subscription()
                    if isinstance(body, Device)
                    else {"subscriptionId": str(uuid4())}
                    if method == "POST"
                    else None
                ),
            )
            assert response.status_code == 404, (path, response.text)
            assert response.json()["error"]["code"] == "feature_flag_disabled"
        assert (await self.client.get("/api/v1/push/configuration")).status_code == 401

        await self.flag(True)
        # Without a VAPID key: the page can say so, nothing can be switched on.
        self.app.state.push_service = self.service(public_key=None, policy=self.policy)
        configuration = await self.configuration("acquirer")
        assert configuration["configured"] is False
        assert configuration["publicKey"] is None
        refused = await self.client.put(
            "/api/v1/push/subscriptions",
            headers=self.headers("acquirer"),
            json=Device(self.receiver, "x").subscription(),
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "push_not_configured"
        assert await self.devices("acquirer") == []

    async def kinds_follow_the_roles(self) -> None:
        def kinds(configuration: dict[str, Any]) -> list[str]:
            return [item["kind"] for item in configuration["kinds"]]

        acquirer = await self.configuration("acquirer")
        assert acquirer["configured"] is True
        assert acquirer["publicKey"] == self.signer.public_key
        assert kinds(acquirer) == ["follow_ups", "feed", "tasks"]
        # Every kind is off until the member switches it on (D-P3).
        assert all(item["enabled"] is False for item in acquirer["kinds"])
        assert kinds(await self.configuration("driver")) == ["tasks", "delivery"]
        assert kinds(await self.configuration("admin")) == ["feed", "tasks"]
        assert kinds(await self.configuration("outsider")) == ["tasks"]
        refused = await self.prefer("outsider", delivery=True)
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "push_kind_unavailable"
        unknown = await self.client.put(
            "/api/v1/push/preferences",
            headers=self.headers("outsider"),
            json={"preferences": [{"kind": "orders", "enabled": True}]},
        )
        assert unknown.status_code == 422

    async def only_known_push_services(self, phone: Device) -> None:
        # The composition of the product knows no local receiver.
        default = self.app.state.push_service
        self.app.state.push_service = self.service(
            public_key=self.signer.public_key, policy=PushEndpointPolicy()
        )
        for subscription in (
            phone.subscription(),
            {**phone.subscription(), "endpoint": "https://core-postgres:5432/x"},
            {**phone.subscription(), "endpoint": "https://attacker.example/push"},
        ):
            refused = await self.client.put(
                "/api/v1/push/subscriptions",
                headers=self.headers("acquirer"),
                json=subscription,
            )
            assert refused.status_code == 409, refused.text
            assert refused.json()["error"]["code"] == "push_endpoint_not_allowed"
        self.app.state.push_service = default
        for keys in (
            {"p256dh": b64url(bytes(65)), "auth": b64url(phone.auth)},
            {
                "p256dh": b64url(public_point(phone.private_key)),
                "auth": b64url(bytes(8)),
            },
        ):
            refused = await self.client.put(
                "/api/v1/push/subscriptions",
                headers=self.headers("acquirer"),
                json={"endpoint": phone.endpoint, "keys": keys},
            )
            assert refused.status_code == 409, refused.text
            assert refused.json()["error"]["code"] == "push_subscription_keys_invalid"
        assert await self.devices("acquirer") == []
        assert self.receiver.take() == []

    async def subscribe_and_test_push(self, phone: Device) -> str:
        subscription_id = await self.subscribe("acquirer", phone)
        # The same browser subscription again: the same row.
        assert await self.subscribe("acquirer", phone) == subscription_id
        (row,) = await self.devices("acquirer")
        assert str(row["id"]) == subscription_id
        assert row["session_id"] == self.data.sessions["acquirer"]
        assert row["user_agent"] == "Push proof browser"
        assert await self.audits("push.subscription.created", "acquirer") == [{}]

        # Another member cannot push to or remove this device.
        for response in (
            await self.client.post(
                "/api/v1/push/test",
                headers=self.headers("driver"),
                json={"subscriptionId": subscription_id},
            ),
            await self.client.delete(
                f"/api/v1/push/subscriptions/{subscription_id}",
                headers=self.headers("driver"),
            ),
        ):
            assert response.status_code == 404, response.text
            assert response.json()["error"]["code"] == "push_subscription_not_found"

        queued = await self.client.post(
            "/api/v1/push/test",
            headers=self.headers("acquirer"),
            json={"subscriptionId": subscription_id},
        )
        assert queued.status_code == 202, queued.text
        assert queued.json() == {"status": "queued"}
        assert self.receiver.take() == []
        assert await self.run_all("acquirer") == 1
        (request,) = self.receiver.take()
        assert phone.read(request, public_key=self.signer.public_key) == {
            "kind": "test",
            "count": 1,
            "path": "/app/notifications",
        }
        (row,) = await self.devices("acquirer")
        assert row["last_success_at"] == self.clock.now
        assert row["failure_count"] == 0
        return subscription_id

    async def preferences_are_recorded(self) -> None:
        response = await self.prefer("acquirer", follow_ups=True, feed=True)
        assert response.status_code == 200, response.text
        assert response.json()["kinds"] == [
            {"kind": "follow_ups", "enabled": True},
            {"kind": "feed", "enabled": True},
            {"kind": "tasks", "enabled": False},
        ]
        # Saying the same again changes and records nothing.
        assert (await self.prefer("acquirer", feed=True)).status_code == 200
        assert await self.audits("push.preferences.changed", "acquirer") == [
            {"kinds": {"feed": True, "follow_ups": True}}
        ]

    async def order_arrives(self) -> None:
        """A new public order in "Neues" for the acquirer and the admin.

        The writer of the entry asks for the push in its transaction with
        this call; ``tools/public_orders/contract.py`` proves that writer
        with a real order.
        """

        async with self.pool.acquire() as connection, connection.transaction():
            await enqueue_push(
                connection,
                user_ids=[self.data.users["acquirer"], self.data.users["admin"]],
                kind=PushKind.FEED,
                occurred_at=datetime.now(timezone.utc),
            )

    async def feed_and_the_15_minutes(self, phone: Device) -> None:
        key = self.signer.public_key
        await self.order_arrives()
        # Only the acquirer asked for "Neues"; the admin gets no job at all.
        assert len(await self.jobs("acquirer")) == 1
        assert await self.jobs("admin") == []
        assert await self.run_all("acquirer") == 1
        (first,) = self.receiver.take()
        assert phone.read(first, public_key=key) == {
            "kind": "feed",
            "count": 1,
            "path": "/app/activities",
        }
        sent_at = self.clock.now

        # Three more entries in the next minutes: nothing is pushed, one
        # job is set for the end of the 15 minutes.
        for minutes in (1, 5, 9):
            self.clock.now = sent_at + timedelta(minutes=minutes)
            await self.order_arrives()
            assert await self.run_all("acquirer") == 1
        assert self.receiver.take() == []
        (flush,) = await self.jobs("acquirer")
        assert flush["available_at"] == sent_at + PUSH_THROTTLE
        assert json_payload(flush["payload"])["count"] == 0
        self.clock.now = sent_at + PUSH_THROTTLE
        assert await self.run_all("acquirer") == 1
        (merged,) = self.receiver.take()
        assert phone.read(merged, public_key=key) == {
            "kind": "feed",
            "count": 3,
            "path": "/app/activities",
        }
        assert await self.jobs("acquirer") == []

    async def gone_and_failing_devices(self, phone: Device) -> None:
        key = self.signer.public_key
        tablet = Device(self.receiver, "acquirer-tablet")
        laptop = Device(self.receiver, "acquirer-laptop")
        await self.subscribe("acquirer", tablet)
        await self.subscribe("acquirer", laptop)
        # The push service says the tablet's subscription ended (410) and
        # knows the laptop's no longer (404).
        self.receiver.answers = {tablet.path: [410], laptop.path: [404]}
        self.clock.advance(PUSH_THROTTLE)
        await self.order_arrives()
        assert await self.run_all("acquirer") == 1
        assert sorted(request.path for request in self.receiver.take()) == sorted(
            [phone.path, tablet.path, laptop.path]
        )
        assert [row["endpoint"] for row in await self.devices("acquirer")] == [
            phone.endpoint
        ]

        # The push service is down: the job fails and is run again; the
        # second run sends the same count, not a doubled one.
        self.receiver.answers = {phone.path: [503]}
        self.clock.advance(PUSH_THROTTLE)
        await self.order_arrives()
        (job,) = await self.jobs("acquirer")
        try:
            await self.run(job, done=False)
        except PushServiceUnavailable as error:
            assert error.code == "push_service_unavailable"
            assert error.retryable is True
        else:
            raise AssertionError("an unreachable push service must fail the job")
        (row,) = await self.devices("acquirer")
        assert row["failure_count"] == 1
        self.receiver.take()
        self.clock.advance(timedelta(seconds=5))
        await self.run(job)
        (again,) = self.receiver.take()
        assert phone.read(again, public_key=key)["count"] == 1
        (row,) = await self.devices("acquirer")
        assert row["failure_count"] == 0

    async def tasks(self) -> None:
        key = self.signer.public_key
        driver_phone = self.driver_phone
        await self.subscribe("driver", driver_phone)
        assert (await self.prefer("driver", tasks=True, delivery=True)).status_code == (
            200
        )
        listing = await self.client.post(
            "/api/v1/task-lists",
            headers=self.headers("admin"),
            json={
                "idempotencyKey": str(uuid4()),
                "title": f"Push {self.data.tag}",
                "actionId": str(self.data.action),
            },
        )
        assert listing.status_code == 200, listing.text
        list_id = listing.json()["id"]
        command = {
            "idempotencyKey": str(uuid4()),
            "title": "Flyer abholen",
            "assigneeUserId": str(self.data.users["driver"]),
        }
        created = await self.client.post(
            f"/api/v1/task-lists/{list_id}/tasks",
            headers=self.headers("admin"),
            json=command,
        )
        assert created.status_code == 200, created.text
        # The same command again is a replay: no second push.
        replay = await self.client.post(
            f"/api/v1/task-lists/{list_id}/tasks",
            headers=self.headers("admin"),
            json=command,
        )
        assert replay.status_code == 200, replay.text
        assert len(await self.jobs("driver")) == 1
        assert await self.run_all("driver") == 1
        (request,) = self.receiver.take()
        payload = driver_phone.read(request, public_key=key)
        assert payload == {"kind": "tasks", "count": 1, "path": "/app/tasks"}
        # Nothing of the task is in the push.
        assert "Flyer" not in json.dumps(payload)

        # A task someone gives to themselves, and a change that keeps the
        # assignee, announce nothing.
        task = created.json()
        own = await self.client.post(
            f"/api/v1/task-lists/{list_id}/tasks",
            headers=self.headers("admin"),
            json={
                "idempotencyKey": str(uuid4()),
                "title": "Eigene Aufgabe",
                "assigneeUserId": str(self.data.users["admin"]),
            },
        )
        assert own.status_code == 200, own.text
        renamed = await self.client.put(
            f"/api/v1/tasks/{task['id']}",
            headers=self.headers("admin"),
            json={
                "idempotencyKey": str(uuid4()),
                "expectedRevision": task["revision"],
                "title": "Flyer und Plakate abholen",
                "assigneeUserId": str(self.data.users["driver"]),
                "status": "open",
            },
        )
        assert renamed.status_code == 200, renamed.text
        assert await self.jobs("driver") == []
        assert await self.jobs("admin") == []

    async def deliveries(self) -> None:
        key = self.signer.public_key
        driver_phone = self.driver_phone
        assigned = await self.client.put(
            f"/api/v1/actions/{self.data.action}/delivery-board/drivers",
            headers=self.headers("admin"),
            json={
                "commitmentIds": [str(order) for order in self.data.orders],
                "driverUserId": str(self.data.users["driver"]),
            },
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json() == {"changed": 3}
        assert await self.run_all("driver") == 1
        (request,) = self.receiver.take()
        assert driver_phone.read(request, public_key=key) == {
            "kind": "delivery",
            "count": 3,
            "path": "/app/delivery",
        }
        # Assigning the same stops again changes nothing and pushes nothing.
        again = await self.client.put(
            f"/api/v1/actions/{self.data.action}/delivery-board/drivers",
            headers=self.headers("admin"),
            json={
                "commitmentIds": [str(order) for order in self.data.orders],
                "driverUserId": str(self.data.users["driver"]),
            },
        )
        assert again.json() == {"changed": 0}
        assert await self.jobs("driver") == []

    async def follow_ups(self, phone: Device) -> None:
        key = self.signer.public_key
        job = FollowUpPushJob(self.repository, self.flags, configured=True)
        today = datetime.now(BERLIN)
        early = today.replace(hour=7, minute=59, second=0, microsecond=0)
        morning = today.replace(hour=8, minute=0, second=0, microsecond=0)
        night = today.replace(hour=21, minute=0, second=0, microsecond=0)
        assert await job.run_once(now=early) == 0
        assert await job.run_once(now=night) == 0
        assert (
            await FollowUpPushJob(
                self.repository, self.flags, configured=False
            ).run_once(now=morning)
            == 0
        )
        # 08:00 club time: one job for the acquirer, none for members
        # without due follow-ups or without the switch.
        assert await job.run_once(now=morning) == 1
        # Every later run of the day asks nobody again.
        assert await job.run_once(now=morning + timedelta(minutes=5)) == 0
        (queued,) = await self.jobs("acquirer")
        assert json_payload(queued["payload"]) == {
            "userId": str(self.data.users["acquirer"]),
            "kind": "follow_ups",
            # Overdue and due today; not the later one, the handed-over one
            # or the one without a date.
            "count": 2,
        }
        self.clock.now = max(self.clock.now, morning.astimezone(timezone.utc))
        assert await self.run_all("acquirer") == 1
        (request,) = self.receiver.take()
        assert phone.read(request, public_key=key) == {
            "kind": "follow_ups",
            "count": 2,
            "path": "/app/activities?view=contacts",
        }

    async def switching_off(self, phone: Device) -> None:
        # A kind switched off after its job was written: the job sends
        # nothing; later events write no job.
        self.clock.advance(PUSH_THROTTLE)
        await self.order_arrives()
        (job,) = await self.jobs("acquirer")
        assert (await self.prefer("acquirer", feed=False)).status_code == 200
        await self.run(job)
        await self.order_arrives()
        assert await self.jobs("acquirer") == []
        assert self.receiver.take() == []
        assert (await self.audits("push.preferences.changed", "acquirer"))[-1] == {
            "kinds": {"feed": False}
        }
        assert (await self.prefer("acquirer", feed=True)).status_code == 200

        # The flag switched off: no jobs, and a job in hand sends nothing.
        self.clock.advance(PUSH_THROTTLE)
        await self.order_arrives()
        (job,) = await self.jobs("acquirer")
        await self.flag(False)
        await self.run(job)
        await self.order_arrives()
        assert await self.jobs("acquirer") == []
        assert self.receiver.take() == []
        await self.flag(True)

    async def sessions_end_devices(self, phone: Device, subscription_id: str) -> None:
        # An expired session: the device gets nothing and is cleaned up.
        second_token = uuid4().hex + uuid4().hex
        second_session = uuid4()
        await self.data.session(
            self.connection, "acquirer", second_session, second_token
        )
        tablet = Device(self.receiver, "acquirer-tablet-2")
        tablet_id = await self.subscribe("acquirer", tablet, second_token)
        await self.connection.execute(
            "UPDATE user_session SET expires_at = $2 WHERE id = $1",
            second_session,
            self.clock.now - timedelta(minutes=1),
        )
        self.clock.advance(PUSH_THROTTLE)
        await self.order_arrives()
        assert await self.run_all("acquirer") == 1
        assert [request.path for request in self.receiver.take()] == [phone.path]
        assert await self.repository.purge_ended(now=self.clock.now) == 1
        assert tablet_id not in {
            str(row["id"]) for row in await self.devices("acquirer")
        }

        # A member removes a device themselves, also while the flag is off.
        await self.flag(False)
        removed = await self.client.delete(
            f"/api/v1/push/subscriptions/{subscription_id}",
            headers=self.headers("acquirer"),
        )
        assert removed.status_code == 204, removed.text
        await self.flag(True)
        assert await self.devices("acquirer") == []
        assert (await self.audits("push.subscription.deleted", "acquirer"))[-1] == {
            "reason": "member"
        }
        again = await self.client.delete(
            f"/api/v1/push/subscriptions/{subscription_id}",
            headers=self.headers("acquirer"),
        )
        assert again.status_code == 404

        # Signing out on the device ends its subscription at once.
        await self.subscribe("acquirer", phone)
        assert len(await self.devices("acquirer")) == 1
        signed_out = await self.client.post(
            "/api/v1/auth/logout", headers=self.headers("acquirer")
        )
        assert signed_out.status_code == 200, signed_out.text
        assert await self.devices("acquirer") == []

        # So does an admin who ends all sessions of a member.
        assert len(await self.devices("driver")) == 1
        await self.connection.execute(
            "UPDATE user_session SET revoked_at = now() WHERE user_id = $1",
            self.data.users["driver"],
        )
        assert await self.devices("driver") == []
        # A job still in the queue for a member without devices just ends.
        self.clock.advance(PUSH_THROTTLE)
        await self.order_arrives()
        await self.run_all("acquirer")
        assert self.receiver.take() == []

    async def prove(self) -> None:
        phone = Device(self.receiver, "acquirer-phone")
        await self.switched_off_and_unconfigured()
        self.app.state.push_service = self.service(
            public_key=self.signer.public_key, policy=self.policy
        )
        await self.kinds_follow_the_roles()
        await self.only_known_push_services(phone)
        subscription_id = await self.subscribe_and_test_push(phone)
        await self.preferences_are_recorded()
        await self.feed_and_the_15_minutes(phone)
        await self.gone_and_failing_devices(phone)
        await self.tasks()
        await self.deliveries()
        await self.follow_ups(phone)
        await self.switching_off(phone)
        await self.sessions_end_devices(phone, subscription_id)


async def main() -> None:
    # The schema gate runs without the recovery volume; the survey erasure
    # archive is not part of this proof, so the app must not publish to it.
    os.environ.pop("LEONAID_SURVEY_ERASURE_ARCHIVE_DIR", None)
    private_key = generate_vapid_private_key()
    os.environ["LEONAID_VAPID_PRIVATE_KEY"] = private_key
    os.environ["LEONAID_VAPID_SUBJECT"] = SUBJECT
    os.environ.setdefault("LEONAID_PUBLIC_BASE_URL", BASE_URL)
    data = Fixture()
    receiver = Receiver()
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    pool = await create_pool(os.environ["CORE_DATABASE_URL"], maximum_size=3)
    was_enabled = await connection.fetchval(
        "SELECT enabled FROM feature_flag WHERE key = 'pwa.push'"
    )
    assert was_enabled is False, "0065 ships pwa.push switched off"
    try:
        await data.create(connection)
        app = create_app(settings())
        async with app.router.lifespan_context(app):
            # The product's own composition: the key of the environment.
            assert app.state.push_service._public_key == (  # noqa: SLF001
                VapidSigner(private_key, SUBJECT).public_key
            )
            async with (
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url=BASE_URL
                ) as client,
                httpx.AsyncClient(
                    timeout=10, follow_redirects=False, trust_env=False
                ) as push_client,
            ):
                await Proof(
                    app,
                    client,
                    connection,
                    pool,
                    data,
                    receiver,
                    VapidSigner(private_key, SUBJECT),
                    push_client,
                ).prove()
    finally:
        await connection.execute(
            "UPDATE feature_flag SET enabled = false, revision = revision + 1 "
            "WHERE key = 'pwa.push' AND enabled"
        )
        await data.remove(connection)
        await pool.close()
        await connection.close()
        receiver.close()
    print(
        "push-api: OK: subscriptions, preferences, the four kinds, the 15 "
        "minutes and Web Push to a decrypting receiver proven against PostgreSQL"
    )


def test_push_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
