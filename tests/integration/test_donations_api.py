#!/usr/bin/env python3
"""Donations over HTTP: full app, real PostgreSQL.

Runs as a contract script in the schema gate (``tools/schema/test.sh``) and,
with ``CORE_DATABASE_URL`` set, under pytest. Proves ADR-0016 and spec §8.1
to §8.4:

- no donation without the capability and without a receiving body in the
  active legal configuration, and neither refusal uses a number;
- a donation takes the next number of the installation's ``donation`` series
  and gets its pledge document in the same transaction;
- one payment per donation, of any amount; withdrawing it is reasoned and
  kept; only an unpaid donation can be cancelled;
- who may read, record and send; fresh login; replay;
- the pledge mail, the sums of the list and of the dashboard, the navigation.

The legal configuration is one row for the installation: the proof activates
its own versions and puts the previous state back at the end.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.dashboard import AsyncpgDashboardRepository
from leonaid.adapters.postgres.donations import AsyncpgDonationRepository
from leonaid.adapters.postgres.invoice_deliveries import (
    AsyncpgInvoiceDeliveryRepository,
)
from leonaid.configuration import Settings
from leonaid.domain.calendar import local_day
from leonaid.domain.donations import (
    ExemptionNoticeKind,
    ReceiptSigning,
    ReceivingBody,
)
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)
from leonaid.entrypoints.fastapi.platform import create_app

BASE_URL = "https://donations.leonaid.invalid"
TAX_NOTE = "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet."
PLEDGE_TEXT = (
    "Ihre Spende ist freiwillig. Sie erhalten dafür keine Gegenleistung. "
    "Dieses Schreiben ist keine Rechnung."
)
LIABILITY_TEXT = (
    "Hinweis: Wer vorsätzlich oder grob fahrlässig eine unrichtige "
    "Zuwendungsbestätigung erstellt, haftet für die entgangene Steuer."
)
REASON = "Zahlung gehörte zu einer anderen Spende"


def settings() -> Settings:
    return Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-donation-proof-secret-32-chars",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-donation-proof-encrypt-32-ch",
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
    """Two actions that take donations, one that does not, every role."""

    USERS = (
        "charity",
        "finance",
        "finance_manager",
        "acquirer",
        "outsider",
        "system",
    )

    def __init__(self) -> None:
        self.tag = f"DN{uuid4().hex[:8].upper()}"
        self.pledge_prefix = f"{self.tag}S-"
        self.receipt_prefix = f"{self.tag}Z-"
        self.alpha = uuid4()
        self.beta = uuid4()
        # Orders only: no `donations` capability.
        self.gamma = uuid4()
        self.without_body = uuid4()
        self.with_body = uuid4()
        self.users = {name: uuid4() for name in self.USERS}
        self.tokens = {name: uuid4().hex + uuid4().hex for name in self.USERS}
        self.stale_token = uuid4().hex + uuid4().hex
        self.previous_state: asyncpg.Record | None = None

    def body(self) -> ReceivingBody:
        return ReceivingBody(
            legal_name=f"Förderverein {self.tag} e. V.",
            street_line_1="Marktplatz 1",
            postal_code="12345",
            city="Musterstadt",
            country_code="DE",
            legal_form="registered_association",
            tax_office="Finanzamt Musterstadt",
            tax_number="123/456/78901",
            notice_kind=ExemptionNoticeKind.FREISTELLUNGSBESCHEID,
            notice_date=date(2025, 3, 15),
            assessment_period_from=2021,
            assessment_period_to=2023,
            purposes="Förderung der Jugendhilfe, der Bildung und mildtätiger Zwecke",
            bank_account_holder=f"Förderverein {self.tag} e. V.",
            iban="DE02120300000000202051",
            bic="BYLADEM1001",
            signatory_name="Erika Mustermann",
            signatory_function="Schatzmeisterin",
            signing=ReceiptSigning.MACHINE,
            machine_notified_on=date(2025, 4, 1),
            pledge_prefix=self.pledge_prefix,
            receipt_prefix=self.receipt_prefix,
            number_width=4,
            pledge_text=PLEDGE_TEXT,
            receipt_liability_text=LIABILITY_TEXT,
        )

    def number(self, serial: int) -> str:
        return f"{self.pledge_prefix}{serial:04d}"

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
        await connection.execute(
            "INSERT INTO user_global_role (user_id, role) VALUES ($1, 'system_admin')",
            self.users["system"],
        )
        self.previous_state = await connection.fetchrow(
            "SELECT active_version_id, draft_version_id FROM legal_configuration_state"
        )
        await self._legal_version(connection, self.without_body, None)
        await self._legal_version(connection, self.with_body, self.body())
        await self.activate(connection, self.without_body)
        for action_id, name, capabilities in (
            (self.alpha, "Alpha", ("ordering", "invoicing", "donations")),
            (self.beta, "Beta", ("donations",)),
            (self.gamma, "Gamma", ("ordering",)),
        ):
            await connection.execute(
                """
                INSERT INTO charity_action (
                    id, carrier_name, name, purpose, status, starts_on, ends_on,
                    archive_slug
                )
                VALUES ($1, 'Donation proof', $2, 'Jugendhilfe im Ort', 'active',
                        '2026-01-01', '2099-12-31', $3)
                """,
                action_id,
                f"Aktion {self.tag} {name}",
                f"donation-proof-{action_id}",
            )
            for capability in capabilities:
                await connection.execute(
                    "INSERT INTO charity_action_capability (action_id, capability) "
                    "VALUES ($1, $2)",
                    action_id,
                    capability,
                )
            await connection.execute(
                "INSERT INTO action_membership (id, action_id, user_id, role) "
                "VALUES ($1, $2, $3, 'charity_admin')",
                uuid4(),
                action_id,
                self.users["charity"],
            )
        for name, action_id, role in (
            ("finance", self.alpha, "finance_reader"),
            ("acquirer", self.alpha, "acquirer"),
            # Reads the finances of an action that takes no donations.
            ("outsider", self.gamma, "finance_reader"),
        ):
            await connection.execute(
                "INSERT INTO action_membership (id, action_id, user_id, role) "
                "VALUES ($1, $2, $3, $4)",
                uuid4(),
                action_id,
                self.users[name],
                role,
            )

    async def activate(
        self, connection: asyncpg.Connection[Any], version_id: UUID
    ) -> None:
        await connection.execute(
            "UPDATE legal_configuration_state SET active_version_id = $1",
            version_id,
        )

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

    async def _legal_version(
        self,
        connection: asyncpg.Connection[Any],
        version_id: UUID,
        body: ReceivingBody | None,
    ) -> None:
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
                privacy_evidence_id, created_by_user_id, donations
            )
            VALUES ($1, $2, 'Donation proof Hilfswerk e.V.', 'Clubweg 1', '86150',
                    'Augsburg', 'DE', '103/999/99999',
                    'finanzen@donation-proof.leonaid.invalid',
                    'Donation proof Hilfswerk e.V.', 'DE89370400440532013000',
                    'COBADEFFXXX', 'small_business', 0, $3, $4, 4, 14,
                    'Vertragserfüllung für den Spendennachweis.',
                    'Spendennachweis: Datenschutzhinweis für die Bestellung.',
                    'donation-proof-v1', 'datenschutz@donation-proof.leonaid.invalid',
                    3650, 3650, 730, 3650, 3650, 'pending',
                    'STEUER-DONATION-1', 'DATENSCHUTZ-DONATION-1', $5, $6::jsonb)
            """,
            version_id,
            version,
            TAX_NOTE,
            f"{self.tag}R-",
            self.users["charity"],
            json.dumps(body.payload()) if body is not None else None,
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
            VALUES ($1, $2, $3, $4, $5, $6, 'Donation proof', $6, $5)
            """,
            uuid4(),
            user_id,
            session_token_digest(token),
            fresh_login_at + SESSION_LIFETIME,
            now,
            fresh_login_at,
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
        self.today = local_day(datetime.now(timezone.utc))
        self.donations: dict[str, dict[str, Any]] = {}

    @property
    def charity(self) -> Session:
        return self.sessions["charity"]

    @staticmethod
    def key() -> str:
        return f"donation-proof:{uuid4()}"

    @staticmethod
    def error(response: httpx.Response, status: int, code: str) -> None:
        assert response.status_code == status, (status, code, response.text)
        assert response.json()["error"]["code"] == code, response.text

    def path(self, action: UUID, name: str | None = None, suffix: str = "") -> str:
        base = f"/api/v1/actions/{action}/donations"
        if name is None:
            return base
        return f"{base}/{self.donations[name]['id']}{suffix}"

    def draft(
        self, name: str, *, amount: int = 5000, email: bool = True
    ) -> dict[str, object]:
        return {
            "donor": {
                "name": f"Spenderin {self.data.tag} {name}",
                "streetLine1": "Gartenweg 4",
                "postalCode": "12345",
                "city": "Musterstadt",
                "email": (
                    f"{name.replace('_', '-')}.{self.data.tag.lower()}"
                    "@donor.leonaid.invalid"
                    if email
                    else None
                ),
            },
            "pledgedMinor": amount,
            "note": None,
        }

    async def create(
        self,
        name: str,
        *,
        action: UUID | None = None,
        session: Session | None = None,
        amount: int = 5000,
        email: bool = True,
    ) -> dict[str, Any]:
        response = await (session or self.charity).post(
            self.path(action or self.data.alpha),
            self.draft(name, amount=amount, email=email),
            self.key(),
        )
        assert response.status_code == 201, response.text
        self.donations[name] = response.json()
        return self.donations[name]

    async def listing(
        self, action: UUID | None = None, session: Session | None = None
    ) -> dict[str, Any]:
        response = await (session or self.charity).get(
            self.path(action or self.data.alpha)
        )
        assert response.status_code == 200, response.text
        return dict(response.json())

    async def record(self, name: str) -> dict[str, Any]:
        listing = await self.listing(UUID(self.donations[name]["actionId"]))
        return next(
            dict(item)
            for item in listing["items"]
            if item["id"] == self.donations[name]["id"]
        )

    async def next_number(self) -> int | None:
        value = await self.db.fetchval(
            "SELECT next_number FROM document_series "
            "WHERE kind = 'donation' AND prefix = $1",
            self.data.pledge_prefix,
        )
        return int(value) if value is not None else None

    async def pay(
        self, name: str, amount: int, received_on: date | None = None
    ) -> httpx.Response:
        return await self.charity.post(
            self.path(self.data.alpha, name, "/payment"),
            {
                "amountMinor": amount,
                "receivedOn": (received_on or self.today).isoformat(),
                "note": None,
            },
            self.key(),
        )

    async def run(self) -> None:
        await self.nothing_without_capability_or_receiving_body()
        await self.data.activate(self.db, self.data.with_body)
        await self.a_donation_takes_a_number_and_a_pledge_document()
        await self.replay_and_refusals_use_no_number()
        await self.one_series_for_the_installation()
        await self.who_may_read_record_and_send()
        await self.one_payment_of_any_amount()
        await self.only_an_unpaid_donation_is_cancelled()
        await self.other_actions_cannot_reach_it()
        await self.the_pledge_goes_out_by_mail()
        await self.sums_dashboard_and_navigation()
        await self.the_pledge_keeps_the_body_of_its_day()
        await self.a_privacy_erasure_names_and_keeps_donations()
        await self.stored_donations_are_final()

    async def nothing_without_capability_or_receiving_body(self) -> None:
        listing = await self.listing()
        assert listing["receivingBodyName"] is None
        assert listing["items"] == []
        assert listing["mayManage"] is True
        self.error(
            await self.charity.post(
                self.path(self.data.alpha), self.draft("early"), self.key()
            ),
            409,
            "donation_receiving_body_missing",
        )
        assert await self.next_number() is None
        # An action without the capability, with and without a receiving body.
        for version in (self.data.without_body, self.data.with_body):
            await self.data.activate(self.db, version)
            self.error(
                await self.charity.get(self.path(self.data.gamma)),
                409,
                "donation_capability_disabled",
            )
            self.error(
                await self.charity.post(
                    self.path(self.data.gamma), self.draft("gamma"), self.key()
                ),
                409,
                "donation_capability_disabled",
            )
        assert await self.next_number() is None
        assert (
            await self.db.fetchval(
                "SELECT count(*) FROM donation WHERE action_id = ANY($1::uuid[])",
                [self.data.alpha, self.data.beta, self.data.gamma],
            )
            == 0
        )

    async def a_donation_takes_a_number_and_a_pledge_document(self) -> None:
        listing = await self.listing()
        assert listing["receivingBodyName"] == self.data.body().legal_name
        donation = await self.create("first")
        assert donation["number"] == self.data.number(1)
        assert donation["status"] == "pledged"
        assert donation["source"] == "admin"
        assert donation["pledgedMinor"] == 5000
        assert donation["currency"] == "EUR"
        assert donation["commitmentId"] is None
        assert donation["payment"] is None
        assert donation["cancellation"] is None
        assert donation["paymentWithdrawals"] == []
        assert donation["pledgeDeliveries"] == []
        assert donation["replayed"] is False
        assert donation["donor"]["countryCode"] == "DE"
        assert donation["createdByDisplayName"] == f"Charity {self.data.tag}"
        pledge_document = donation["pledgeDocument"]
        assert pledge_document["status"] == "pending"
        assert pledge_document["version"] == 1
        assert pledge_document["createdAt"] is not None
        assert pledge_document["availableAt"] is None
        assert pledge_document["filename"] is None
        assert await self.next_number() == 2
        donation_id = UUID(donation["id"])
        assert (
            await self.db.fetchval(
                "SELECT kind FROM document_number WHERE number = $1",
                donation["number"],
            )
            == "donation"
        )
        document = await self.db.fetchrow(
            "SELECT id, document_type, status, version FROM generated_document "
            "WHERE donation_id = $1",
            donation_id,
        )
        assert document is not None
        assert document["document_type"] == "donation_pledge_pdf"
        assert document["status"] == "pending"
        assert str(document["id"]) == donation["pledgeDocument"]["id"]
        assert (
            await self.db.fetchval(
                "SELECT count(*) FROM outbox_event "
                "WHERE aggregate_type = 'generated_document' AND aggregate_id = $1 "
                "AND event_type = 'document.render.requested.v1'",
                document["id"],
            )
            == 1
        )
        audit = await self.db.fetchrow(
            "SELECT actor_user_id, payload FROM audit_event "
            "WHERE event_type = 'donation_pledged' AND action_id = $1",
            self.data.alpha,
        )
        assert audit is not None
        assert audit["actor_user_id"] == self.data.users["charity"]
        assert self.data.tag not in str(audit["payload"]).replace(
            donation["number"], ""
        ), "the audit entry carries donor data"
        # The document the worker renders: what was true when it was issued.
        pool = await asyncpg.create_pool(
            os.environ["CORE_DATABASE_URL"], min_size=1, max_size=1
        )
        try:
            pledge = await AsyncpgDonationRepository(pool).donation_pledge_document(
                donation_id
            )
        finally:
            await pool.close()
        assert pledge is not None
        assert pledge.number == donation["number"]
        assert pledge.body.legal_name == self.data.body().legal_name
        assert pledge.body.pledge_text == PLEDGE_TEXT
        assert pledge.donor.name == donation["donor"]["name"]
        assert pledge.amount.amount_minor == 5000
        assert pledge.action_purpose == "Jugendhilfe im Ort"
        # It is listed with the documents of the action, under its number.
        documents = await self.charity.get(
            f"/api/v1/actions/{self.data.alpha}/documents"
        )
        assert documents.status_code == 200, documents.text
        listed = next(
            item
            for item in documents.json()["items"]
            if item["document"]["id"] == str(document["id"])
        )
        assert listed["document"]["documentType"] == "donation_pledge_pdf"
        assert listed["document"]["donationId"] == donation["id"]
        assert listed["documentNumber"] == donation["number"]
        assert listed["buyerDisplayName"] == donation["donor"]["name"]

    async def replay_and_refusals_use_no_number(self) -> None:
        key = self.key()
        body = self.draft("replay", amount=12000)
        first = await self.charity.post(self.path(self.data.alpha), body, key)
        assert first.status_code == 201, first.text
        self.donations["replay"] = first.json()
        assert first.json()["number"] == self.data.number(2)
        again = await self.charity.post(self.path(self.data.alpha), body, key)
        assert again.status_code == 201, again.text
        assert again.json()["id"] == first.json()["id"]
        assert again.json()["replayed"] is True
        self.error(
            await self.charity.post(
                self.path(self.data.alpha), self.draft("replay", amount=12001), key
            ),
            409,
            "idempotency_conflict",
        )
        for amount in (99, 100_000_001):
            refused = await self.charity.post(
                self.path(self.data.alpha),
                self.draft("small", amount=amount),
                self.key(),
            )
            assert refused.status_code == 422, refused.text
        bad_mail = self.draft("mail")
        bad_mail["donor"] = {**bad_mail["donor"], "email": "keine-adresse"}  # type: ignore[dict-item]
        self.error(
            await self.charity.post(self.path(self.data.alpha), bad_mail, self.key()),
            422,
            "donation_donor_email_invalid",
        )
        self.error(
            await self.charity.post(
                self.path(self.data.alpha), self.draft("no_key"), "x"
            ),
            422,
            "donation_idempotency_key_invalid",
        )
        self.error(
            await self.stale.post(
                self.path(self.data.alpha), self.draft("stale"), self.key()
            ),
            401,
            "fresh_login_required",
        )
        assert await self.next_number() == 3

    async def one_series_for_the_installation(self) -> None:
        beta = await self.create("beta", action=self.data.beta)
        assert beta["number"] == self.data.number(3)
        names = [f"race_{index}" for index in range(4)]
        created = await asyncio.gather(
            *(
                self.create(
                    name, action=self.data.beta if index % 2 else self.data.alpha
                )
                for index, name in enumerate(names)
            )
        )
        assert sorted(item["number"] for item in created) == [
            self.data.number(serial) for serial in range(4, 8)
        ]
        assert await self.next_number() == 8

    async def who_may_read_record_and_send(self) -> None:
        finance = self.sessions["finance"]
        listing = await self.listing(session=finance)
        assert listing["mayManage"] is False
        assert listing["maySend"] is False
        assert len(listing["items"]) == 4
        self.error(
            await finance.post(
                self.path(self.data.alpha), self.draft("finance"), self.key()
            ),
            403,
            "donation_manage_required",
        )
        for suffix, body in (
            ("/payment", {"amountMinor": 5000, "receivedOn": self.today.isoformat()}),
            ("/payment/withdrawal", {"reason": REASON}),
            ("/cancellation", {"reason": REASON}),
        ):
            self.error(
                await finance.post(
                    self.path(self.data.alpha, "first", suffix), body, self.key()
                ),
                403,
                "donation_manage_required",
            )
        self.error(
            await finance.post(
                self.path(self.data.alpha, "first", "/pledge/deliveries"),
                None,
                self.key(),
            ),
            403,
            "donation_delivery_required",
        )
        # The global finance manager records and books, and sends nothing.
        manager = self.sessions["finance_manager"]
        listing = await self.listing(session=manager)
        assert listing["mayManage"] is True
        assert listing["maySend"] is False
        booked = await self.create("by_manager", session=manager)
        assert booked["createdByDisplayName"] == f"Finance_Manager {self.data.tag}"
        self.error(
            await manager.post(
                self.path(self.data.alpha, "by_manager", "/pledge/deliveries"),
                None,
                self.key(),
            ),
            403,
            "donation_delivery_required",
        )
        for name in ("acquirer", "outsider"):
            self.error(
                await self.sessions[name].get(self.path(self.data.alpha)),
                403,
                "donation_read_required",
            )
        for suffix, body in (
            ("/payment", {"amountMinor": 5000, "receivedOn": self.today.isoformat()}),
            ("/payment/withdrawal", {"reason": REASON}),
            ("/cancellation", {"reason": REASON}),
        ):
            self.error(
                await self.stale.post(
                    self.path(self.data.alpha, "first", suffix), body, self.key()
                ),
                401,
                "fresh_login_required",
            )

    async def one_payment_of_any_amount(self) -> None:
        self.error(
            await self.pay("first", 5000, self.today + timedelta(days=1)),
            422,
            "donation_payment_future_date",
        )
        self.error(
            await self.pay("first", 5000, self.today - timedelta(days=1)),
            422,
            "donation_payment_before_pledge",
        )
        self.error(
            await self.charity.post(
                self.path(self.data.alpha, "first", "/payment/withdrawal"),
                {"reason": REASON},
                self.key(),
            ),
            422,
            "donation_payment_not_recorded",
        )
        # More than pledged: what arrived is what counts.
        key = self.key()
        body: dict[str, object] = {
            "amountMinor": 6000,
            "receivedOn": self.today.isoformat(),
            "note": "  Überweisung   vom Geschäftskonto ",
        }
        path = self.path(self.data.alpha, "first", "/payment")
        paid = await self.charity.post(path, body, key)
        assert paid.status_code == 201, paid.text
        assert paid.json()["status"] == "paid"
        assert paid.json()["pledgedMinor"] == 5000
        payment = paid.json()["payment"]
        assert payment["amountMinor"] == 6000
        assert payment["receivedOn"] == self.today.isoformat()
        assert payment["note"] == "Überweisung vom Geschäftskonto"
        assert payment["recordedByDisplayName"] == f"Charity {self.data.tag}"
        replay = await self.charity.post(path, body, key)
        assert replay.status_code == 201, replay.text
        assert replay.json()["replayed"] is True
        self.error(
            await self.pay("first", 1000), 422, "donation_payment_already_recorded"
        )
        self.error(
            await self.charity.post(
                self.path(self.data.alpha, "first", "/cancellation"),
                {"reason": REASON},
                self.key(),
            ),
            422,
            "donation_paid",
        )
        withdrawn = await self.charity.post(
            self.path(self.data.alpha, "first", "/payment/withdrawal"),
            {"reason": f"  {REASON}  "},
            self.key(),
        )
        assert withdrawn.status_code == 201, withdrawn.text
        after = withdrawn.json()
        assert after["status"] == "pledged"
        assert after["payment"] is None
        assert len(after["paymentWithdrawals"]) == 1
        history = after["paymentWithdrawals"][0]
        assert history["amountMinor"] == 6000
        assert history["reason"] == REASON
        assert history["note"] == "Überweisung vom Geschäftskonto"
        assert history["withdrawnByDisplayName"] == f"Charity {self.data.tag}"
        # Less than pledged, after the withdrawal.
        less = await self.pay("first", 4000)
        assert less.status_code == 201, less.text
        assert less.json()["status"] == "paid"
        assert less.json()["payment"]["amountMinor"] == 4000
        assert len(less.json()["paymentWithdrawals"]) == 1
        events = await self.db.fetch(
            "SELECT event_type FROM audit_event "
            "WHERE action_id = $1 AND payload ->> 'number' = $2 ORDER BY occurred_at",
            self.data.alpha,
            self.data.number(1),
        )
        assert [item["event_type"] for item in events] == [
            "donation_pledged",
            "donation_payment_recorded",
            "donation_payment_withdrawn",
            "donation_payment_recorded",
        ], events

    async def only_an_unpaid_donation_is_cancelled(self) -> None:
        path = self.path(self.data.alpha, "replay", "/cancellation")
        short = await self.charity.post(path, {"reason": "zu kurz"}, self.key())
        assert short.status_code == 422, short.text
        key = self.key()
        cancelled = await self.charity.post(path, {"reason": REASON}, key)
        assert cancelled.status_code == 201, cancelled.text
        body = cancelled.json()
        assert body["status"] == "cancelled"
        assert body["number"] == self.data.number(2)
        assert body["cancellation"]["reason"] == REASON
        assert body["cancellation"]["cancelledByDisplayName"] == (
            f"Charity {self.data.tag}"
        )
        replay = await self.charity.post(path, {"reason": REASON}, key)
        assert replay.status_code == 201, replay.text
        assert replay.json()["replayed"] is True
        self.error(
            await self.charity.post(path, {"reason": REASON}, self.key()),
            422,
            "donation_already_cancelled",
        )
        self.error(await self.pay("replay", 12000), 422, "donation_cancelled")
        # The number stays used: the next donation takes the next one.
        following = await self.create("after_cancel")
        assert following["number"] == self.data.number(9)

    async def other_actions_cannot_reach_it(self) -> None:
        first = self.donations["first"]["id"]
        base = f"/api/v1/actions/{self.data.beta}/donations/{first}"
        for suffix, body in (
            ("/payment", {"amountMinor": 5000, "receivedOn": self.today.isoformat()}),
            ("/payment/withdrawal", {"reason": REASON}),
            ("/cancellation", {"reason": REASON}),
            ("/pledge/deliveries", None),
        ):
            self.error(
                await self.charity.post(base + suffix, body, self.key()),
                404,
                "donation_not_found",
            )
        record = await self.record("first")
        assert record["status"] == "paid"
        assert record["payment"]["amountMinor"] == 4000

    async def make_available(self, name: str) -> UUID:
        """What the worker does after rendering; no worker runs here."""

        document_id = UUID(self.donations[name]["pledgeDocument"]["id"])
        await self.db.execute(
            """
            UPDATE generated_document
            SET status = 'available', filename = 'Spendenzusage.pdf',
                storage_bucket = 'leonaid', object_key = $2,
                storage_version_id = 'proof', size_bytes = 1200, sha256 = $3,
                render_version = 'donation-pledge-v1+typst-0.13.1',
                available_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            document_id,
            f"proof/{document_id}.pdf",
            "a" * 64,
        )
        return document_id

    async def the_pledge_goes_out_by_mail(self) -> None:
        send = self.path(self.data.alpha, "after_cancel", "/pledge/deliveries")
        self.error(
            await self.charity.post(send, None, self.key()),
            409,
            "donation_pledge_document_not_ready",
        )
        document_id = await self.make_available("after_cancel")
        await self.create("no_mail", email=False)
        await self.make_available("no_mail")
        self.error(
            await self.charity.post(
                self.path(self.data.alpha, "no_mail", "/pledge/deliveries"),
                None,
                self.key(),
            ),
            409,
            "donation_donor_email_missing",
        )
        await self.make_available("replay")
        self.error(
            await self.charity.post(
                self.path(self.data.alpha, "replay", "/pledge/deliveries"),
                None,
                self.key(),
            ),
            409,
            "donation_cancelled",
        )
        self.error(
            await self.stale.post(send, None, self.key()),
            401,
            "fresh_login_required",
        )
        available = (await self.record("after_cancel"))["pledgeDocument"]
        assert available["status"] == "available"
        assert available["availableAt"] is not None
        assert available["filename"] == "Spendenzusage.pdf"
        key = self.key()
        sent = await self.charity.post(send, None, key)
        assert sent.status_code == 201, sent.text
        delivery = sent.json()
        donation = self.donations["after_cancel"]
        assert delivery["donationId"] == donation["id"]
        assert delivery["generatedDocumentId"] == str(document_id)
        assert delivery["recipientEmail"] == donation["donor"]["email"]
        assert delivery["status"] == "queued"
        assert donation["number"] in delivery["subject"]
        assert delivery["subject"].startswith("Spendenzusage ")
        again = await self.charity.post(send, None, key)
        assert again.status_code == 201, again.text
        assert again.json()["id"] == delivery["id"]
        record = await self.record("after_cancel")
        assert [item["id"] for item in record["pledgeDeliveries"]] == [delivery["id"]]
        # The mail job the worker claims: the pledge, its PDF, its donor.
        pool = await asyncpg.create_pool(
            os.environ["CORE_DATABASE_URL"], min_size=1, max_size=1
        )
        try:
            deliveries = AsyncpgInvoiceDeliveryRepository(pool)
            job = await deliveries.job(UUID(delivery["id"]))
            assert job.invoice_id is None
            assert job.document_id == document_id
            assert job.recipient_email == donation["donor"]["email"]
            assert job.subject == delivery["subject"]
            assert donation["number"] in job.text
            assert "keine Rechnung" in job.text
            assert self.data.body().legal_name in job.text
            assert job.filename == "Spendenzusage.pdf"
        finally:
            await pool.close()
        # A pledge delivery is no invoice delivery: the invoice list of the
        # action still reads, and does not carry it.
        invoices = await self.charity.get(f"/api/v1/actions/{self.data.alpha}/invoices")
        assert invoices.status_code == 200, invoices.text
        assert delivery["id"] not in invoices.text
        audit = await self.db.fetchval(
            "SELECT count(*) FROM audit_event "
            "WHERE event_type = 'donation_pledge_delivery_requested' "
            "AND action_id = $1",
            self.data.alpha,
        )
        assert audit == 1

    async def sums_dashboard_and_navigation(self) -> None:
        listing = await self.listing()
        by_status: dict[str, list[dict[str, Any]]] = {}
        for item in listing["items"]:
            by_status.setdefault(item["status"], []).append(item)
        assert len(by_status["paid"]) == 1
        assert len(by_status["cancelled"]) == 1
        open_total = sum(item["pledgedMinor"] for item in by_status["pledged"])
        assert listing["receivedTotalMinor"] == 4000
        assert listing["pledgedOpenTotalMinor"] == open_total
        assert listing["currency"] == "EUR"
        overview = await AsyncpgDashboardRepository._donations(self.db, self.data.alpha)
        assert overview.enabled is True
        assert overview.paid == 1
        assert overview.pledged == len(by_status["pledged"])
        assert overview.received_minor == 4000
        assert overview.pledged_open_minor == open_total
        without = await AsyncpgDashboardRepository._donations(self.db, self.data.gamma)
        assert without.enabled is False
        assert without.received_minor == 0
        for name, expected in (
            ("charity", True),
            ("finance", True),
            ("finance_manager", True),
            ("acquirer", False),
            ("outsider", False),
        ):
            identity = await self.sessions[name].get("/api/v1/identity/me")
            assert identity.status_code == 200, identity.text
            keys = [item["key"] for item in identity.json()["navigation"]]
            assert ("donations" in keys) is expected, (name, keys)
            # The picker of "Spenden": the actions with the capability whose
            # finances the account reads, never one without the capability.
            listed = {
                item["actionId"]: item["actionName"]
                for item in identity.json()["donationActions"]
            }
            assert str(self.data.gamma) not in listed, name
            own = {str(self.data.alpha), str(self.data.beta)} & set(listed)
            assert (
                own
                == {
                    "charity": {str(self.data.alpha), str(self.data.beta)},
                    "finance": {str(self.data.alpha)},
                    "finance_manager": {str(self.data.alpha), str(self.data.beta)},
                    "acquirer": set(),
                    "outsider": set(),
                }[name]
            ), (name, listed)
            if name in ("charity", "finance"):
                assert set(listed) == own, (name, listed)
            if own:
                assert listed[str(self.data.alpha)] == (f"Aktion {self.data.tag} Alpha")
        # The dashboard figure carries its currency.
        dashboard = await self.charity.get(
            f"/api/v1/actions/{self.data.alpha}/dashboard"
        )
        assert dashboard.status_code == 200, dashboard.text
        figure = dashboard.json()["charityAdmin"]["donations"]
        assert figure == {
            "enabled": True,
            "pledged": overview.pledged,
            "paid": 1,
            "receivedMinor": 4000,
            "pledgedOpenMinor": open_total,
            "currency": "EUR",
        }, figure

    async def the_pledge_keeps_the_body_of_its_day(self) -> None:
        """A later legal configuration without the part "Spenden" stops new
        donations and changes nothing about the ones that exist."""

        await self.data.activate(self.db, self.data.without_body)
        try:
            self.error(
                await self.charity.post(
                    self.path(self.data.alpha), self.draft("late"), self.key()
                ),
                409,
                "donation_receiving_body_missing",
            )
            listing = await self.listing()
            assert listing["receivingBodyName"] is None
            assert len(listing["items"]) >= 5
            # Booking what exists still works.
            paid = await self.pay("by_manager", 5000)
            assert paid.status_code == 201, paid.text
            stored = await self.db.fetchval(
                "SELECT pledge_snapshot -> 'body' ->> 'legalName' FROM donation "
                "WHERE id = $1",
                UUID(self.donations["by_manager"]["id"]),
            )
            assert stored == self.data.body().legal_name
        finally:
            await self.data.activate(self.db, self.data.with_body)

    async def a_privacy_erasure_names_and_keeps_donations(self) -> None:
        """A donation is a tax record like an invoice: the subject report
        lists it and the erasure keeps it, with the reason."""

        system = self.sessions["system"]
        donation = self.donations["first"]
        email = donation["donor"]["email"]
        looked_up = await system.post(
            "/api/v1/admin/privacy/lookup", {"email": email.upper()}
        )
        assert looked_up.status_code == 200, looked_up.text
        report = looked_up.json()
        assert report["found"] is True
        references = [
            item for item in report["references"] if item["referenceType"] == "donation"
        ]
        assert references == [
            {
                "id": donation["id"],
                "referenceType": "donation",
                "actionId": str(self.data.alpha),
                "status": "paid",
                "label": f"Spendenzusage {donation['number']}",
            }
        ], references
        before = await self.db.fetchrow(
            "SELECT donor_snapshot, pledge_snapshot, status FROM donation "
            "WHERE id = $1",
            UUID(donation["id"]),
        )
        erased = await system.post(
            "/api/v1/admin/privacy/erasures", {"email": email, "confirmation": email}
        )
        assert erased.status_code == 200, erased.text
        reasons = erased.json()["retentionReasons"]
        assert any("Spenden und ihre Dokumente" in item for item in reasons), reasons
        after = await self.db.fetchrow(
            "SELECT donor_snapshot, pledge_snapshot, status FROM donation "
            "WHERE id = $1",
            UUID(donation["id"]),
        )
        assert after == before
        # A subject without a donation gets no such reason.
        unknown = await system.post(
            "/api/v1/admin/privacy/lookup",
            {"email": f"niemand.{self.data.tag.lower()}@donor.leonaid.invalid"},
        )
        assert unknown.status_code == 200, unknown.text
        assert unknown.json()["found"] is False

    async def stored_donations_are_final(self) -> None:
        first = UUID(self.donations["first"]["id"])
        for statement in (
            "UPDATE donation SET number = number || 'X' WHERE id = $1",
            "UPDATE donation SET pledged_minor = pledged_minor + 1 WHERE id = $1",
            "UPDATE donation SET donor_snapshot = '{}'::jsonb WHERE id = $1",
            "UPDATE donation SET pledge_snapshot = '{}'::jsonb WHERE id = $1",
            "UPDATE donation SET action_id = gen_random_uuid() WHERE id = $1",
            "DELETE FROM donation WHERE id = $1",
            "UPDATE donation_payment_withdrawal SET reason_snapshot = "
            "'eine andere Begründung' WHERE donation_id = $1",
            "DELETE FROM donation_payment_withdrawal WHERE donation_id = $1",
            # A paid donation carries its payment; a pledged one none.
            "UPDATE donation SET received_minor = NULL WHERE id = $1",
            "UPDATE donation SET status = 'cancelled' WHERE id = $1",
        ):
            try:
                async with self.db.transaction():
                    await self.db.execute(statement, first)
            except (
                asyncpg.IntegrityConstraintViolationError,
                asyncpg.RaiseError,
            ):
                continue
            raise AssertionError(f"the stored donation was changed: {statement}")
        # A donation number cannot be taken by another document.
        try:
            async with self.db.transaction():
                await self.db.execute(
                    "INSERT INTO document_number (number, kind) VALUES ($1, 'invoice')",
                    self.data.number(1),
                )
        except asyncpg.UniqueViolationError:
            pass
        else:
            raise AssertionError("a second document took a donation's number")
        issued = await self.db.fetch(
            "SELECT number FROM document_number WHERE left(number, $2) = $1",
            self.data.pledge_prefix,
            len(self.data.pledge_prefix),
        )
        serials = sorted(
            int(item["number"][len(self.data.pledge_prefix) :]) for item in issued
        )
        next_number = await self.next_number()
        assert next_number is not None
        assert serials == list(range(1, next_number)), serials


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
        "donations-api: OK: capability and receiving body, numbers of the"
        " donation series, one payment, withdrawal, cancellation, roles,"
        " pledge mail, sums and navigation proven against PostgreSQL"
    )


def test_donations_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
