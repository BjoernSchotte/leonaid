#!/usr/bin/env python3
"""Order cancellation over HTTP: full FastAPI app and real PostgreSQL.

Runs as a contract script in the schema gate (``tools/schema/test.sh``) and,
with ``CORE_DATABASE_URL`` set, under pytest. Proves who may cancel, the
allowed states, the invoice cases of ADR-0009, the optimistic version,
idempotent replays, concurrent commands, the delivery board and the
"Nachliefern" task, and that lists keep but no longer count cancelled orders.

Delivery windows cannot be deleted (protect_delivery_window), so the fixture
stays in the throwaway gate database; every row is scoped by fresh UUIDs.
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

from leonaid.adapters.postgres.order_mails import AsyncpgOrderMailReader
from leonaid.application.order_mails import (
    ORDER_CANCELLATION_MAIL,
    OrderMailHandler,
    OrderMailKind,
)
from leonaid.configuration import Settings
from leonaid.domain.invoices import InvoiceIssuerSnapshot, TaxTreatment
from leonaid.domain.legal_configuration import (
    EInvoiceDecision,
    LegalConfigurationDraft,
    LegalConfigurationVersion,
    RetentionSchedule,
)
from leonaid.domain.outbox import ClaimedOutboxEvent
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)
from leonaid.entrypoints.fastapi.platform import create_app
from leonaid.modules.tasks.delivery_follow_up import TaskDeliveryFollowUp

BASE_URL = "https://cancellation.leonaid.invalid"
REASON = "Sponsor hat die Bestellung zurückgezogen"
# What the buyer typed into the public form; it stays out of the mails.
PUBLIC_MESSAGE = "Bitte beim Pförtner abgeben, Tor-Code 2468."


def legal_version() -> LegalConfigurationVersion:
    """An active legal configuration as the worker reads it."""

    return LegalConfigurationVersion(
        id=uuid4(),
        version=1,
        configuration=LegalConfigurationDraft(
            issuer=InvoiceIssuerSnapshot(
                legal_name="Cancel proof Hilfswerk e.V.",
                street_line_1="Clubweg 1",
                postal_code="86150",
                city="Augsburg",
                country_code="DE",
                tax_identifier="103/999/99999",
                email="kontakt@cancel-proof.leonaid.invalid",
            ),
            bank_account_holder="Cancel proof Hilfswerk e.V.",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            tax_treatment=TaxTreatment.SMALL_BUSINESS,
            tax_rate_basis_points=0,
            tax_note="Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.",
            number_prefix="CP26-",
            number_width=4,
            payment_terms_days=14,
            public_order_legal_basis="Art. 6 Abs. 1 lit. b DSGVO (Vertrag).",
            public_order_notice_text=(
                "Wir verarbeiten Ihre Angaben nur zur Abwicklung Ihrer Bestellung."
            ),
            consent_text_version="cancel-proof-v1",
            privacy_contact_email="datenschutz@cancel-proof.leonaid.invalid",
            retention=RetentionSchedule(3650, 1095, 730, 1095, 2190),
            e_invoice_decision=EInvoiceDecision.NOT_REQUIRED,
            tax_evidence_id="TAX-PROOF-1",
            privacy_evidence_id="PRIVACY-PROOF-1",
            e_invoice_evidence_id="EINVOICE-PROOF-1",
            imprint_phone="+49 821 555000",
        ),
        created_by_user_id=uuid4(),
        created_by_display_name="Proof",
        created_at=datetime.now(timezone.utc),
    )


def settings() -> Settings:
    return Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-cancel-proof-secret-only-32-chars",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-cancel-proof-encryption-32-ch",
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
    """Two actions, accounts in every relevant role and one order per case."""

    USERS = (
        "admin",
        "charity",
        "acquirer",
        "finance",
        "finance_manager",
        "driver",
        "other_admin",
    )
    ORDERS = (
        "plain",
        "draft",
        "missed",
        "delivered",
        "invoiced",
        "paid",
        "sent",
        "race",
        "stale",
        "race_delivered",
        "race_closure",
        "race_issue",
    )
    # Pairs of concurrent commands per order: cancel vs delivery completion
    # (drafts booked into the window) and cancel vs invoice cancellation.
    PAIRS = 8
    DRAFTS = tuple(f"completion_{index}" for index in range(PAIRS))
    INVOICED = tuple(f"journal_{index}" for index in range(PAIRS))
    # Deliverable orders that overlapping bulk driver assignments share.
    ASSIGNED = tuple(f"assign_{index}" for index in range(6))
    # Orders from the public form: their buyer gets a cancellation notice.
    PUBLIC = ("public", "public_invoiced")

    def __init__(self) -> None:
        self.tag = f"oc{uuid4().hex[:10]}"
        self.action = uuid4()
        self.other_action = uuid4()
        self.window = uuid4()
        self.offering = uuid4()
        self.users = {name: uuid4() for name in self.USERS}
        self.tokens = {name: uuid4().hex + uuid4().hex for name in self.USERS}
        # The charity admin also holds a session whose login is not fresh.
        self.stale_token = uuid4().hex + uuid4().hex
        names = (
            *self.ORDERS,
            *self.DRAFTS,
            *self.INVOICED,
            *self.ASSIGNED,
            *self.PUBLIC,
        )
        self.orders = {name: uuid4() for name in names}
        self.invoices = {
            name: uuid4()
            for name in (
                "invoiced",
                "paid",
                "sent",
                "race_issue",
                "public_invoiced",
                *self.INVOICED,
            )
        }
        self.parties = {name: uuid4() for name in names}
        # A bookable window in the future: drafts complete into it.
        start_day = date.today() + timedelta(days=30)
        self.window_starts_at = datetime(
            start_day.year, start_day.month, start_day.day, 7, tzinfo=timezone.utc
        )
        self.board_day = self.window_starts_at.astimezone(
            ZoneInfo("Europe/Berlin")
        ).date()

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
            await self._session(connection, user_id, self.tokens[name], now, now)
        await self._session(
            connection,
            self.users["charity"],
            self.stale_token,
            now,
            now - timedelta(hours=2),
        )
        await connection.execute(
            "INSERT INTO user_global_role (user_id, role) VALUES ($1, 'system_admin')",
            self.users["admin"],
        )
        await connection.execute(
            "INSERT INTO user_global_role (user_id, role) "
            "VALUES ($1, 'finance_manager')",
            self.users["finance_manager"],
        )
        for action_id, name in (
            (self.action, "Alpha"),
            (self.other_action, "Beta"),
        ):
            await connection.execute(
                """
                INSERT INTO charity_action (
                    id, carrier_name, name, purpose, status, starts_on, ends_on,
                    archive_slug
                )
                VALUES ($1, 'Cancel proof', $2, 'Proof', 'active',
                        '2026-01-01', '2099-12-31', $3)
                """,
                action_id,
                f"Aktion {self.tag} {name}",
                f"cancel-proof-{action_id}",
            )
            for capability in ("ordering", "invoicing", "delivery"):
                await connection.execute(
                    "INSERT INTO charity_action_capability (action_id, capability) "
                    "VALUES ($1, $2)",
                    action_id,
                    capability,
                )
            await connection.execute(
                """
                INSERT INTO action_delivery_configuration (action_id, enabled)
                VALUES ($1, true)
                ON CONFLICT (action_id) DO UPDATE SET enabled = true
                """,
                action_id,
            )
        starts_at = self.window_starts_at
        await connection.execute(
            "INSERT INTO action_delivery_window (id, action_id, starts_at, ends_at) "
            "VALUES ($1, $2, $3, $4)",
            self.window,
            self.action,
            starts_at,
            starts_at + timedelta(hours=2),
        )
        for action_id, name, role in (
            (self.action, "charity", "charity_admin"),
            (self.action, "acquirer", "acquirer"),
            (self.action, "finance", "finance_reader"),
            (self.action, "driver", "driver"),
            (self.other_action, "other_admin", "charity_admin"),
        ):
            await connection.execute(
                "INSERT INTO action_membership (id, action_id, user_id, role) "
                "VALUES ($1, $2, $3, $4)",
                uuid4(),
                action_id,
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
        window_snapshot = {
            "windowId": str(self.window),
            "startsAt": starts_at.isoformat(),
            "endsAt": (starts_at + timedelta(hours=2)).isoformat(),
        }
        statuses = {
            "plain": "review_ready",
            "draft": "draft",
            "missed": "review_ready",
            "delivered": "review_ready",
            "invoiced": "invoiced",
            "paid": "invoiced",
            "sent": "invoiced",
            "race": "review_ready",
            "stale": "review_ready",
            "race_delivered": "review_ready",
            "race_closure": "review_ready",
            "race_issue": "review_ready",
            **{name: "review_ready" for name in self.ASSIGNED},
            **{name: "draft" for name in self.DRAFTS},
            **{name: "invoiced" for name in self.INVOICED},
            "public": "review_ready",
            "public_invoiced": "invoiced",
        }
        with_window = {
            "missed",
            "delivered",
            "race",
            "race_delivered",
            "race_closure",
            *self.DRAFTS,
            *self.ASSIGNED,
        }
        for name, order_id in self.orders.items():
            await self._order(
                connection,
                order_id,
                name,
                statuses[name],
                window_snapshot if name in with_window else None,
            )
        await connection.execute(
            """
            INSERT INTO commitment_delivery (
                commitment_id, action_id, state, state_changed_at,
                state_changed_by_user_id, missed_at_closure
            )
            VALUES ($1, $3, 'missed', $4, $5, true),
                   ($2, $3, 'delivered', $4, $5, false)
            """,
            self.orders["missed"],
            self.orders["delivered"],
            self.action,
            now,
            self.users["charity"],
        )
        # The open "Nachliefern" task of the missed order, created the way
        # the delivery board's closure creates it.
        async with connection.transaction():
            await TaskDeliveryFollowUp().sync(
                connection,
                action_id=self.action,
                commitment_id=self.orders["missed"],
                title=f"Nachliefern: Bestellung {self.tag}",
                description="Nicht geliefert im Fenster Mi 11.11.",
                needed=True,
                assignee_user_id=self.users["charity"],
                actor_user_id=self.users["charity"],
                request_id="cancel-proof",
                occurred_at=now,
            )
        for name, status in (
            ("invoiced", "issued"),
            ("paid", "issued"),
            ("sent", "sent"),
            ("public_invoiced", "issued"),
            *((name, "issued") for name in self.INVOICED),
        ):
            await self._invoice(connection, name, status)

    @staticmethod
    async def _session(
        connection: asyncpg.Connection[Any],
        user_id: UUID,
        token: str,
        now: datetime,
        fresh_login_at: datetime,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at, last_seen_at,
                fresh_login_at, device_hint, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, 'Cancel proof', $6, $5)
            """,
            uuid4(),
            user_id,
            session_token_digest(token),
            # Expiry is bound to creation, which is the login.
            fresh_login_at + SESSION_LIFETIME,
            now,
            fresh_login_at,
        )

    def recipient(self, name: str) -> dict[str, object]:
        return {
            "recipientName": f"Firma {self.tag} {name}",
            "streetLine1": "Werkstraße 1",
            "postalCode": "86150",
            "city": "Augsburg",
            "countryCode": "DE",
            "email": None,
        }

    async def _order(
        self,
        connection: asyncpg.Connection[Any],
        order_id: UUID,
        name: str,
        status: str,
        window_snapshot: dict[str, str] | None,
    ) -> None:
        recipient = self.recipient(name)
        public = name in self.PUBLIC
        await connection.execute(
            """
            INSERT INTO commitment (
                id, action_id, twenty_company_id, source, status,
                customer_snapshot, invoice_recipient_snapshot,
                delivery_recipient_snapshot, delivery_window_id,
                delivery_window_snapshot, currency, total_minor, idempotency_key,
                public_reference, message_snapshot
            )
            VALUES ($1, $2, $3, $10, $4, $5::jsonb, $6::jsonb, $6::jsonb,
                    $7, $8::jsonb, 'EUR', 7200, $9, $11, $12)
            """,
            order_id,
            self.action,
            self.parties[name],
            status,
            json.dumps(
                {
                    "partyKind": "company",
                    "twentyId": str(self.parties[name]),
                    "displayName": f"Firma {self.tag} {name}",
                    "email": self.buyer_email(name) if public else None,
                }
            ),
            json.dumps(recipient),
            self.window if window_snapshot else None,
            json.dumps(window_snapshot) if window_snapshot else None,
            f"cancel-proof:{order_id}",
            "public_form" if public else "admin",
            f"LA-{order_id.hex.upper()}" if public else None,
            PUBLIC_MESSAGE if public else None,
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

    def buyer_email(self, name: str) -> str:
        return f"{name.replace('_', '-')}.{self.tag}@buyer.leonaid.invalid"

    def invoice_number(self, name: str) -> str:
        return f"{self.tag.upper()}-{name.upper().replace('_', '-')}"

    async def _invoice(
        self, connection: asyncpg.Connection[Any], name: str, status: str
    ) -> None:
        await connection.execute(
            """
            INSERT INTO invoice (
                id, action_id, commitment_id, number, status, issued_at,
                service_on, due_on, currency, net_minor, tax_minor,
                gross_minor, issuer_snapshot, payment_details_snapshot,
                recipient_snapshot, line_snapshot, tax_treatment,
                tax_rate_basis_points, tax_note, payment_reference,
                approved_by_user_id, document_version, idempotency_key,
                issued_on
            )
            VALUES (
                $1, $2, $3, $4, $8, CURRENT_TIMESTAMP - interval '1 day',
                '2026-11-05', '2026-11-19', 'EUR', 7200, 0, 7200,
                '{"legalName":"Cancel proof e.V.","streetLine1":"Clubweg 1","postalCode":"86150","city":"Augsburg","countryCode":"DE","taxIdentifier":"103/999/99999","email":"finanzen@leonaid.invalid"}'::jsonb,
                '{"accountHolder":"Cancel proof e.V.","iban":"DE89370400440532013000","bic":"COBADEFFXXX"}'::jsonb,
                $5::jsonb,
                '[{"description":"Krapfenbox","quantity":2,"unit":"box","unitPriceGrossMinor":3600,"taxRateBasisPoints":0,"netMinor":7200,"taxMinor":0,"grossMinor":7200,"currency":"EUR"}]'::jsonb,
                'small_business', 0,
                'Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.',
                $4, $6, 1, $7, (CURRENT_TIMESTAMP - interval '1 day')::date
            )
            """,
            self.invoices[name],
            self.action,
            self.orders[name],
            self.invoice_number(name),
            json.dumps(self.recipient(name)),
            self.users["charity"],
            f"cancel-proof:{self.invoices[name]}",
            status,
        )


class Session:
    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        self.client = client
        self.headers = {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}

    async def get(self, path: str, **params: object) -> httpx.Response:
        return await self.client.get(path, headers=self.headers, params=params)

    async def post(
        self, path: str, body: dict[str, object], key: str | None
    ) -> httpx.Response:
        headers = dict(self.headers)
        headers["Origin"] = BASE_URL
        if key is not None:
            headers["Idempotency-Key"] = key
        return await self.client.post(path, headers=headers, json=body)


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
        self.sessions = {
            name: Session(client, token) for name, token in data.tokens.items()
        }
        self.stale = Session(client, data.stale_token)

    def path(self, name: str, action_id: UUID | None = None) -> str:
        action = action_id or self.data.action
        return (
            f"/api/v1/actions/{action}/commitments/{self.data.orders[name]}"
            "/cancellation"
        )

    async def listing(self, name: str = "charity") -> dict[str, Any]:
        response = await self.sessions[name].get(
            f"/api/v1/actions/{self.data.action}/commitments"
        )
        assert response.status_code == 200, response.text
        return dict(response.json())

    async def record(self, order: str) -> dict[str, Any]:
        order_id = str(self.data.orders[order])
        listing = await self.listing()
        return next(
            item for item in listing["items"] if item["commitment"]["id"] == order_id
        )

    async def version(self, order: str) -> str:
        return str(
            (await self.record(order))["commitment"]["deliveryCompletionVersion"]
        )

    async def cancel(
        self,
        order: str,
        *,
        session: Session | None = None,
        key: str | None = None,
        version: str | None = None,
        reason: str = REASON,
        note: str | None = None,
    ) -> httpx.Response:
        body: dict[str, object] = {
            "expectedVersion": version or await self.version(order),
            "reason": reason,
        }
        if note is not None:
            body["note"] = note
        return await (session or self.sessions["charity"]).post(
            self.path(order), body, key or f"cancel-proof:{uuid4()}"
        )

    async def count(self, sql: str, *arguments: object) -> int:
        return int(await self.db.fetchval(sql, *arguments))

    async def status(self, order: str) -> str:
        return str(
            await self.db.fetchval(
                "SELECT status FROM commitment WHERE id = $1", self.data.orders[order]
            )
        )

    @staticmethod
    def error(response: httpx.Response, status: int, code: str) -> None:
        assert response.status_code == status, (status, code, response.text)
        assert response.json()["error"]["code"] == code, response.text

    async def run(self) -> None:
        await self.authorization()
        await self.validation()
        await self.plain_cancellation_and_replay()
        await self.states()
        await self.invoice_cases()
        await self.buyer_notices()
        await self.board_and_follow_up()
        await self.concurrency()
        await self.board_races()
        await self.lock_order_races()
        await self.invoice_issue_race()
        await self.overlapping_assignments()
        await self.listing_counts()

    async def authorization(self) -> None:
        version = await self.version("plain")
        body = {"expectedVersion": version, "reason": REASON}
        anonymous = await self.client.post(
            self.path("plain"),
            headers={"Origin": BASE_URL, "Idempotency-Key": "cancel-proof:anon"},
            json=body,
        )
        assert anonymous.status_code == 401, anonymous.text
        for name in ("acquirer", "finance", "driver", "other_admin", "finance_manager"):
            response = await self.sessions[name].post(
                self.path("plain"), body, f"cancel-proof:{name}:{uuid4()}"
            )
            assert response.status_code == 403, (name, response.text)
        # The other action's admin learns nothing through its own action.
        foreign = await self.sessions["other_admin"].post(
            self.path("plain", self.data.other_action),
            body,
            f"cancel-proof:foreign:{uuid4()}",
        )
        self.error(foreign, 404, "commitment_not_found")
        assert await self.status("plain") == "review_ready"
        assert (
            await self.count(
                "SELECT count(*) FROM command_receipt WHERE idempotency_key LIKE $1",
                "cancel-proof:%",
            )
            == 0
        )

    async def validation(self) -> None:
        version = await self.version("plain")
        charity = self.sessions["charity"]
        for body in (
            {"expectedVersion": version, "reason": "zu kurz"},
            {"expectedVersion": version, "reason": "x" * 501},
            {"expectedVersion": "stale", "reason": REASON},
            {"expectedVersion": version, "reason": REASON, "note": "x" * 1001},
            {"expectedVersion": version},
        ):
            response = await charity.post(
                self.path("plain"), body, f"cancel-proof:{uuid4()}"
            )
            assert response.status_code == 422, (body, response.text)
        # Eight characters only after collapsing whitespace.
        spaced = await charity.post(
            self.path("plain"),
            {"expectedVersion": version, "reason": "ab    cd   "},
            f"cancel-proof:{uuid4()}",
        )
        self.error(spaced, 422, "commitment_cancellation_reason_too_short")
        missing_key = await charity.post(
            self.path("plain"), {"expectedVersion": version, "reason": REASON}, None
        )
        self.error(missing_key, 422, "commitment_idempotency_key_invalid")
        stale = await self.cancel("plain", version="0" * 64)
        self.error(stale, 409, "commitment_cancellation_conflict")
        assert await self.status("plain") == "review_ready"

    async def plain_cancellation_and_replay(self) -> None:
        key = f"cancel-proof:plain:{uuid4()}"
        version = await self.version("plain")
        note = "  Rückruf am Montag.\n  Kunde informiert.  "
        first = await self.cancel("plain", key=key, version=version, note=note)
        assert first.status_code == 201, first.text
        assert first.headers["cache-control"] == "no-store"
        result = first.json()
        assert result["replayed"] is False
        assert result["commitment"]["status"] == "cancelled"
        cancellation = result["cancellation"]
        assert cancellation["reason"] == REASON
        assert cancellation["note"] == "Rückruf am Montag.\n  Kunde informiert."
        assert cancellation["previousStatus"] == "review_ready"
        assert cancellation["requestedByDisplayName"] == f"Charity {self.data.tag}"
        assert cancellation["invoiceCancellationId"] is None
        # Same key, same content: the stored result, nothing new.
        again = await self.cancel("plain", key=key, version=version, note=note)
        assert again.status_code == 201, again.text
        assert again.json()["replayed"] is True
        assert again.json()["cancellation"]["id"] == cancellation["id"]
        # Same key, other content: refused.
        reused = await self.cancel(
            "plain", key=key, version=version, reason="Ein ganz anderer Grund"
        )
        self.error(reused, 409, "idempotency_conflict")
        # A new command on the cancelled order, even with its current version.
        twice = await self.cancel("plain")
        self.error(twice, 409, "commitment_already_cancelled")
        order_id = self.data.orders["plain"]
        assert (
            await self.count(
                "SELECT count(*) FROM commitment_cancellation WHERE commitment_id=$1",
                order_id,
            )
            == 1
        )
        audit = await self.db.fetch(
            "SELECT actor_user_id, payload FROM audit_event"
            " WHERE entity_id=$1 AND event_type='commitment_cancelled'",
            order_id,
        )
        assert len(audit) == 1
        assert audit[0]["actor_user_id"] == self.data.users["charity"]
        payload = json.loads(audit[0]["payload"])
        assert payload["previousStatus"] == "review_ready"
        assert payload["reason"] == REASON
        assert "note" not in payload and "Rückruf" not in json.dumps(payload)
        activity = await self.db.fetch(
            "SELECT twenty_company_id, payload FROM activity_event"
            " WHERE event_type='commitment_cancelled' AND payload->>'commitmentId'=$1",
            str(order_id),
        )
        assert len(activity) == 1
        assert activity[0]["twenty_company_id"] == self.data.parties["plain"]
        assert "Rückruf" not in str(activity[0]["payload"])

    async def notice_jobs(self, name: str) -> list[asyncpg.Record]:
        return list(
            await self.db.fetch(
                "SELECT id, idempotency_key, payload FROM outbox_event"
                " WHERE aggregate_id=$1 AND event_type=$2",
                self.data.orders[name],
                ORDER_CANCELLATION_MAIL,
            )
        )

    async def buyer_notices(self) -> None:
        # Members' orders got no confirmation, so no cancellation notice.
        for name in ("plain", "draft", "invoiced"):
            assert await self.notice_jobs(name) == [], name
        key = f"cancel-proof:public:{uuid4()}"
        version = await self.version("public")
        note = "Intern: Fahrer Bernd hat schon geladen."
        first = await self.cancel("public", key=key, version=version, note=note)
        assert first.status_code == 201, first.text
        replay = await self.cancel("public", key=key, version=version, note=note)
        assert replay.json()["replayed"] is True
        invoiced = await self.cancel("public_invoiced")
        assert invoiced.status_code == 201, invoiced.text
        sent: list[ClaimedOutboxEvent] = []

        class Sender:
            async def handle(self, event: ClaimedOutboxEvent) -> None:
                sent.append(event)

        class Legal:
            async def active_configuration(self) -> LegalConfigurationVersion:
                return legal_version()

        pool = await asyncpg.create_pool(
            os.environ["CORE_DATABASE_URL"], min_size=1, max_size=2
        )
        try:
            handler = OrderMailHandler(
                OrderMailKind.CANCELLATION,
                reader=AsyncpgOrderMailReader(pool),
                legal_configuration=Legal(),
                sender=Sender(),
            )
            for name in self.data.PUBLIC:
                jobs = await self.notice_jobs(name)
                # One notice per order, also after the replayed command.
                assert len(jobs) == 1, (name, jobs)
                order_id = self.data.orders[name]
                assert jobs[0]["idempotency_key"] == (
                    f"order-cancellation-mail:{order_id}"
                )
                payload = json.loads(jobs[0]["payload"])
                assert payload == {
                    "actionId": str(self.data.action),
                    "commitmentId": str(order_id),
                    # No alias in this fixture: the archive page.
                    "campaignUrl": (
                        f"{BASE_URL}/archive/cancel-proof-{self.data.action}"
                    ),
                    "privacyUrl": f"{BASE_URL}/datenschutz",
                    "imprintUrl": f"{BASE_URL}/impressum",
                }
                await handler.handle(
                    ClaimedOutboxEvent(
                        id=jobs[0]["id"],
                        aggregate_type="commitment",
                        aggregate_id=order_id,
                        event_type=ORDER_CANCELLATION_MAIL,
                        idempotency_key=jobs[0]["idempotency_key"],
                        payload=payload,
                        attempts=1,
                        claim_token=uuid4(),
                        claimed_by="cancel-proof",
                    )
                )
        finally:
            await pool.close()
        assert [event.payload["to"] for event in sent] == [
            self.data.buyer_email(name) for name in self.data.PUBLIC
        ]
        plain_text, invoiced_text = (str(event.payload["text"]) for event in sent)
        for text, name in ((plain_text, "public"), (invoiced_text, "public_invoiced")):
            reference = f"LA-{self.data.orders[name].hex.upper()}"
            assert f"Bestellnummer: {reference}" in text
            assert "storniert. Sie wird nicht geliefert." in text
            assert "- Krapfenbox: 2 Boxen (48 Stück) × 36,00 € = 72,00 €" in text
            assert "kontakt@cancel-proof.leonaid.invalid" in text
            # Reason, note and the buyer's own message stay internal.
            for forbidden in (REASON, "Fahrer Bernd", PUBLIC_MESSAGE, "Pförtner"):
                assert forbidden not in text, forbidden
        assert "Rechnung" not in plain_text.split("Bei Fragen")[0]
        assert (
            f"Die Rechnung {self.data.invoice_number('public_invoiced')} zu dieser "
            "Bestellung wurde ebenfalls storniert." in invoiced_text
        )

    async def states(self) -> None:
        delivered = await self.cancel("delivered")
        self.error(delivered, 409, "commitment_cancellation_delivered")
        assert "geliefert" in delivered.json()["error"]["message"]
        assert await self.status("delivered") == "review_ready"
        # A system admin manages every action; drafts may be cancelled.
        draft = await self.cancel("draft", session=self.sessions["admin"])
        assert draft.status_code == 201, draft.text
        assert draft.json()["cancellation"]["previousStatus"] == "draft"

    async def invoice_cases(self) -> None:
        invoice_id = self.data.invoices["invoiced"]
        before = await self.db.fetchval(
            "SELECT to_jsonb(invoice) - 'status' - 'updated_at' FROM invoice"
            " WHERE id=$1",
            invoice_id,
        )
        # Cancelling the invoice needs a fresh login; nothing is written.
        key = f"cancel-proof:invoiced:{uuid4()}"
        version = await self.version("invoiced")
        refused = await self.cancel(
            "invoiced", session=self.stale, key=key, version=version
        )
        self.error(refused, 401, "fresh_login_required")
        assert await self.status("invoiced") == "invoiced"
        assert (
            await self.count(
                "SELECT count(*) FROM command_receipt WHERE idempotency_key=$1", key
            )
            == 0
        )
        # After the fresh login the same command goes through.
        done = await self.cancel("invoiced", key=key, version=version)
        assert done.status_code == 201, done.text
        cancellation = done.json()["cancellation"]
        assert cancellation["invoiceNumber"] == self.data.invoice_number("invoiced")
        invoice = await self.db.fetchrow(
            "SELECT status, to_jsonb(invoice) - 'status' - 'updated_at' AS rest"
            " FROM invoice WHERE id=$1",
            invoice_id,
        )
        assert invoice["status"] == "cancelled"
        # ADR-0009: number, snapshots and document version stay unchanged.
        assert json.loads(invoice["rest"]) == json.loads(before)
        invoice_cancellation = await self.db.fetchrow(
            "SELECT id, reason_snapshot, original_status FROM invoice_cancellation"
            " WHERE invoice_id=$1",
            invoice_id,
        )
        assert invoice_cancellation["reason_snapshot"] == REASON
        assert invoice_cancellation["original_status"] == "issued"
        assert str(invoice_cancellation["id"]) == cancellation["invoiceCancellationId"]
        assert (
            await self.count(
                "SELECT count(*) FROM audit_event WHERE event_type='invoice_cancelled'"
                " AND payload->>'invoiceId'=$1",
                str(invoice_id),
            )
            == 1
        )
        # The invoice journal shows the cancellation with its reason.
        journal = await self.sessions["charity"].get(
            f"/api/v1/actions/{self.data.action}/invoices"
        )
        assert journal.status_code == 200, journal.text
        entry = next(
            item
            for item in journal.json()["items"]
            if item["invoice"]["id"] == str(invoice_id)
        )
        assert entry["invoice"]["status"] == "cancelled"
        assert entry["cancellation"]["reason"] == REASON
        # A sent invoice is cancelled the same way.
        sent = await self.cancel("sent")
        assert sent.status_code == 201, sent.text
        assert (
            await self.db.fetchval(
                "SELECT status FROM invoice WHERE id=$1", self.data.invoices["sent"]
            )
            == "cancelled"
        )
        # Active payment entries block the cancellation (ADR-0014): a partial
        # one already does, and so does the rest after one entry is reversed.
        # Once every entry is reversed the order can be cancelled; no refund
        # is invented.
        paid_invoice = self.data.invoices["paid"]
        payments = (
            f"/api/v1/actions/{self.data.action}/invoices/{paid_invoice}/payments"
        )
        entries = []
        for amount in (3000, 4200):
            payment = await self.sessions["charity"].post(
                payments,
                {
                    "amountMinor": amount,
                    "currency": "EUR",
                    "receivedOn": date.today().isoformat(),
                    "reference": self.data.invoice_number("paid"),
                },
                f"cancel-proof:payment:{uuid4()}",
            )
            assert payment.status_code == 201, payment.text
            entries.append(payment.json()["id"])
            record = await self.record("paid")
            assert record["invoice"]["paymentRecorded"] is True
            assert record["invoice"]["paidMinor"] == (3000 if amount == 3000 else 7200)
            blocked = await self.cancel("paid")
            self.error(blocked, 409, "commitment_cancellation_payment_recorded")
            assert "Zahlung zurückbuchen" in blocked.json()["error"]["message"]
        assert (
            await self.db.fetchval(
                "SELECT status FROM invoice WHERE id=$1", paid_invoice
            )
            == "paid"
        )
        for index, entry in enumerate(entries):
            reversal = await self.sessions["charity"].post(
                f"{payments}/{entry}/reversal",
                {"reason": "Doppelt erfasster Zahlungseingang"},
                f"cancel-proof:reversal:{uuid4()}",
            )
            assert reversal.status_code == 201, reversal.text
            record = await self.record("paid")
            if index == 0:
                assert record["invoice"]["paidMinor"] == 4200
                still = await self.cancel("paid")
                self.error(still, 409, "commitment_cancellation_payment_recorded")
        assert record["invoice"]["paidMinor"] == 0
        assert record["invoice"]["paymentRecorded"] is False
        assert await self.status("paid") == "invoiced"
        released = await self.cancel("paid")
        assert released.status_code == 201, released.text
        assert released.json()["cancellation"]["invoiceNumber"] == (
            self.data.invoice_number("paid")
        )
        assert (
            await self.db.fetchval(
                "SELECT status FROM invoice WHERE id=$1", paid_invoice
            )
            == "cancelled"
        )
        # The payment history stays: two entries, both reversed.
        assert (
            await self.count(
                "SELECT count(*) FROM payment_record AS p JOIN payment_reversal AS r"
                " ON r.payment_id = p.id WHERE p.invoice_id=$1",
                paid_invoice,
            )
            == 2
        )

    async def board_and_follow_up(self) -> None:
        board = await self.sessions["charity"].get(
            f"/api/v1/actions/{self.data.action}/delivery-board",
            day=self.data.board_day.isoformat(),
        )
        assert board.status_code == 200, board.text
        drops = {
            drop["commitmentId"]
            for window in board.json()["windows"]
            for drop in window["drops"]
        }
        assert str(self.data.orders["missed"]) in drops
        task_before = await self.db.fetchrow(
            "SELECT task.status, task.description FROM task_delivery_follow_up AS f"
            " JOIN task ON task.id = f.task_id WHERE f.commitment_id=$1",
            self.data.orders["missed"],
        )
        assert task_before["status"] == "open"
        response = await self.cancel("missed", note="Privat: Frau Muster, Tel. 0821")
        assert response.status_code == 201, response.text
        board = await self.sessions["charity"].get(
            f"/api/v1/actions/{self.data.action}/delivery-board",
            day=self.data.board_day.isoformat(),
        )
        drops = {
            drop["commitmentId"]
            for window in board.json()["windows"]
            for drop in window["drops"]
        }
        # Gone from the board at once; the delivered order stays.
        assert str(self.data.orders["missed"]) not in drops
        assert str(self.data.orders["delivered"]) in drops
        task = await self.db.fetchrow(
            "SELECT task.status, task.description FROM task_delivery_follow_up AS f"
            " JOIN task ON task.id = f.task_id WHERE f.commitment_id=$1",
            self.data.orders["missed"],
        )
        assert task["status"] == "done"
        assert task["description"].startswith(task_before["description"])
        assert "storniert" in task["description"]
        # No free text from the order in the task: it outlives an erasure.
        for private in (REASON, "Muster", "0821"):
            assert private not in task["description"], task["description"]
        assert (
            await self.count(
                "SELECT count(*) FROM audit_event"
                " WHERE event_type='tasks.delivery_follow_up_closed'"
                " AND payload->>'commitmentId'=$1",
                str(self.data.orders["missed"]),
            )
            == 1
        )
        # The board refuses state changes on it.
        state = await self.sessions["charity"].client.put(
            f"/api/v1/actions/{self.data.action}/commitments/"
            f"{self.data.orders['missed']}/delivery-state",
            headers={**self.sessions["charity"].headers, "Origin": BASE_URL},
            json={"delivered": True, "expectedRevision": 1},
        )
        assert state.status_code == 409, state.text

    async def concurrency(self) -> None:
        version = await self.version("race")
        responses = await asyncio.gather(
            *(
                self.cancel("race", key=f"cancel-proof:race:{index}", version=version)
                for index in range(4)
            )
        )
        codes = sorted(response.status_code for response in responses)
        assert codes == [201, 409, 409, 409], [r.text for r in responses]
        for response in responses:
            if response.status_code == 409:
                assert response.json()["error"]["code"] in {
                    "commitment_already_cancelled",
                    "commitment_cancellation_conflict",
                    "commitment_concurrent_retry",
                }, response.text
        assert (
            await self.count(
                "SELECT count(*) FROM commitment_cancellation WHERE commitment_id=$1",
                self.data.orders["race"],
            )
            == 1
        )
        # The same command sent twice at once runs once.
        key = f"cancel-proof:stale:{uuid4()}"
        version = await self.version("stale")
        pair = await asyncio.gather(
            self.cancel("stale", key=key, version=version),
            self.cancel("stale", key=key, version=version),
        )
        assert [response.status_code for response in pair] == [201, 201]
        assert sorted(response.json()["replayed"] for response in pair) == [
            False,
            True,
        ]
        assert (
            await self.count(
                "SELECT count(*) FROM audit_event WHERE entity_id=$1"
                " AND event_type='commitment_cancelled'",
                self.data.orders["stale"],
            )
            == 1
        )

    async def board_races(self) -> None:
        """A board command holding the window commits first; the cancel that
        waited for the window then sees what the board wrote."""

        async def board_then_cancel(order: str, board: Any) -> httpx.Response:
            version = await self.version(order)
            raw = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
            try:
                transaction = raw.transaction()
                await transaction.start()
                await raw.execute(
                    "SELECT id FROM action_delivery_window WHERE id=$1 FOR UPDATE",
                    self.data.window,
                )
                await board(raw)
                cancelling = asyncio.create_task(self.cancel(order, version=version))
                await asyncio.sleep(0.5)
                assert not cancelling.done(), "the cancel must wait for the window"
                await transaction.commit()
                return await asyncio.wait_for(cancelling, timeout=15)
            finally:
                await raw.close()

        delivered_id = self.data.orders["race_delivered"]

        async def tick_off(raw: asyncpg.Connection[Any]) -> None:
            # First state row of the drop, as the board's set_state writes it.
            await raw.execute(
                """
                INSERT INTO commitment_delivery (
                    commitment_id, action_id, state, state_changed_at,
                    state_changed_by_user_id
                )
                VALUES ($1, $2, 'delivered', now(), $3)
                """,
                delivered_id,
                self.data.action,
                self.data.users["charity"],
            )

        response = await board_then_cancel("race_delivered", tick_off)
        self.error(response, 409, "commitment_cancellation_delivered")
        assert await self.status("race_delivered") == "review_ready"

        closure_id = self.data.orders["race_closure"]

        async def close_window(raw: asyncpg.Connection[Any]) -> None:
            # The closure marks the drop missed and opens its task.
            await raw.execute(
                """
                INSERT INTO commitment_delivery (
                    commitment_id, action_id, state, state_changed_at,
                    state_changed_by_user_id, missed_at_closure
                )
                VALUES ($1, $2, 'missed', now(), $3, true)
                """,
                closure_id,
                self.data.action,
                self.data.users["charity"],
            )
            await TaskDeliveryFollowUp().sync(
                raw,
                action_id=self.data.action,
                commitment_id=closure_id,
                title=f"Nachliefern: Bestellung {self.data.tag} closure",
                description="Nicht geliefert.",
                needed=True,
                assignee_user_id=self.data.users["charity"],
                actor_user_id=self.data.users["charity"],
                request_id="cancel-proof",
                occurred_at=datetime.now(timezone.utc),
            )

        response = await board_then_cancel("race_closure", close_window)
        assert response.status_code == 201, response.text
        task = await self.db.fetchval(
            "SELECT task.status FROM task_delivery_follow_up AS f"
            " JOIN task ON task.id = f.task_id WHERE f.commitment_id=$1",
            closure_id,
        )
        assert task == "done", task

    async def lock_order_races(self) -> None:
        """Cancel against delivery completion and against the invoice
        journal's cancellation, all at once: no 500, one consistent result."""

        charity = self.sessions["charity"]
        recipient = {
            "recipientName": "Firma Proof",
            "streetLine1": "Werkstraße 1",
            "postalCode": "86150",
            "city": "Augsburg",
            "countryCode": "DE",
        }
        versions = {
            name: await self.version(name)
            for name in (*self.data.DRAFTS, *self.data.INVOICED)
        }

        async def complete(name: str) -> httpx.Response:
            return await charity.post(
                f"/api/v1/actions/{self.data.action}/commitments/"
                f"{self.data.orders[name]}/delivery-completion",
                {
                    "expectedVersion": versions[name],
                    "invoiceRecipient": {**recipient, "email": None},
                    "deliveryRecipient": recipient,
                    "deliveryWindowId": str(self.data.window),
                },
                f"cancel-proof:completion:{uuid4()}",
            )

        async def journal(name: str) -> httpx.Response:
            return await charity.post(
                f"/api/v1/actions/{self.data.action}/invoices/"
                f"{self.data.invoices[name]}/cancellation",
                {"reason": "Rechnung im Journal storniert"},
                f"cancel-proof:journal:{uuid4()}",
            )

        calls = []
        for name in self.data.DRAFTS:
            calls += [self.cancel(name, version=versions[name]), complete(name)]
        for name in self.data.INVOICED:
            calls += [self.cancel(name, version=versions[name]), journal(name)]
        responses = await asyncio.gather(*calls)
        errors = [r for r in responses if r.status_code >= 500]
        assert not errors, [r.text for r in errors]
        for index, name in enumerate(self.data.DRAFTS):
            cancel, completion = responses[2 * index], responses[2 * index + 1]
            # Exactly one wins; the other sees the changed order.
            assert sorted((cancel.status_code, completion.status_code)) in (
                [200, 409],
                [201, 409],
            ), (cancel.text, completion.text)
            expected = "cancelled" if cancel.status_code == 201 else "review_ready"
            assert await self.status(name) == expected
        offset = 2 * len(self.data.DRAFTS)
        for index, name in enumerate(self.data.INVOICED):
            cancel = responses[offset + 2 * index]
            invoice_cancel = responses[offset + 2 * index + 1]
            assert cancel.status_code == 201, cancel.text
            assert invoice_cancel.status_code in (201, 409), invoice_cancel.text
            assert await self.status(name) == "cancelled"
            invoice_id = self.data.invoices[name]
            assert (
                await self.db.fetchval(
                    "SELECT status FROM invoice WHERE id=$1", invoice_id
                )
                == "cancelled"
            )
            assert (
                await self.count(
                    "SELECT count(*) FROM invoice_cancellation WHERE invoice_id=$1",
                    invoice_id,
                )
                == 1
            )

    async def invoice_issue_race(self) -> None:
        """An invoice issue holding the order while a cancel waits: the
        cancel cancels that invoice too or answers 409; never a cancelled
        order with a live invoice."""

        name = "race_issue"
        version = await self.version(name)
        raw = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
        try:
            transaction = raw.transaction()
            await transaction.start()
            await raw.execute(
                "SELECT id FROM commitment WHERE id=$1 FOR UPDATE",
                self.data.orders[name],
            )
            await raw.execute(
                "UPDATE commitment SET status='invoiced' WHERE id=$1",
                self.data.orders[name],
            )
            await self.data._invoice(raw, name, "issued")
            cancelling = asyncio.create_task(self.cancel(name, version=version))
            await asyncio.sleep(0.5)
            assert not cancelling.done(), "the cancel must wait for the order"
            await transaction.commit()
            response = await asyncio.wait_for(cancelling, timeout=15)
        finally:
            await raw.close()
        invoice_status = await self.db.fetchval(
            "SELECT status FROM invoice WHERE id=$1", self.data.invoices[name]
        )
        if response.status_code == 201:
            assert invoice_status == "cancelled", invoice_status
        else:
            self.error(response, 409, "commitment_cancellation_conflict")
            assert await self.status(name) == "invoiced"
            assert invoice_status == "issued"

    async def overlapping_assignments(self) -> None:
        """Bulk driver assignments over the same orders in opposite orders,
        all at once: every one answers 200, none 500."""

        orders = [str(self.data.orders[name]) for name in self.data.ASSIGNED]
        driver = str(self.data.users["driver"])
        charity = self.sessions["charity"]
        headers = {**charity.headers, "Origin": BASE_URL}
        path = f"/api/v1/actions/{self.data.action}/delivery-board/drivers"
        calls = [
            charity.client.put(
                path,
                headers=headers,
                json={
                    "commitmentIds": orders if index % 2 else orders[::-1],
                    "driverUserId": driver if index % 3 else None,
                },
            )
            for index in range(40)
        ]
        responses = await asyncio.gather(*calls)
        assert [r.status_code for r in responses] == [200] * 40, [
            r.text for r in responses if r.status_code != 200
        ]
        assigned = {
            row["driver_user_id"]
            for row in await self.db.fetch(
                "SELECT driver_user_id FROM commitment_delivery"
                " WHERE commitment_id = ANY($1::uuid[])",
                [self.data.orders[name] for name in self.data.ASSIGNED],
            )
        }
        # One assignment ran last over all of them: one driver (or none).
        assert len(assigned) <= 1, assigned

    async def listing_counts(self) -> None:
        listing = await self.listing()
        by_id = {item["commitment"]["id"]: item for item in listing["items"]}
        cancelled = [
            name
            for name in self.data.ORDERS
            # race_issue ends either way (proven in invoice_issue_race).
            if name != "race_issue"
            if by_id[str(self.data.orders[name])]["commitment"]["status"] == "cancelled"
        ]
        assert sorted(cancelled) == sorted(
            [
                "plain",
                "draft",
                "invoiced",
                "sent",
                "paid",
                "missed",
                "race",
                "stale",
                "race_closure",
            ]
        )
        plain = by_id[str(self.data.orders["plain"])]
        assert plain["cancellation"]["reason"] == REASON
        assert by_id[str(self.data.orders["delivered"])]["delivered"] is True
        assert by_id[str(self.data.orders["delivered"])]["cancellation"] is None
        # Every order is 2 boxes for 72 EUR; only the active ones count.
        active = [
            item
            for item in listing["items"]
            if item["commitment"]["status"] != "cancelled"
        ]
        assert len(active) >= 2
        assert listing["currencyTotals"] == [
            {"currency": "EUR", "totalMinor": 7200 * len(active)}
        ]
        assert listing["quantities"] == [{"unit": "box", "quantity": 2 * len(active)}]
        assert listing["totalPieces"] == 48 * len(active)


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
        "order-cancellation-api: OK: roles, states, invoices, version, replay,"
        " races, board and Nachliefern task proven against PostgreSQL"
    )


def test_order_cancellation_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
