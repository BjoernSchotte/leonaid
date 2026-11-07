#!/usr/bin/env python3
"""Queued acquisition orders over HTTP: full FastAPI app and real PostgreSQL.

Runs as a contract script in the schema gate (``tools/schema/test.sh``) and,
with ``CORE_DATABASE_URL`` set, under pytest. Proves the server part of the
PWA offline queue for orders (specs/pwa-offline-queue/PLAN.md §11.2, §11.3,
§11.5): the bounded ``capturedAt``, the price guard with its details, replays
and concurrent sends of one key, the receipt rollback on every refusal (so a
resolution may reuse the key) and the queued completion of a draft. Online
capture without ``capturedAt`` keeps taking the server price silently.

Activities need the CRM for party names and suppression; their queue rules
are proven against real Twenty in ``tools/activities/contract.py``.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import asyncpg
import httpx

from leonaid.configuration import Settings
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)
from leonaid.domain.commitments import CommitmentSource, CommitmentStatus
from leonaid.entrypoints.fastapi.platform import create_app
from leonaid.entrypoints.fastapi.routes import commitment_draft
from leonaid.entrypoints.fastapi.schemas import CreateCommitmentRequest

BASE_URL = "https://offline-capture.leonaid.invalid"


def settings() -> Settings:
    return Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-offline-proof-secret-only-32c",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-offline-proof-encryption-32",
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


class Fixture:
    """One action with delivery, an acquirer with one sponsor, two windows."""

    USERS = ("acquirer", "charity")

    def __init__(self) -> None:
        self.tag = f"oq{uuid4().hex[:10]}"
        self.action = uuid4()
        self.offering = uuid4()
        self.company = uuid4()
        self.open_window = uuid4()
        self.full_window = uuid4()
        self.users = {name: uuid4() for name in self.USERS}
        self.tokens = {name: uuid4().hex + uuid4().hex for name in self.USERS}
        start_day = date.today() + timedelta(days=30)
        self.window_starts_at = datetime(
            start_day.year, start_day.month, start_day.day, 7, tzinfo=timezone.utc
        )

    async def create(self, connection: asyncpg.Connection[Any]) -> None:
        now = datetime.now(timezone.utc)
        for name, user_id in self.users.items():
            await connection.execute(
                "INSERT INTO user_account (id, email, display_name, status) "
                "VALUES ($1, $2, $3, 'active')",
                user_id,
                f"{name}.{self.tag}@leonaid.invalid",
                f"{name.title()} {self.tag}",
            )
            await connection.execute(
                """
                INSERT INTO user_session (
                    id, user_id, token_digest, expires_at, last_seen_at,
                    fresh_login_at, device_hint, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $5, 'Offline proof', $5, $5)
                """,
                uuid4(),
                user_id,
                session_token_digest(self.tokens[name]),
                now + SESSION_LIFETIME,
                now,
            )
        await connection.execute(
            """
            INSERT INTO charity_action (
                id, carrier_name, name, purpose, status, starts_on, ends_on,
                archive_slug
            )
            VALUES ($1, 'Offline proof', $2, 'Proof', 'active',
                    '2026-01-01', '2099-12-31', $3)
            """,
            self.action,
            f"Aktion {self.tag}",
            f"offline-proof-{self.action}",
        )
        for capability in ("ordering", "acquisition", "delivery"):
            await connection.execute(
                "INSERT INTO charity_action_capability (action_id, capability) "
                "VALUES ($1, $2)",
                self.action,
                capability,
            )
        await connection.execute(
            """
            INSERT INTO action_delivery_configuration (action_id, enabled)
            VALUES ($1, true)
            ON CONFLICT (action_id) DO UPDATE SET enabled = true
            """,
            self.action,
        )
        for window, offset, full in (
            (self.open_window, 0, False),
            (self.full_window, 3, True),
        ):
            starts_at = self.window_starts_at + timedelta(hours=offset)
            await connection.execute(
                """
                INSERT INTO action_delivery_window (
                    id, action_id, starts_at, ends_at, fully_booked
                )
                VALUES ($1, $2, $3, $4, $5)
                """,
                window,
                self.action,
                starts_at,
                starts_at + timedelta(hours=2),
                full,
            )
        for name, role in (("acquirer", "acquirer"), ("charity", "charity_admin")):
            await connection.execute(
                "INSERT INTO action_membership (id, action_id, user_id, role) "
                "VALUES ($1, $2, $3, $4)",
                uuid4(),
                self.action,
                self.users[name],
                role,
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
        await connection.execute(
            """
            INSERT INTO acquisition_assignment (
                id, action_id, twenty_company_id, acquirer_user_id
            )
            VALUES ($1, $2, $3, $4)
            """,
            uuid4(),
            self.action,
            self.company,
            self.users["acquirer"],
        )


class Proof:
    def __init__(
        self,
        client: httpx.AsyncClient,
        data: Fixture,
        connection: asyncpg.Connection[Any],
    ) -> None:
        self.client = client
        self.data = data
        self.db = connection
        self.orders = f"/api/v1/actions/{data.action}/commitments"

    def key(self, name: str) -> str:
        return f"pwa-q:{self.data.tag}-{name}"

    async def post(
        self,
        path: str,
        body: dict[str, object],
        key: str | None,
        user: str = "acquirer",
    ) -> httpx.Response:
        headers = {
            "Cookie": f"{SESSION_COOKIE_NAME}={self.data.tokens[user]}",
            "Origin": BASE_URL,
        }
        if key is not None:
            headers["Idempotency-Key"] = key
        return await self.client.post(path, headers=headers, json=body)

    async def get(self, path: str, user: str = "charity") -> httpx.Response:
        return await self.client.get(
            path,
            headers={"Cookie": f"{SESSION_COOKIE_NAME}={self.data.tokens[user]}"},
        )

    def body(
        self,
        *,
        captured_at: datetime | str | None,
        quote: int | None = 3600,
        window: UUID | None = None,
        ready: bool = True,
        source: str = "acquisition",
        allow_full_window: bool = False,
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "source": source,
            "readyForReview": ready,
            "buyer": {
                "partyKind": "company",
                "twentyId": str(self.data.company),
                "displayName": f"Bäckerei {self.data.tag}",
                "email": None,
            },
            "invoiceRecipient": {
                "recipientName": f"Bäckerei {self.data.tag}",
                "streetLine1": "Marktplatz 3",
                "postalCode": "86150",
                "city": "Augsburg",
                "countryCode": "DE",
                "email": None,
            },
            "lines": [
                {
                    "offeringId": str(self.data.offering),
                    "quantity": 2,
                    "unit": "box",
                    **({"quotedUnitPriceMinor": quote} if quote is not None else {}),
                }
            ],
        }
        if ready:
            body["deliveryRecipient"] = {
                "recipientName": f"Bäckerei {self.data.tag}",
                "streetLine1": "Marktplatz 3",
                "postalCode": "86150",
                "city": "Augsburg",
                "countryCode": "DE",
            }
            body["deliveryWindowId"] = str(window or self.data.open_window)
        if allow_full_window:
            body["allowFullWindow"] = True
        if captured_at is not None:
            body["capturedAt"] = (
                captured_at if isinstance(captured_at, str) else captured_at.isoformat()
            )
        return body

    async def receipts(self, key: str) -> int:
        return int(
            await self.db.fetchval(
                "SELECT count(*) FROM command_receipt WHERE idempotency_key = $1",
                key,
            )
        )

    @staticmethod
    def error(response: httpx.Response) -> dict[str, Any]:
        payload = response.json()
        assert isinstance(payload, dict) and isinstance(payload.get("error"), dict)
        return dict(payload["error"])

    async def run(self) -> None:
        await self.queued_order_keeps_capture_time()
        await self.online_capture_keeps_server_price()
        await self.capture_time_bounds()
        await self.queued_order_needs_quotes_and_acquisition_source()
        await self.price_changed_meanwhile()
        await self.window_full_meanwhile()
        await self.concurrent_sends_create_one_order()
        await self.queued_completion_of_a_draft()
        await self.price_and_window_changed_meanwhile()
        await self.late_resend_replays()

    async def queued_order_keeps_capture_time(self) -> None:
        # Captured at 00:30 Berlin two days ago: the UTC day before.
        berlin = ZoneInfo("Europe/Berlin")
        two_days = (datetime.now(timezone.utc) - timedelta(days=2)).date()
        captured = datetime(
            two_days.year, two_days.month, two_days.day, 0, 30, tzinfo=berlin
        )
        key = self.key("queued")
        body = self.body(captured_at=captured)
        created = await self.post(self.orders, body, key)
        assert created.status_code == 201, created.text
        order = created.json()
        assert order["replayed"] is False
        assert datetime.fromisoformat(order["capturedAt"]) == captured
        assert order["totalMinor"] == 7200 and order["status"] == "review_ready"

        replay = await self.post(self.orders, body, key)
        assert replay.status_code == 201, replay.text
        assert replay.json()["id"] == order["id"] and replay.json()["replayed"]

        # The same key with another capture time is another capture: a bug.
        other = await self.post(
            self.orders,
            self.body(captured_at=captured + timedelta(minutes=1)),
            key,
        )
        assert other.status_code == 409, other.text
        assert self.error(other)["code"] == "idempotency_conflict"

        row = await self.db.fetchrow(
            "SELECT captured_at, created_at FROM commitment WHERE id = $1",
            UUID(order["id"]),
        )
        assert row["captured_at"] == captured
        # created_at stays the server time; it drives lists and invoices.
        assert datetime.now(timezone.utc) - row["created_at"] < timedelta(minutes=5)
        audit = await self.db.fetchval(
            "SELECT payload FROM audit_event WHERE entity_id = $1 "
            "AND event_type = 'commitment_created'",
            UUID(order["id"]),
        )
        payload = json.loads(audit) if isinstance(audit, str) else audit
        assert datetime.fromisoformat(payload["capturedAt"]) == captured
        # Canonical UTC, like the activity and completion audits (M7).
        assert payload["capturedAt"].endswith("+00:00"), payload
        assert order["capturedAt"].endswith(("Z", "+00:00")), order

        detail = await self.get(f"{self.orders}/{order['id']}")
        assert detail.status_code == 200, detail.text
        assert datetime.fromisoformat(detail.json()["capturedAt"]) == captured
        listing = await self.get(self.orders)
        assert listing.status_code == 200, listing.text
        record = next(
            item
            for item in listing.json()["items"]
            if item["commitment"]["id"] == order["id"]
        )
        assert datetime.fromisoformat(record["commitment"]["capturedAt"]) == captured
        assert datetime.fromisoformat(record["createdAt"]) == row["created_at"]

    async def online_capture_keeps_server_price(self) -> None:
        # Without capturedAt the client quote stays non-binding (risk R3).
        created = await self.post(
            self.orders, self.body(captured_at=None, quote=1), self.key("online")
        )
        assert created.status_code == 201, created.text
        assert created.json()["totalMinor"] == 7200
        assert created.json().get("capturedAt") is None

    async def capture_time_bounds(self) -> None:
        now = datetime.now(timezone.utc)
        for name, captured, code in (
            ("old", now - timedelta(days=14, minutes=5), "captured_at_out_of_range"),
            ("ahead", now + timedelta(minutes=10), "captured_at_out_of_range"),
            ("naive", "2026-11-04T09:12:30", "request_invalid"),
        ):
            key = self.key(f"bounds-{name}")
            refused = await self.post(self.orders, self.body(captured_at=captured), key)
            assert refused.status_code == 422, (name, refused.text)
            assert self.error(refused)["code"] == code, name
            assert await self.receipts(key) == 0, name
        inside = await self.post(
            self.orders,
            self.body(captured_at=now - timedelta(days=13, hours=23)),
            self.key("bounds-inside"),
        )
        assert inside.status_code == 201, inside.text

    async def queued_order_needs_quotes_and_acquisition_source(self) -> None:
        captured = datetime.now(timezone.utc) - timedelta(hours=1)
        unquoted = await self.post(
            self.orders,
            self.body(captured_at=captured, quote=None),
            self.key("unquoted"),
        )
        assert unquoted.status_code == 422, unquoted.text
        assert self.error(unquoted)["code"] == "commitment_client_quote_required"
        admin = await self.post(
            self.orders,
            self.body(captured_at=captured, source="admin"),
            self.key("admin"),
            user="charity",
        )
        assert admin.status_code == 422, admin.text
        assert self.error(admin)["code"] == "captured_at_source_invalid"

    async def price_changed_meanwhile(self) -> None:
        await self.db.execute(
            "UPDATE offering SET unit_price_minor = 3800 WHERE id = $1",
            self.data.offering,
        )
        try:
            captured = datetime.now(timezone.utc) - timedelta(hours=3)
            key = self.key("price")
            before = await self.db.fetchval(
                "SELECT count(*) FROM commitment WHERE action_id = $1",
                self.data.action,
            )
            refused = await self.post(
                self.orders, self.body(captured_at=captured, quote=3600), key
            )
            assert refused.status_code == 409, refused.text
            error = self.error(refused)
            assert error["code"] == "commitment_price_changed"
            assert error["details"] == {
                "lines": [
                    {
                        "offeringId": str(self.data.offering),
                        "quotedUnitPriceMinor": 3600,
                        "unitPriceMinor": 3800,
                        "lineTotalMinor": 7600,
                    }
                ],
                "totalMinor": 7600,
                "currency": "EUR",
            }
            # The refusal stored nothing: no order and no receipt (§11.5).
            assert await self.receipts(key) == 0
            assert (
                await self.db.fetchval(
                    "SELECT count(*) FROM commitment WHERE action_id = $1",
                    self.data.action,
                )
                == before
            )
            # "Neuen Preis übernehmen": the new quote is accepted. The PWA
            # sends it with a new key; the refused key would work as well.
            accepted = await self.post(
                self.orders, self.body(captured_at=captured, quote=3800), key
            )
            assert accepted.status_code == 201, accepted.text
            assert accepted.json()["totalMinor"] == 7600
            assert accepted.json()["lines"][0]["unitPriceMinor"] == 3800
        finally:
            await self.db.execute(
                "UPDATE offering SET unit_price_minor = 3600 WHERE id = $1",
                self.data.offering,
            )

    async def window_full_meanwhile(self) -> None:
        captured = datetime.now(timezone.utc) - timedelta(hours=2)
        key = self.key("full")
        refused = await self.post(
            self.orders,
            self.body(captured_at=captured, window=self.data.full_window),
            key,
        )
        assert refused.status_code == 409, refused.text
        assert self.error(refused)["code"] == "delivery_window_full"
        assert await self.receipts(key) == 0
        # "Trotzdem eintragen": same key, the confirmation is not content.
        confirmed = await self.post(
            self.orders,
            self.body(
                captured_at=captured,
                window=self.data.full_window,
                allow_full_window=True,
            ),
            key,
        )
        assert confirmed.status_code == 201, confirmed.text
        assert confirmed.json()["deliveryWindowId"] == str(self.data.full_window)

    async def concurrent_sends_create_one_order(self) -> None:
        key = self.key("race")
        body = self.body(captured_at=datetime.now(timezone.utc) - timedelta(hours=4))
        responses = await asyncio.gather(
            *(self.post(self.orders, body, key) for _ in range(6))
        )
        assert [response.status_code for response in responses] == [201] * 6, [
            response.text for response in responses
        ]
        assert len({response.json()["id"] for response in responses}) == 1
        assert sum(not response.json()["replayed"] for response in responses) == 1
        assert (
            await self.db.fetchval(
                "SELECT count(*) FROM commitment WHERE idempotency_key = $1", key
            )
            == 1
        )

    async def queued_completion_of_a_draft(self) -> None:
        draft = await self.post(
            self.orders,
            self.body(
                captured_at=datetime.now(timezone.utc) - timedelta(days=1),
                ready=False,
            ),
            self.key("draft"),
        )
        assert draft.status_code == 201, draft.text
        assert draft.json()["status"] == "draft"
        complete_path = f"{self.orders}/{draft.json()['id']}/complete"
        completion: dict[str, object] = {
            "deliveryRecipient": {
                "recipientName": f"Bäckerei {self.data.tag}",
                "streetLine1": "Marktplatz 3",
                "postalCode": "86150",
                "city": "Augsburg",
                "countryCode": "DE",
            },
            "deliveryWindowId": str(self.data.open_window),
        }
        late = await self.post(
            complete_path,
            {
                **completion,
                "capturedAt": (
                    datetime.now(timezone.utc) - timedelta(days=15)
                ).isoformat(),
            },
            self.key("complete-late"),
        )
        assert late.status_code == 422, late.text
        assert self.error(late)["code"] == "captured_at_out_of_range"
        captured = datetime.now(timezone.utc) - timedelta(minutes=30)
        body = {**completion, "capturedAt": captured.isoformat()}
        completed = await self.post(complete_path, body, self.key("complete"))
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "review_ready"
        replay = await self.post(complete_path, body, self.key("complete"))
        assert replay.status_code == 200, replay.text
        assert replay.json()["replayed"] is True
        payload = await self.db.fetchval(
            "SELECT payload FROM audit_event WHERE entity_id = $1 "
            "AND event_type = 'commitment_completed'",
            UUID(draft.json()["id"]),
        )
        payload = json.loads(payload) if isinstance(payload, str) else payload
        assert datetime.fromisoformat(payload["capturedAt"]) == captured

    async def price_and_window_changed_meanwhile(self) -> None:
        # Both changed: the window guard answers first, the confirmation
        # keeps the key, then the price guard asks; the new price is a new key.
        await self.db.execute(
            "UPDATE offering SET unit_price_minor = 3800 WHERE id = $1",
            self.data.offering,
        )
        try:
            captured = datetime.now(timezone.utc) - timedelta(hours=5)
            key = self.key("price-and-window")
            full = await self.post(
                self.orders,
                self.body(captured_at=captured, window=self.data.full_window),
                key,
            )
            assert full.status_code == 409, full.text
            assert self.error(full)["code"] == "delivery_window_full"
            confirmed = self.body(
                captured_at=captured,
                window=self.data.full_window,
                allow_full_window=True,
            )
            price = await self.post(self.orders, confirmed, key)
            assert price.status_code == 409, price.text
            assert self.error(price)["code"] == "commitment_price_changed"
            assert self.error(price)["details"]["totalMinor"] == 7600
            assert await self.receipts(key) == 0
            accepted = await self.post(
                self.orders,
                self.body(
                    captured_at=captured,
                    quote=3800,
                    window=self.data.full_window,
                    allow_full_window=True,
                ),
                self.key("price-and-window-accepted"),
            )
            assert accepted.status_code == 201, accepted.text
            assert accepted.json()["totalMinor"] == 7600
        finally:
            await self.db.execute(
                "UPDATE offering SET unit_price_minor = 3600 WHERE id = $1",
                self.data.offering,
            )

    async def late_resend_replays(self) -> None:
        # M2: a stored order replays after its 14-day window closed (lost
        # answer, retry on day 15). The receipt of a 20-day-old capture is
        # planted for an existing order; a new write would be refused.
        existing = await self.post(
            self.orders,
            self.body(captured_at=datetime.now(timezone.utc) - timedelta(hours=6)),
            self.key("late-source"),
        )
        assert existing.status_code == 201, existing.text
        old = self.body(captured_at=datetime.now(timezone.utc) - timedelta(days=20))
        draft = commitment_draft(CreateCommitmentRequest.model_validate(old))
        key = self.key("late")
        await self.db.execute(
            """
            INSERT INTO command_receipt (
                idempotency_key, command_type, request_hash, result, completed_at
            )
            VALUES ($1, 'create_commitment_v1', $2, $3::jsonb, CURRENT_TIMESTAMP)
            """,
            key,
            draft.fingerprint(
                action_id=self.data.action,
                source=CommitmentSource.ACQUISITION,
                status=CommitmentStatus.REVIEW_READY,
            ),
            json.dumps({"commitmentId": existing.json()["id"]}),
        )
        late = await self.post(self.orders, old, key)
        assert late.status_code == 201, late.text
        assert late.json()["replayed"] is True
        assert late.json()["id"] == existing.json()["id"]
        fresh = await self.post(self.orders, old, self.key("late-new"))
        assert fresh.status_code == 422, fresh.text
        assert self.error(fresh)["code"] == "captured_at_out_of_range"


async def main() -> None:
    os.environ.pop("LEONAID_SURVEY_ERASURE_ARCHIVE_DIR", None)
    data = Fixture()
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        await data.create(connection)
        app = create_app(settings())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE_URL
            ) as client:
                await Proof(client, data, connection).run()
    finally:
        await connection.close()
    print(
        "offline-capture-api: OK: capturedAt bounds, price guard, replay,"
        " concurrent key, receipt rollback and queued completion proven"
        " against PostgreSQL"
    )


def test_offline_capture_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
