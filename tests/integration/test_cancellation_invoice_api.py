#!/usr/bin/env python3
"""Document series and cancellation invoice over HTTP: full app, real PostgreSQL.

Runs as a contract script in the schema gate (``tools/schema/test.sh``) and,
with ``CORE_DATABASE_URL`` set, under pytest. Proves ADR-0015 and spec §7:

- two actions with the same prefix share one series (before ADR-0015 the
  second action's first invoice took the number of the first action's);
- cancelling an invoice issues the cancellation invoice in the same
  transaction, for both cancel paths, with a number of the invoice series;
- a failed or replayed command uses no number;
- the refund marker, the document for older cancellations and the delivery.

The legal configuration is one row for the installation: the proof activates
its own version and puts the previous state back at the end.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.configuration import Settings
from leonaid.domain.calendar import local_day
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)
from leonaid.entrypoints.fastapi.platform import create_app

BASE_URL = "https://cancellation-invoice.leonaid.invalid"
REASON = "Sponsor hat die Bestellung zurückgezogen"
TAX_NOTE = "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet."
ISSUER = {
    "legalName": "Series proof Hilfswerk e.V.",
    "streetLine1": "Clubweg 1",
    "postalCode": "86150",
    "city": "Augsburg",
    "countryCode": "DE",
    "taxIdentifier": "103/999/99999",
    "email": "finanzen@series-proof.leonaid.invalid",
}
BANK = {
    "accountHolder": "Series proof Hilfswerk e.V.",
    "iban": "DE89370400440532013000",
    "bic": "COBADEFFXXX",
}


def settings() -> Settings:
    return Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-series-proof-secret-only-32-chars",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-series-proof-encryption-32-ch",
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
    """Two actions with one prefix, their orders and accounts in every role."""

    USERS = ("charity", "finance", "finance_manager", "acquirer")
    # Orders of action Alpha by what the proof does with them.
    ALPHA = (
        "first",
        "unpaid",
        "paid",
        "partial",
        "by_order",
        "send_now",
        "no_mail",
        "race_1",
        "race_2",
    )
    BETA = ("second", "race_3", "race_4")
    # Invoices cancelled before the cancellation invoice existed.
    LEGACY = ("legacy", "legacy_paid")

    def __init__(self) -> None:
        self.tag = f"DS{uuid4().hex[:8].upper()}"
        self.prefix = f"{self.tag}-"
        self.alpha = uuid4()
        self.beta = uuid4()
        self.legal_version = uuid4()
        self.offerings = {self.alpha: uuid4(), self.beta: uuid4()}
        self.users = {name: uuid4() for name in self.USERS}
        self.tokens = {name: uuid4().hex + uuid4().hex for name in self.USERS}
        # The charity admin also holds a session whose login is not fresh.
        self.stale_token = uuid4().hex + uuid4().hex
        names = (*self.ALPHA, *self.BETA, *self.LEGACY)
        self.orders = {name: uuid4() for name in names}
        self.legacy_invoices = {name: uuid4() for name in self.LEGACY}
        self.previous_state: asyncpg.Record | None = None

    def action_of(self, name: str) -> UUID:
        return self.beta if name in self.BETA else self.alpha

    def number(self, serial: int) -> str:
        return f"{self.prefix}{serial:04d}"

    def recipient(self, name: str) -> dict[str, object]:
        return {
            "recipientName": f"Firma {self.tag} {name}",
            "streetLine1": "Werkstraße 1",
            "postalCode": "86150",
            "city": "Augsburg",
            "countryCode": "DE",
            "email": (
                None
                if name == "no_mail"
                else f"{name.replace('_', '-')}.{self.tag.lower()}"
                "@buyer.leonaid.invalid"
            ),
        }

    async def create(self, connection: asyncpg.Connection[Any]) -> None:
        now = datetime.now(timezone.utc)
        for name, user_id in self.users.items():
            await connection.execute(
                "INSERT INTO user_account (id, email, display_name, status) "
                "VALUES ($1, $2, $3, 'active')",
                user_id,
                f"{name}.{self.tag.lower()}@leonaid.invalid",
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
            "INSERT INTO user_global_role (user_id, role) "
            "VALUES ($1, 'finance_manager')",
            self.users["finance_manager"],
        )
        await self._legal_configuration(connection)
        for action_id, name in ((self.alpha, "Alpha"), (self.beta, "Beta")):
            await connection.execute(
                """
                INSERT INTO charity_action (
                    id, carrier_name, name, purpose, status, starts_on, ends_on,
                    archive_slug
                )
                VALUES ($1, 'Series proof', $2, 'Proof', 'active',
                        '2026-01-01', '2099-12-31', $3)
                """,
                action_id,
                f"Aktion {self.tag} {name}",
                f"series-proof-{action_id}",
            )
            for capability in ("ordering", "invoicing"):
                await connection.execute(
                    "INSERT INTO charity_action_capability (action_id, capability) "
                    "VALUES ($1, $2)",
                    action_id,
                    capability,
                )
            # A profile as every release before ADR-0015 kept it: the same
            # prefix in both actions and each with its own counter at 1.
            await connection.execute(
                """
                INSERT INTO invoice_profile (
                    id, action_id, legal_name, street_line_1, postal_code, city,
                    country_code, tax_identifier, email, tax_treatment,
                    tax_rate_basis_points, tax_note, number_prefix, next_number,
                    number_width, payment_terms_days, confirmed_at,
                    legal_configuration_version_id, bank_account_holder, iban, bic
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'small_business', 0,
                        $10, $11, 1, 4, 14, $12, $13, $14, $15, $16)
                """,
                uuid4(),
                action_id,
                ISSUER["legalName"],
                ISSUER["streetLine1"],
                ISSUER["postalCode"],
                ISSUER["city"],
                ISSUER["countryCode"],
                ISSUER["taxIdentifier"],
                ISSUER["email"],
                TAX_NOTE,
                self.prefix,
                now,
                self.legal_version,
                BANK["accountHolder"],
                BANK["iban"],
                BANK["bic"],
            )
            await connection.execute(
                "INSERT INTO action_membership (id, action_id, user_id, role) "
                "VALUES ($1, $2, $3, 'charity_admin')",
                uuid4(),
                action_id,
                self.users["charity"],
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
                self.offerings[action_id],
                action_id,
                f"box-{self.offerings[action_id].hex[:12]}",
            )
        for name, role in (("finance", "finance_reader"), ("acquirer", "acquirer")):
            await connection.execute(
                "INSERT INTO action_membership (id, action_id, user_id, role) "
                "VALUES ($1, $2, $3, $4)",
                uuid4(),
                self.alpha,
                self.users[name],
                role,
            )
        for name, order_id in self.orders.items():
            await self._order(
                connection,
                order_id,
                name,
                "invoiced" if name in self.LEGACY else "review_ready",
            )
        for name in self.LEGACY:
            await self._legacy_cancelled_invoice(connection, name, now)

    async def remove_legal_configuration(
        self, connection: asyncpg.Connection[Any]
    ) -> None:
        """Puts back the installation's legal state as the proof found it."""

        previous = self.previous_state
        if previous is None:
            return
        await connection.execute(
            """
            UPDATE legal_configuration_state
            SET active_version_id = $1, draft_version_id = $2
            """,
            previous["active_version_id"],
            previous["draft_version_id"],
        )

    async def _legal_configuration(self, connection: asyncpg.Connection[Any]) -> None:
        self.previous_state = await connection.fetchrow(
            "SELECT active_version_id, draft_version_id FROM legal_configuration_state"
        )
        version = int(
            await connection.fetchval(
                "SELECT COALESCE(max(version), 0) + 1 FROM legal_configuration_version"
            )
        )
        await connection.execute(
            """
            INSERT INTO legal_configuration_version (
                id, version, legal_name, street_line_1, postal_code, city,
                country_code, tax_identifier, issuer_email, bank_account_holder,
                iban, bic, tax_treatment, tax_rate_basis_points, tax_note,
                number_prefix, number_width, payment_terms_days,
                public_order_legal_basis, public_order_notice_text,
                consent_text_version, privacy_contact_email,
                invoice_retention_days, commitment_retention_days,
                contact_retention_days, consent_evidence_retention_days,
                audit_retention_days, e_invoice_decision, tax_evidence_id,
                privacy_evidence_id, created_by_user_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                    'small_business', 0, $13, $14, 4, 14,
                    'Vertragserfüllung für den Seriennachweis.',
                    'Seriennachweis: Datenschutzhinweis für die Bestellung.',
                    'series-proof-v1', 'datenschutz@series-proof.leonaid.invalid',
                    3650, 3650, 730, 3650, 3650, 'pending',
                    'STEUER-SERIES-1', 'DATENSCHUTZ-SERIES-1', $15)
            """,
            self.legal_version,
            version,
            ISSUER["legalName"],
            ISSUER["streetLine1"],
            ISSUER["postalCode"],
            ISSUER["city"],
            ISSUER["countryCode"],
            ISSUER["taxIdentifier"],
            ISSUER["email"],
            BANK["accountHolder"],
            BANK["iban"],
            BANK["bic"],
            TAX_NOTE,
            self.prefix,
            self.users["charity"],
        )
        await connection.execute(
            "UPDATE legal_configuration_state SET active_version_id = $1",
            self.legal_version,
        )

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
            VALUES ($1, $2, $3, $4, $5, $6, 'Series proof', $6, $5)
            """,
            uuid4(),
            user_id,
            session_token_digest(token),
            fresh_login_at + SESSION_LIFETIME,
            now,
            fresh_login_at,
        )

    async def _order(
        self,
        connection: asyncpg.Connection[Any],
        order_id: UUID,
        name: str,
        status: str,
    ) -> None:
        party = uuid4()
        await connection.execute(
            """
            INSERT INTO commitment (
                id, action_id, twenty_company_id, source, status,
                customer_snapshot, invoice_recipient_snapshot, currency,
                total_minor, idempotency_key
            )
            VALUES ($1, $2, $3, 'admin', $4, $5::jsonb, $6::jsonb, 'EUR',
                    7200, $7)
            """,
            order_id,
            self.action_of(name),
            party,
            status,
            json.dumps(
                {
                    "partyKind": "company",
                    "twentyId": str(party),
                    "displayName": f"Firma {self.tag} {name}",
                    "email": None,
                }
            ),
            json.dumps(self.recipient(name)),
            f"series-proof:{order_id}",
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
            self.offerings[self.action_of(name)],
        )

    def legacy_number(self, name: str) -> str:
        return f"{self.tag}-OLD-{name.upper().replace('_', '-')}"

    async def _legacy_cancelled_invoice(
        self, connection: asyncpg.Connection[Any], name: str, now: datetime
    ) -> None:
        """An invoice cancelled by a release before the cancellation invoice."""

        invoice_id = self.legacy_invoices[name]
        issued_at = now - timedelta(days=3)
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
                $1, $2, $3, $4, 'cancelled', $5, $6, $7, 'EUR', 7200, 0, 7200,
                $8::jsonb, $9::jsonb, $10::jsonb,
                '[{"description":"Krapfenbox","quantity":2,"unit":"box","unitPriceGrossMinor":3600,"taxRateBasisPoints":0,"netMinor":7200,"taxMinor":0,"grossMinor":7200,"currency":"EUR"}]'::jsonb,
                'small_business', 0, $11, $4, $12, 2, $13, $6
            )
            """,
            invoice_id,
            self.alpha,
            self.orders[name],
            self.legacy_number(name),
            issued_at,
            local_day(issued_at),
            local_day(issued_at) + timedelta(days=14),
            json.dumps(ISSUER),
            json.dumps(BANK),
            json.dumps(self.recipient(name)),
            TAX_NOTE,
            self.users["charity"],
            f"series-proof:{invoice_id}",
        )
        if name == "legacy_paid":
            await connection.execute(
                """
                INSERT INTO payment_record (
                    id, invoice_id, amount_minor, currency, received_on,
                    recorded_by_user_id, reference, created_at
                )
                VALUES ($1, $2, 7200, 'EUR', $3, $4, $5, $6)
                """,
                uuid4(),
                invoice_id,
                local_day(issued_at),
                self.users["charity"],
                self.legacy_number(name),
                issued_at,
            )
        await connection.execute(
            """
            INSERT INTO invoice_cancellation (
                id, action_id, invoice_id, original_status, reason_snapshot,
                requested_by_user_id, idempotency_key, requested_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            uuid4(),
            self.alpha,
            invoice_id,
            "paid" if name == "legacy_paid" else "issued",
            REASON,
            self.users["charity"],
            f"series-proof-cancel:{invoice_id}",
            now - timedelta(days=2),
        )


class Session:
    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        self.client = client
        self.headers = {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}

    async def get(self, path: str) -> httpx.Response:
        return await self.client.get(path, headers=self.headers)

    async def post(
        self, path: str, body: dict[str, object] | None, key: str | None = None
    ) -> httpx.Response:
        headers = {**self.headers, "Origin": BASE_URL}
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
        self.data = data
        self.db = connection
        self.sessions = {
            name: Session(client, token) for name, token in data.tokens.items()
        }
        self.stale = Session(client, data.stale_token)
        self.invoices: dict[str, dict[str, Any]] = {}
        self.today = local_day(datetime.now(timezone.utc))

    @property
    def charity(self) -> Session:
        return self.sessions["charity"]

    @staticmethod
    def key() -> str:
        return f"series-proof:{uuid4()}"

    @staticmethod
    def error(response: httpx.Response, status: int, code: str) -> None:
        assert response.status_code == status, (status, code, response.text)
        assert response.json()["error"]["code"] == code, response.text

    async def next_number(self) -> int:
        return int(
            await self.db.fetchval(
                "SELECT next_number FROM document_series "
                "WHERE kind = 'invoice' AND prefix = $1",
                self.data.prefix,
            )
        )

    async def issue(self, name: str) -> httpx.Response:
        action = self.data.action_of(name)
        response = await self.charity.post(
            f"/api/v1/actions/{action}/commitments/{self.data.orders[name]}/invoice",
            {"serviceOn": self.today.isoformat()},
            self.key(),
        )
        if response.status_code == 201:
            self.invoices[name] = response.json()
        return response

    def invoice_path(self, name: str, suffix: str = "") -> str:
        if name in self.data.LEGACY:
            invoice_id = str(self.data.legacy_invoices[name])
        else:
            invoice_id = self.invoices[name]["id"]
        return (
            f"/api/v1/actions/{self.data.action_of(name)}/invoices/{invoice_id}{suffix}"
        )

    async def record(self, name: str, session: Session | None = None) -> dict[str, Any]:
        action = self.data.action_of(name)
        response = await (session or self.charity).get(
            f"/api/v1/actions/{action}/invoices"
        )
        assert response.status_code == 200, response.text
        invoice_id = (
            str(self.data.legacy_invoices[name])
            if name in self.data.LEGACY
            else self.invoices[name]["id"]
        )
        return next(
            dict(item)
            for item in response.json()["items"]
            if item["invoice"]["id"] == invoice_id
        )

    async def run(self) -> None:
        await self.one_series_for_both_actions()
        await self.cancelling_issues_the_cancellation_invoice()
        await self.failed_and_replayed_commands_use_no_number()
        await self.paid_invoice_and_refund_marker()
        await self.order_cancellation_issues_it_too()
        await self.older_cancellations_get_their_document()
        await self.delivery()
        await self.numbers_are_unique_and_final()
        await self.every_action_with_invoicing_gets_a_profile()

    async def cancel(
        self,
        name: str,
        *,
        session: Session | None = None,
        key: str | None = None,
        reason: str = REASON,
        send: bool | None = None,
    ) -> httpx.Response:
        body: dict[str, object] = {"reason": reason}
        if send is not None:
            body["sendCancellation"] = send
        return await (session or self.charity).post(
            self.invoice_path(name, "/cancellation"), body, key or self.key()
        )

    async def pay(self, name: str, amount_minor: int) -> None:
        response = await self.charity.post(
            self.invoice_path(name, "/payments"),
            {
                "amountMinor": amount_minor,
                "currency": "EUR",
                "receivedOn": self.today.isoformat(),
                "reference": self.invoices[name]["number"],
            },
            self.key(),
        )
        assert response.status_code == 201, response.text

    async def cancellation_row(self, name: str) -> asyncpg.Record:
        invoice_id = (
            self.data.legacy_invoices[name]
            if name in self.data.LEGACY
            else UUID(self.invoices[name]["id"])
        )
        row = await self.db.fetchrow(
            "SELECT * FROM invoice_cancellation WHERE invoice_id = $1", invoice_id
        )
        assert row is not None
        return row

    async def documents(self, name: str) -> list[asyncpg.Record]:
        invoice_id = (
            self.data.legacy_invoices[name]
            if name in self.data.LEGACY
            else UUID(self.invoices[name]["id"])
        )
        return list(
            await self.db.fetch(
                """
                SELECT document.*, event.event_type, event.status AS job_status
                FROM generated_document AS document
                LEFT JOIN outbox_event AS event
                  ON event.aggregate_type = 'generated_document'
                 AND event.aggregate_id = document.id
                WHERE document.invoice_id = $1
                  AND document.document_type = 'invoice_cancellation_pdf'
                """,
                invoice_id,
            )
        )

    async def cancelling_issues_the_cancellation_invoice(self) -> None:
        for name in ("unpaid", "paid", "partial", "by_order", "send_now", "no_mail"):
            issued = await self.issue(name)
            assert issued.status_code == 201, issued.text
        await self.pay("partial", 2000)
        before = await self.db.fetchrow(
            "SELECT * FROM invoice WHERE id = $1", UUID(self.invoices["unpaid"]["id"])
        )
        serial = await self.next_number()
        assert serial == 13
        response = await self.cancel("unpaid")
        assert response.status_code == 201, response.text
        body = response.json()
        # The next number of the invoice series (D-C1), dated today.
        assert body["number"] == self.data.number(serial)
        assert body["issuedOn"] == self.today.isoformat()
        assert body["originalStatus"] == "issued"
        assert body["receivedMinor"] == 0 and body["refundOpen"] is False
        assert await self.next_number() == serial + 1

        row = await self.cancellation_row("unpaid")
        snapshot = json.loads(row["snapshot"])
        invoice = self.invoices["unpaid"]
        assert row["document_version"] == 1
        assert row["issued_by_user_id"] == self.data.users["charity"]
        assert snapshot["number"] == body["number"]
        assert snapshot["originalNumber"] == invoice["number"]
        assert snapshot["originalIssuedOn"] == self.today.isoformat()
        assert snapshot["issuer"] == ISSUER
        assert snapshot["recipient"] == self.data.recipient("unpaid")
        # The stored amounts are the invoice's, not negative; the document
        # prints the minus sign.
        assert snapshot["totals"] == {
            "netMinor": 7200,
            "taxMinor": 0,
            "grossMinor": 7200,
            "currency": "EUR",
        }
        assert snapshot["lines"][0]["quantity"] == 2
        assert snapshot["lines"][0]["grossMinor"] == 7200
        assert snapshot["receivedMinor"] == 0
        # The reason belongs to the record, not to the document.
        assert REASON not in json.dumps(snapshot, ensure_ascii=False)

        documents = await self.documents("unpaid")
        assert len(documents) == 1
        assert documents[0]["status"] == "pending"
        assert documents[0]["event_type"] == "document.render.requested.v1"
        assert documents[0]["commitment_id"] == self.data.orders["unpaid"]

        # The invoice itself is not touched (ADR-0009): only its status.
        after = await self.db.fetchrow(
            "SELECT * FROM invoice WHERE id = $1", UUID(invoice["id"])
        )
        assert after["status"] == "cancelled"
        for column in (
            "number",
            "issued_on",
            "issuer_snapshot",
            "recipient_snapshot",
            "line_snapshot",
            "gross_minor",
            "document_version",
        ):
            assert after[column] == before[column], column
        audit = await self.db.fetchval(
            "SELECT payload FROM audit_event WHERE event_type = 'invoice_cancelled' "
            "AND entity_id = $1",
            UUID(body["id"]),
        )
        assert json.loads(audit)["cancellationNumber"] == body["number"]

        record = await self.record("unpaid")
        assert record["cancellation"]["number"] == body["number"]
        assert record["settlementStatus"] == "cancelled"
        assert record["cancellationDeliveries"] == []
        listing = await self.charity.get(
            f"/api/v1/actions/{self.data.alpha}/invoices/{invoice['id']}/documents"
        )
        assert listing.status_code == 200, listing.text
        by_type = {
            item["document"]["documentType"]: item for item in listing.json()["items"]
        }
        assert set(by_type) == {"invoice_pdf", "invoice_cancellation_pdf"}
        assert by_type["invoice_cancellation_pdf"]["documentNumber"] == body["number"]
        assert by_type["invoice_cancellation_pdf"]["invoiceNumber"] == invoice["number"]
        assert by_type["invoice_pdf"]["documentNumber"] is None

    async def failed_and_replayed_commands_use_no_number(self) -> None:
        serial = await self.next_number()
        # The same key again: the same document, no second number.
        key = self.key()
        first = await self.cancel("partial", key=key)
        assert first.status_code == 201, first.text
        assert first.json()["number"] == self.data.number(serial)
        # A part payment is received money as well: the invoice was not
        # `paid`, but its 20.00 EUR go back.
        assert first.json()["originalStatus"] == "issued"
        assert first.json()["receivedMinor"] == 2000
        assert first.json()["refundOpen"] is True
        replay = await self.cancel("partial", key=key)
        assert replay.status_code == 201, replay.text
        assert replay.json()["number"] == first.json()["number"]
        assert replay.json()["replayed"] is True
        assert await self.next_number() == serial + 1
        assert len(await self.documents("partial")) == 1
        # A refused command leaves the series alone.
        self.error(
            await self.cancel("partial"), 409, "invoice_cancellation_already_recorded"
        )
        refused = await self.cancel("paid", reason="kurz")
        assert refused.status_code == 422, refused.text
        self.error(
            await self.cancel("paid", session=self.sessions["finance"]),
            403,
            "invoice_settlement_required",
        )
        self.error(
            await self.cancel("paid", session=self.stale), 401, "fresh_login_required"
        )
        # A transaction that fails after it took a number gives it back:
        # sending needs a recipient address, which this invoice lacks.
        self.error(
            await self.cancel("no_mail", send=True),
            409,
            "invoice_delivery_recipient_missing",
        )
        assert (
            await self.db.fetchval(
                "SELECT status FROM invoice WHERE id = $1",
                UUID(self.invoices["no_mail"]["id"]),
            )
            == "issued"
        )
        assert await self.next_number() == serial + 1

    async def paid_invoice_and_refund_marker(self) -> None:
        await self.pay("paid", 7200)
        serial = await self.next_number()
        response = await self.cancel("paid", session=self.sessions["finance_manager"])
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["number"] == self.data.number(serial)
        assert body["originalStatus"] == "paid"
        assert body["receivedMinor"] == 7200 and body["refundOpen"] is True
        snapshot = json.loads((await self.cancellation_row("paid"))["snapshot"])
        assert snapshot["receivedMinor"] == 7200
        # The payment stays recorded and cannot be reversed (ADR-0014).
        record = await self.record("paid")
        assert record["paidMinor"] == 7200
        assert record["cancellation"]["refundOpen"] is True
        payment_id = record["payments"][0]["id"]
        self.error(
            await self.charity.post(
                self.invoice_path("paid", f"/payments/{payment_id}/reversal"),
                {"reason": "Erstattung an den Sponsor überwiesen"},
                self.key(),
            ),
            409,
            "invoice_payment_cancelled",
        )

        refund = self.invoice_path("paid", "/cancellation/refund")
        today = self.today.isoformat()
        # The gate of a payment reversal: rights, fresh login, a key.
        self.error(
            await self.sessions["finance"].post(
                refund, {"settledOn": today}, self.key()
            ),
            403,
            "invoice_settlement_required",
        )
        self.error(
            await self.stale.post(refund, {"settledOn": today}, self.key()),
            401,
            "fresh_login_required",
        )
        keyless = await self.charity.post(refund, {"settledOn": today})
        assert keyless.status_code == 422, keyless.text
        assert keyless.json()["error"]["code"] == (
            "invoice_settlement_idempotency_key_invalid"
        )
        tomorrow = (self.today + timedelta(days=1)).isoformat()
        future = await self.charity.post(refund, {"settledOn": tomorrow}, self.key())
        assert future.status_code == 422, future.text
        assert future.json()["error"]["code"] == "invoice_refund_future_date"
        yesterday = (self.today - timedelta(days=1)).isoformat()
        early = await self.charity.post(refund, {"settledOn": yesterday}, self.key())
        assert early.json()["error"]["code"] == "invoice_refund_before_cancellation"
        key = self.key()
        note: dict[str, object] = {
            "settledOn": today,
            "note": "  Überweisung vom Vereinskonto  ",
        }
        settled = await self.charity.post(refund, note, key)
        assert settled.status_code == 201, settled.text
        assert settled.json()["refundOpen"] is False
        assert settled.json()["replayed"] is False
        assert settled.json()["refundSettledOn"] == today
        assert settled.json()["refundNote"] == "Überweisung vom Vereinskonto"
        assert settled.json()["refundSettledByDisplayName"].startswith("Charity")
        # The same key again: the stored marker, not an error.
        replay = await self.charity.post(refund, note, key)
        assert replay.status_code == 201, replay.text
        assert replay.json()["replayed"] is True
        assert replay.json()["refundSettledAt"] == settled.json()["refundSettledAt"]
        # The same key for other data, and another command on a settled refund.
        self.error(
            await self.charity.post(refund, {"settledOn": today}, key),
            409,
            "idempotency_conflict",
        )
        self.error(
            await self.charity.post(refund, {"settledOn": today}, self.key()),
            409,
            "invoice_refund_already_settled",
        )
        record = await self.record("paid", self.sessions["finance"])
        assert record["cancellation"]["refundOpen"] is False
        assert (
            await self.db.fetchval(
                "SELECT count(*) FROM audit_event WHERE event_type = "
                "'invoice_refund_settled' AND entity_id = $1",
                UUID(body["id"]),
            )
            == 1
        )
        # Nothing was received for the unpaid invoice: nothing to settle.
        self.error(
            await self.charity.post(
                self.invoice_path("unpaid", "/cancellation/refund"),
                {"settledOn": today},
                self.key(),
            ),
            409,
            "invoice_refund_not_due",
        )
        partial = await self.record("partial")
        assert partial["cancellation"]["refundOpen"] is True

    async def order_cancellation_issues_it_too(self) -> None:
        serial = await self.next_number()
        orders = await self.charity.get(
            f"/api/v1/actions/{self.data.alpha}/commitments"
        )
        assert orders.status_code == 200, orders.text
        order_id = str(self.data.orders["by_order"])
        order = next(
            item
            for item in orders.json()["items"]
            if item["commitment"]["id"] == order_id
        )
        response = await self.charity.post(
            f"/api/v1/actions/{self.data.alpha}/commitments/{order_id}/cancellation",
            {
                "expectedVersion": order["commitment"]["deliveryCompletionVersion"],
                "reason": REASON,
            },
            self.key(),
        )
        assert response.status_code == 201, response.text
        row = await self.cancellation_row("by_order")
        assert row["number"] == self.data.number(serial)
        assert row["id"] == UUID(
            response.json()["cancellation"]["invoiceCancellationId"]
        )
        # The order names the cancellation invoice, in the answer and the list.
        assert (
            response.json()["cancellation"]["invoiceCancellationNumber"]
            == (row["number"])
        )
        listed = await self.charity.get(
            f"/api/v1/actions/{self.data.alpha}/commitments"
        )
        by_order = next(
            item
            for item in listed.json()["items"]
            if item["commitment"]["id"] == order_id
        )
        assert by_order["cancellation"]["invoiceCancellationNumber"] == row["number"]
        assert len(await self.documents("by_order")) == 1
        assert await self.next_number() == serial + 1
        # The order of an invoice that was cancelled with money on it: the
        # payment cannot be reversed any more, so it must not block the
        # order. Nothing is issued again.
        paid_id = str(self.data.orders["paid"])
        paid = next(
            item
            for item in orders.json()["items"]
            if item["commitment"]["id"] == paid_id
        )
        assert paid["invoice"]["status"] == "cancelled"
        assert paid["invoice"]["paidMinor"] == 7200
        released = await self.charity.post(
            f"/api/v1/actions/{self.data.alpha}/commitments/{paid_id}/cancellation",
            {
                "expectedVersion": paid["commitment"]["deliveryCompletionVersion"],
                "reason": REASON,
            },
            self.key(),
        )
        assert released.status_code == 201, released.text
        assert released.json()["cancellation"]["invoiceCancellationId"] is None
        assert released.json()["cancellation"]["invoiceCancellationNumber"] is None
        assert await self.next_number() == serial + 1
        assert len(await self.documents("paid")) == 1

    async def older_cancellations_get_their_document(self) -> None:
        record = await self.record("legacy")
        assert record["cancellation"]["number"] is None
        assert record["cancellation"]["issuedOn"] is None
        paid = await self.record("legacy_paid")
        # The reminder does not wait for the document.
        assert paid["cancellation"]["refundOpen"] is True
        assert paid["cancellation"]["receivedMinor"] == 7200

        path = self.invoice_path("legacy", "/cancellation/document")
        self.error(
            await self.stale.post(path, None, self.key()), 401, "fresh_login_required"
        )
        self.error(
            await self.sessions["finance"].post(path, None, self.key()),
            403,
            "invoice_settlement_required",
        )
        serial = await self.next_number()
        key = self.key()
        issued = await self.charity.post(path, None, key)
        assert issued.status_code == 201, issued.text
        assert issued.json()["number"] == self.data.number(serial)
        assert issued.json()["issuedOn"] == self.today.isoformat()
        replay = await self.charity.post(path, None, key)
        assert replay.status_code == 201 and replay.json()["replayed"] is True
        assert replay.json()["number"] == issued.json()["number"]
        self.error(
            await self.charity.post(path, None, self.key()),
            409,
            "invoice_cancellation_document_exists",
        )
        assert await self.next_number() == serial + 1
        row = await self.cancellation_row("legacy")
        snapshot = json.loads(row["snapshot"])
        assert snapshot["originalNumber"] == self.data.legacy_number("legacy")
        # Dated today, not on the day of the old cancellation.
        assert row["issued_on"] == self.today
        assert row["requested_at"] < row["issued_at"]
        assert len(await self.documents("legacy")) == 1
        # An invoice that is not cancelled has nothing to issue.
        self.error(
            await self.charity.post(
                self.invoice_path("first", "/cancellation/document"), None, self.key()
            ),
            404,
            "invoice_cancellation_not_found",
        )
        with_payment = await self.charity.post(
            self.invoice_path("legacy_paid", "/cancellation/document"),
            None,
            self.key(),
        )
        assert with_payment.status_code == 201, with_payment.text
        assert with_payment.json()["receivedMinor"] == 7200

    async def make_available(self, name: str) -> None:
        """What the worker does after rendering; no worker runs here."""

        document = (await self.documents(name))[0]
        await self.db.execute(
            """
            UPDATE generated_document
            SET status = 'available', filename = 'Stornorechnung.pdf',
                storage_bucket = 'leonaid', object_key = $2,
                storage_version_id = 'proof', size_bytes = 1200, sha256 = $3,
                render_version = 'invoice-cancellation-v1+typst-0.13.1',
                available_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            document["id"],
            f"proof/{document['id']}.pdf",
            "a" * 64,
        )

    async def delivery(self) -> None:
        send = self.invoice_path("unpaid", "/cancellation/deliveries")
        self.error(
            await self.charity.post(send, None, self.key()),
            409,
            "invoice_delivery_document_not_ready",
        )
        await self.make_available("unpaid")
        self.error(
            await self.sessions["finance_manager"].post(send, None, self.key()),
            403,
            "invoice_delivery_required",
        )
        key = self.key()
        sent = await self.charity.post(send, None, key)
        assert sent.status_code == 201, sent.text
        delivery = sent.json()
        cancellation = (await self.record("unpaid"))["cancellation"]
        invoice = self.invoices["unpaid"]
        assert delivery["kind"] == "invoice_cancellation"
        assert delivery["status"] == "queued"
        assert delivery["recipientEmail"] == self.data.recipient("unpaid")["email"]
        assert delivery["subject"] == (
            f"Stornorechnung {cancellation['number']} zur Rechnung "
            f"{invoice['number']} · Aktion {self.data.tag} Alpha"
        )
        text = await self.db.fetchval(
            "SELECT text_snapshot FROM invoice_delivery WHERE id = $1",
            UUID(delivery["id"]),
        )
        assert (
            f"anbei erhalten Sie die Stornorechnung zu Ihrer Rechnung "
            f"{invoice['number']}. Die Rechnung ist damit aufgehoben." in text
        )
        assert f"Aus der Rechnung {invoice['number']} ist kein Betrag mehr" in text
        replay = await self.charity.post(send, None, key)
        assert replay.status_code == 201 and replay.json()["id"] == delivery["id"]
        record = await self.record("unpaid")
        assert [item["id"] for item in record["cancellationDeliveries"]] == [
            delivery["id"]
        ]
        assert record["deliveries"] == []
        # A cancelled invoice itself is still not sent.
        self.error(
            await self.charity.post(
                self.invoice_path("unpaid", "/deliveries"), None, self.key()
            ),
            409,
            "invoice_delivery_cancelled",
        )
        # The invoice's own retry route does not reach this delivery.
        self.error(
            await self.charity.post(
                self.invoice_path("unpaid", f"/deliveries/{delivery['id']}/retry"),
                None,
            ),
            404,
            "invoice_delivery_not_found",
        )
        retry = self.invoice_path(
            "unpaid", f"/cancellation/deliveries/{delivery['id']}/retry"
        )
        self.error(
            await self.charity.post(retry, None), 409, "invoice_delivery_not_retryable"
        )
        # The gate of the invoice's own retry: fresh login, action manager.
        self.error(await self.stale.post(retry, None), 401, "fresh_login_required")
        self.error(
            await self.stale.post(
                self.invoice_path("unpaid", f"/deliveries/{delivery['id']}/retry"),
                None,
            ),
            401,
            "fresh_login_required",
        )
        self.error(
            await self.sessions["finance_manager"].post(retry, None),
            403,
            "invoice_delivery_retry_required",
        )
        # An invoice that is not cancelled has no cancellation invoice to send.
        self.error(
            await self.charity.post(
                self.invoice_path("first", "/cancellation/deliveries"),
                None,
                self.key(),
            ),
            409,
            "invoice_cancellation_not_found",
        )
        # A paid invoice's cover mail names the money and the refund.
        await self.make_available("paid")
        paid = await self.charity.post(
            self.invoice_path("paid", "/cancellation/deliveries"), None, self.key()
        )
        assert paid.status_code == 201, paid.text
        paid_text = await self.db.fetchval(
            "SELECT text_snapshot FROM invoice_delivery WHERE id = $1",
            UUID(paid.json()["id"]),
        )
        assert "haben wir 72,00 € erhalten. Die Erstattung erfolgt gesondert." in (
            paid_text
        )
        # "Stornorechnung gleich senden": queued with the cancel command,
        # for a PDF that is still to be rendered.
        self.error(
            await self.cancel(
                "send_now", session=self.sessions["finance_manager"], send=True
            ),
            403,
            "invoice_delivery_required",
        )
        now = await self.cancel("send_now", send=True)
        assert now.status_code == 201, now.text
        record = await self.record("send_now")
        assert len(record["cancellationDeliveries"]) == 1
        queued = record["cancellationDeliveries"][0]
        assert queued["status"] == "queued"
        assert f"Stornorechnung {now.json()['number']} " in queued["subject"]
        assert (await self.documents("send_now"))[0]["status"] == "pending"

    async def create_action(self, name: str, capabilities: list[str]) -> dict[str, Any]:
        response = await self.charity.post(
            "/api/v1/actions",
            {
                "carrierName": "Series proof",
                "name": f"Aktion {self.data.tag} {name}",
                "purpose": "Proof",
                "startsOn": "2027-02-01",
                "endsOn": "2027-03-31",
                "archiveSlug": f"series-proof-{self.data.tag.lower()}-{name.lower()}",
                "capabilities": capabilities,
                "beneficiaries": [
                    {
                        "organizationName": "Bildungshafen Beispielstadt",
                        "publicDescription": "Finanziert Lernmaterial für Kinder.",
                    }
                ],
                "goal": {
                    "goalValue": "100",
                    "actualValue": "0",
                    "unit": "EUR",
                    "currency": "EUR",
                },
            },
        )
        assert response.status_code == 201, response.text
        return dict(response.json())

    async def profile_of(self, action_id: str) -> dict[str, Any] | None:
        context = await self.charity.get(f"/api/v1/actions/{action_id}/invoice-context")
        assert context.status_code == 200, context.text
        profile = context.json()["profile"]
        return None if profile is None else dict(profile)

    async def every_action_with_invoicing_gets_a_profile(self) -> None:
        """Before, no code created a profile: a new action could not issue."""

        expected_next = self.data.number(await self.next_number())
        # At creation, from the active legal configuration.
        created = await self.create_action("Gamma", ["invoicing"])
        profile = await self.profile_of(created["id"])
        assert profile is not None
        assert profile["readyToIssue"] is True
        assert profile["legalConfigurationVersionId"] == str(self.data.legal_version)
        assert profile["issuer"]["legalName"] == ISSUER["legalName"]
        assert profile["paymentDetails"] == BANK
        # The same series as every other action with this prefix.
        assert profile["nextInvoiceNumber"] == expected_next
        # When a draft action gets the capability later.
        later = await self.create_action("Delta", ["acquisition"])
        assert (
            await self.db.fetchval(
                "SELECT count(*) FROM invoice_profile WHERE action_id = $1",
                UUID(later["id"]),
            )
            == 0
        )
        changed = await self.client_put(
            f"/api/v1/actions/{later['id']}/capabilities",
            {
                "revision": later["revision"],
                "capabilities": ["acquisition", "invoicing"],
            },
        )
        assert changed.status_code == 200, changed.text
        profile = await self.profile_of(later["id"])
        assert profile is not None and profile["readyToIssue"] is True
        # The profile stays when the capability goes and is not doubled when
        # it comes back.
        for capabilities in (["acquisition"], ["acquisition", "invoicing"]):
            revision = changed.json()["revision"]
            changed = await self.client_put(
                f"/api/v1/actions/{later['id']}/capabilities",
                {"revision": revision, "capabilities": capabilities},
            )
            assert changed.status_code == 200, changed.text
        assert (
            await self.db.fetchval(
                "SELECT count(*) FROM invoice_profile WHERE action_id = $1",
                UUID(later["id"]),
            )
            == 1
        )
        # Without an active legal configuration nothing can be confirmed: no
        # profile, and the context says so.
        await self.db.execute(
            "UPDATE legal_configuration_state SET active_version_id = NULL"
        )
        try:
            unconfigured = await self.create_action("Epsilon", ["invoicing"])
            assert await self.profile_of(unconfigured["id"]) is None
        finally:
            await self.db.execute(
                "UPDATE legal_configuration_state SET active_version_id = $1",
                self.data.legal_version,
            )

    async def client_put(self, path: str, body: dict[str, object]) -> httpx.Response:
        return await self.charity.client.put(
            path, headers={**self.charity.headers, "Origin": BASE_URL}, json=body
        )

    async def numbers_are_unique_and_final(self) -> None:
        row = await self.cancellation_row("unpaid")
        # No invoice can take the number of a cancellation invoice.
        try:
            async with self.db.transaction():
                await self.db.execute(
                    "UPDATE invoice SET number = $1 WHERE id = $2",
                    row["number"],
                    UUID(self.invoices["first"]["id"]),
                )
        except asyncpg.PostgresError:
            pass
        else:
            raise AssertionError("an invoice took a cancellation invoice's number")
        assert (
            await self.db.fetchval(
                "SELECT kind FROM document_number WHERE number = $1", row["number"]
            )
            == "invoice_cancellation"
        )
        for statement in (
            "UPDATE invoice_cancellation SET number = number || 'X' WHERE id = $1",
            "UPDATE invoice_cancellation SET snapshot = '{}'::jsonb WHERE id = $1",
            "UPDATE invoice_cancellation SET issued_on = issued_on + 1 WHERE id = $1",
        ):
            try:
                async with self.db.transaction():
                    await self.db.execute(statement, row["id"])
            except asyncpg.IntegrityConstraintViolationError:
                continue
            raise AssertionError(f"the issued document was changed: {statement}")
        # Every number of the series was used once: 1 to next - 1, no gap.
        issued = await self.db.fetch(
            "SELECT number FROM document_number WHERE left(number, $2) = $1",
            self.data.prefix,
            len(self.data.prefix),
        )
        tails = [item["number"][len(self.data.prefix) :] for item in issued]
        # The two older invoices of the fixture carry their own numbers.
        serials = sorted(int(tail) for tail in tails if tail.isdigit())
        assert serials == list(range(1, await self.next_number())), serials

    async def one_series_for_both_actions(self) -> None:
        """Before ADR-0015 the second action issued the first one's number."""

        first = await self.issue("first")
        assert first.status_code == 201, first.text
        assert first.json()["number"] == self.data.number(1)
        second = await self.issue("second")
        assert second.status_code == 201, second.text
        assert second.json()["number"] == self.data.number(2)
        assert await self.next_number() == 3
        # Both actions at once: every number once, none left out.
        names = ("race_1", "race_3", "race_2", "race_4")
        responses = await asyncio.gather(*(self.issue(name) for name in names))
        assert [item.status_code for item in responses] == [201] * 4, [
            item.text for item in responses
        ]
        assert sorted(item.json()["number"] for item in responses) == [
            self.data.number(serial) for serial in range(3, 7)
        ]
        assert await self.next_number() == 7
        for action in (self.data.alpha, self.data.beta):
            context = await self.charity.get(
                f"/api/v1/actions/{action}/invoice-context"
            )
            assert context.status_code == 200, context.text
            assert context.json()["profile"]["nextInvoiceNumber"] == (
                self.data.number(7)
            )


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
        await data.remove_legal_configuration(connection)
        await connection.close()
    print(
        "cancellation-invoice-api: OK: one series for the installation, the"
        " cancellation invoice of both cancel paths, replay, refund marker,"
        " older cancellations and delivery proven against PostgreSQL"
    )


def test_cancellation_invoice_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
