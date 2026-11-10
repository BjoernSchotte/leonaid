#!/usr/bin/env python3
"""Buyer mails for internal orders over HTTP: full FastAPI app, real PostgreSQL.

Runs as a contract script in the schema gate (``tools/schema/test.sh``) and,
with ``CORE_DATABASE_URL`` set, under pytest. Proves
specs/mails-documents-donations-push §5.1, §6.1, §6.2 and §6.4:

- every order has an order number;
- the settings row: defaults without a row, manager only, optimistic lock,
  the delivery capability rule, the audit event;
- the confirmation of an order that a member or acquirer entered: only with
  the switch on, only with a buyer address, once when the order becomes
  review-ready (creation, completion of a draft from the PWA queue, manager
  completion), never for a draft and never a second time;
- the cancellation notice with the same rule, and ``buyerMailDue`` on the
  order record;
- the mail status per order and "send again": numbered resend jobs, replay,
  refusals without a stored receipt, the mailbox limit, the erased buyer.

The worker side runs the real ``OrderMailHandler`` with the real reader. The
sender writes the ledger row as ``SmtpMailHandler`` does, and the proof marks
the job as the outbox worker would (completed or dead-lettered).
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

from leonaid.adapters.postgres.order_mails import AsyncpgOrderMailReader
from leonaid.application.order_mails import (
    EVENT_TYPES,
    OrderMailError,
    OrderMailHandler,
    OrderMailKind,
    recipient_sha256,
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

BASE_URL = "https://buyer-mails.leonaid.invalid"
CLUB = "Buyer mail proof Hilfswerk e.V."
CLUB_EMAIL = "kontakt@buyer-mails.leonaid.invalid"
DRIVER_NOTE = "Hofeinfahrt links, Code 4711"
REASON = "Kunde hat telefonisch abgesagt."


def legal_version() -> LegalConfigurationVersion:
    """An active legal configuration as the worker reads it."""

    return LegalConfigurationVersion(
        id=uuid4(),
        version=1,
        configuration=LegalConfigurationDraft(
            issuer=InvoiceIssuerSnapshot(
                legal_name=CLUB,
                street_line_1="Clubweg 1",
                postal_code="86150",
                city="Augsburg",
                country_code="DE",
                tax_identifier="103/999/99999",
                email=CLUB_EMAIL,
            ),
            bank_account_holder=CLUB,
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            tax_treatment=TaxTreatment.SMALL_BUSINESS,
            tax_rate_basis_points=0,
            tax_note="Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.",
            number_prefix="BM26-",
            number_width=4,
            payment_terms_days=14,
            public_order_legal_basis="Art. 6 Abs. 1 lit. b DSGVO (Vertrag).",
            public_order_notice_text=(
                "Wir verarbeiten Ihre Angaben nur zur Abwicklung Ihrer Bestellung."
            ),
            consent_text_version="buyer-mail-proof-v1",
            privacy_contact_email="datenschutz@buyer-mails.leonaid.invalid",
            retention=RetentionSchedule(3650, 1095, 730, 1095, 2190),
            e_invoice_decision=EInvoiceDecision.NOT_REQUIRED,
            tax_evidence_id="TAX-PROOF-1",
            privacy_evidence_id="PRIVACY-PROOF-1",
            e_invoice_evidence_id="EINVOICE-PROOF-1",
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
            "LEONAID_SECRET_KEY": "synthetic-buyer-mail-proof-secret-32-ch",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-buyer-mail-proof-encrypt-32",
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
    """Two actions (one with delivery), an acquirer with one sponsor."""

    USERS = ("acquirer", "charity", "outsider")

    def __init__(self) -> None:
        self.tag = f"bm{uuid4().hex[:10]}"
        self.action = uuid4()
        self.plain_action = uuid4()
        self.offering = uuid4()
        self.company = uuid4()
        self.window = uuid4()
        self.users = {name: uuid4() for name in self.USERS}
        self.tokens = {name: uuid4().hex + uuid4().hex for name in self.USERS}
        start_day = date.today() + timedelta(days=30)
        self.window_starts_at = datetime(
            start_day.year, start_day.month, start_day.day, 7, tzinfo=timezone.utc
        )

    def email(self, name: str) -> str:
        return f"{name}.{self.tag}@buyer.leonaid.invalid"

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
                VALUES ($1, $2, $3, $4, $5, $5, 'Buyer mail proof', $5, $5)
                """,
                uuid4(),
                user_id,
                session_token_digest(self.tokens[name]),
                now + SESSION_LIFETIME,
                now,
            )
        # Written with SQL, so neither action has a buyer-mail settings row:
        # the application must treat a missing row as "all off".
        for action, name, capabilities in (
            (self.action, "Aktion", ("ordering", "acquisition", "delivery")),
            (self.plain_action, "Ohne Lieferung", ("ordering",)),
        ):
            await connection.execute(
                """
                INSERT INTO charity_action (
                    id, carrier_name, name, purpose, status, starts_on, ends_on,
                    archive_slug
                )
                VALUES ($1, 'Buyer mail proof', $2, 'Proof', 'active',
                        '2026-01-01', '2099-12-31', $3)
                """,
                action,
                f"{name} {self.tag}",
                f"buyer-mail-proof-{action}",
            )
            for capability in capabilities:
                await connection.execute(
                    "INSERT INTO charity_action_capability (action_id, capability) "
                    "VALUES ($1, $2)",
                    action,
                    capability,
                )
            await connection.execute(
                "INSERT INTO action_membership (id, action_id, user_id, role) "
                "VALUES ($1, $2, $3, 'charity_admin')",
                uuid4(),
                action,
                self.users["charity"],
            )
        await connection.execute(
            "INSERT INTO action_delivery_configuration (action_id, enabled) "
            "VALUES ($1, true)",
            self.action,
        )
        await connection.execute(
            """
            INSERT INTO action_delivery_window (id, action_id, starts_at, ends_at)
            VALUES ($1, $2, $3, $4)
            """,
            self.window,
            self.action,
            self.window_starts_at,
            self.window_starts_at + timedelta(hours=2),
        )
        await connection.execute(
            "INSERT INTO action_membership (id, action_id, user_id, role) "
            "VALUES ($1, $2, $3, 'acquirer')",
            uuid4(),
            self.action,
            self.users["acquirer"],
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
        pool: asyncpg.Pool[Any],
    ) -> None:
        self.client = client
        self.data = data
        self.db = connection
        self.pool = pool
        self.orders = f"/api/v1/actions/{data.action}/commitments"
        self.settings = f"/api/v1/actions/{data.action}/buyer-mail-configuration"
        self.sent: list[ClaimedOutboxEvent] = []

    # -- HTTP -----------------------------------------------------------

    def headers(self, user: str, key: str | None = None) -> dict[str, str]:
        headers = {
            "Cookie": f"{SESSION_COOKIE_NAME}={self.data.tokens[user]}",
            "Origin": BASE_URL,
        }
        if key is not None:
            headers["Idempotency-Key"] = key
        return headers

    def key(self, name: str) -> str:
        return f"buyer-mail-proof:{self.data.tag}-{name}"

    async def post(
        self,
        path: str,
        body: dict[str, object] | None,
        key: str | None,
        user: str = "charity",
    ) -> httpx.Response:
        return await self.client.post(path, headers=self.headers(user, key), json=body)

    async def put(
        self, path: str, body: dict[str, object], user: str = "charity"
    ) -> httpx.Response:
        return await self.client.put(path, headers=self.headers(user), json=body)

    async def get(self, path: str, user: str = "charity") -> httpx.Response:
        return await self.client.get(path, headers=self.headers(user))

    @staticmethod
    def error(response: httpx.Response) -> str:
        payload = response.json()
        assert isinstance(payload, dict) and isinstance(payload.get("error"), dict)
        return str(payload["error"]["code"])

    def address(self, name: str) -> dict[str, object]:
        return {
            "recipientName": f"Bäckerei {self.data.tag} {name}",
            "streetLine1": "Marktplatz 3",
            "postalCode": "86150",
            "city": "Augsburg",
            "countryCode": "DE",
        }

    def body(
        self,
        name: str,
        *,
        ready: bool = True,
        source: str = "acquisition",
        email: bool = True,
        captured_at: datetime | None = None,
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "source": source,
            "readyForReview": ready,
            "buyer": {
                "partyKind": "company",
                "twentyId": str(self.data.company),
                "displayName": f"Bäckerei {self.data.tag} {name}",
                "email": self.data.email(name) if email else None,
            },
            "invoiceRecipient": {**self.address(name), "email": None},
            "lines": [
                {
                    "offeringId": str(self.data.offering),
                    "quantity": 2,
                    "unit": "box",
                    "quotedUnitPriceMinor": 3600,
                }
            ],
        }
        if ready:
            body["deliveryRecipient"] = self.address(name)
            body["deliveryWindowId"] = str(self.data.window)
            body["deliveryContact"] = {
                "name": "Pforte Herr Geheim",
                "phone": "+49 821 999999",
                "driverNote": DRIVER_NOTE,
            }
        if captured_at is not None:
            body["capturedAt"] = captured_at.isoformat()
        return body

    async def order(
        self, name: str, *, user: str = "acquirer", **options: Any
    ) -> dict[str, Any]:
        response = await self.post(
            self.orders, self.body(name, **options), self.key(f"order-{name}"), user
        )
        assert response.status_code == 201, response.text
        return dict(response.json())

    async def record(self, order_id: str) -> dict[str, Any]:
        response = await self.get(self.orders)
        assert response.status_code == 200, response.text
        return next(
            dict(item)
            for item in response.json()["items"]
            if item["commitment"]["id"] == order_id
        )

    async def mails(self, order_id: str) -> dict[str, dict[str, Any]]:
        response = await self.get(f"{self.orders}/{order_id}/buyer-mails")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["commitmentId"] == order_id
        return {str(item["kind"]): dict(item) for item in payload["mails"]}

    async def resend(
        self, order_id: str, kind: str, key: str | None, user: str = "charity"
    ) -> httpx.Response:
        return await self.post(
            f"{self.orders}/{order_id}/buyer-mails/{kind}/resend", None, key, user
        )

    async def cancel(self, order_id: str) -> None:
        version = (await self.record(order_id))["commitment"][
            "deliveryCompletionVersion"
        ]
        response = await self.post(
            f"{self.orders}/{order_id}/cancellation",
            {"expectedVersion": version, "reason": REASON},
            f"buyer-mail-proof:{uuid4()}",
        )
        assert response.status_code == 201, response.text

    async def switch(self, internal_order_mails: bool) -> dict[str, Any]:
        current = (await self.get(self.settings)).json()
        response = await self.put(
            self.settings,
            {
                "expectedRevision": current["revision"],
                "internalOrderMails": internal_order_mails,
                "deliveryDayMail": current["deliveryDayMail"],
                "deliveryDaySendTime": current["deliveryDaySendTime"],
            },
        )
        assert response.status_code == 200, response.text
        return dict(response.json())

    # -- database and worker ---------------------------------------------

    async def jobs(self, order_id: str, kind: OrderMailKind) -> list[asyncpg.Record]:
        return list(
            await self.db.fetch(
                "SELECT id, idempotency_key, payload, status FROM outbox_event "
                "WHERE aggregate_type = 'commitment' AND aggregate_id = $1 "
                "AND event_type = $2 ORDER BY created_at, idempotency_key",
                UUID(order_id),
                EVENT_TYPES[kind],
            )
        )

    async def keys(self, order_id: str, kind: OrderMailKind) -> list[str]:
        return [str(job["idempotency_key"]) for job in await self.jobs(order_id, kind)]

    async def receipts(self, key: str) -> int:
        return int(
            await self.db.fetchval(
                "SELECT count(*) FROM command_receipt WHERE idempotency_key = $1",
                key,
            )
        )

    async def work(
        self, order_id: str, kind: OrderMailKind, *, recipient_limit: int = 10
    ) -> str:
        """Run the newest waiting job of the kind as the outbox worker does."""

        proof = self

        class LedgerSender:
            """Records the mail and the ledger row like ``SmtpMailHandler``."""

            async def handle(self, event: ClaimedOutboxEvent) -> None:
                await proof.db.execute(
                    "INSERT INTO mail_delivery (id, outbox_event_id,"
                    " idempotency_key, message_id, recipient_sha256, status)"
                    " VALUES ($1, $2, $3, $4, $5, 'sent')",
                    uuid4(),
                    event.id,
                    event.idempotency_key,
                    f"<{uuid4().hex}@buyer-mails.leonaid.invalid>",
                    recipient_sha256(str(event.payload["to"])),
                )
                proof.sent.append(event)

        class Legal:
            async def active_configuration(self) -> LegalConfigurationVersion:
                return legal_version()

        waiting = [
            job for job in await self.jobs(order_id, kind) if job["status"] == "pending"
        ]
        assert len(waiting) == 1, waiting
        job = waiting[0]
        handler = OrderMailHandler(
            kind,
            reader=AsyncpgOrderMailReader(self.pool),
            legal_configuration=Legal(),
            sender=LedgerSender(),
            recipient_limit=recipient_limit,
        )
        try:
            await handler.handle(
                ClaimedOutboxEvent(
                    id=job["id"],
                    aggregate_type="commitment",
                    aggregate_id=UUID(order_id),
                    event_type=EVENT_TYPES[kind],
                    idempotency_key=job["idempotency_key"],
                    payload=json.loads(job["payload"]),
                    attempts=1,
                    claim_token=uuid4(),
                    claimed_by="buyer-mail-proof",
                )
            )
        except OrderMailError as error:
            assert error.retryable is False, error.code
            await self.db.execute(
                "UPDATE outbox_event SET status = 'dead_letter', "
                "attempts = attempts + 1, "
                "dead_lettered_at = CURRENT_TIMESTAMP, last_error_code = $2 "
                "WHERE id = $1",
                job["id"],
                error.code,
            )
            return error.code
        await self.db.execute(
            "UPDATE outbox_event SET status = 'completed', attempts = attempts + 1, "
            "completed_at = CURRENT_TIMESTAMP WHERE id = $1",
            job["id"],
        )
        return "completed"

    # -- the proof ---------------------------------------------------------

    async def run(self) -> None:
        await self.settings_row()
        before = await self.switched_off()
        await self.switch(True)
        ready = await self.confirmation_once_when_review_ready()
        await self.drafts()
        await self.not_requested(before)
        await self.send_again(ready)
        await self.mailbox_limit(ready)
        await self.cancellation(ready)
        await self.erased_buyer()
        # Later proofs share this database: leave no waiting or failed job.
        await self.db.execute(
            "DELETE FROM outbox_event WHERE aggregate_type = 'commitment' "
            "AND aggregate_id IN (SELECT id FROM commitment WHERE action_id = $1)",
            self.data.action,
        )

    async def settings_row(self) -> None:
        initial = await self.get(self.settings)
        assert initial.status_code == 200, initial.text
        assert initial.json() == {
            "actionId": str(self.data.action),
            "internalOrderMails": False,
            "deliveryDayMail": False,
            "deliveryDaySendTime": "07:00",
            "revision": 1,
        }
        assert initial.headers["cache-control"] == "private, no-store"
        for user in ("acquirer", "outsider"):
            assert (await self.get(self.settings, user)).status_code == 403
            refused = await self.put(
                self.settings,
                {
                    "expectedRevision": 1,
                    "internalOrderMails": True,
                    "deliveryDayMail": False,
                    "deliveryDaySendTime": "07:00",
                },
                user,
            )
            assert refused.status_code == 403, refused.text
        unknown = f"/api/v1/actions/{uuid4()}/buyer-mail-configuration"
        assert (await self.get(unknown)).status_code in {403, 404}

        def body(**changes: object) -> dict[str, object]:
            return {
                "expectedRevision": 1,
                "internalOrderMails": False,
                "deliveryDayMail": False,
                "deliveryDaySendTime": "07:00",
                **changes,
            }

        for send_time in ("04:59", "12:01", "25:00", "7:00", "07:00:30"):
            invalid = await self.put(self.settings, body(deliveryDaySendTime=send_time))
            assert invalid.status_code == 422, (send_time, invalid.text)
        stale = await self.put(self.settings, body(expectedRevision=2))
        assert stale.status_code == 409, stale.text
        assert self.error(stale) == "buyer_mail_configuration_conflict"
        # The delivery-day mail needs the delivery capability.
        plain = f"/api/v1/actions/{self.data.plain_action}/buyer-mail-configuration"
        no_delivery = await self.put(plain, body(deliveryDayMail=True))
        assert no_delivery.status_code == 409, no_delivery.text
        assert self.error(no_delivery) == "buyer_mail_delivery_required"
        assert (await self.get(plain)).json()["revision"] == 1

        saved = await self.put(
            self.settings, body(deliveryDayMail=True, deliveryDaySendTime="06:30")
        )
        assert saved.status_code == 200, saved.text
        assert saved.json() == {
            "actionId": str(self.data.action),
            "internalOrderMails": False,
            "deliveryDayMail": True,
            "deliveryDaySendTime": "06:30",
            "revision": 2,
        }
        again = await self.put(self.settings, body())
        assert again.status_code == 409, again.text
        audit = await self.db.fetchrow(
            "SELECT actor_user_id, payload FROM audit_event WHERE action_id = $1 "
            "AND event_type = 'buyer_mail_configuration_changed'",
            self.data.action,
        )
        assert audit is not None
        assert audit["actor_user_id"] == self.data.users["charity"]
        assert json.loads(audit["payload"]) == {
            "previous": {
                "internalOrderMails": False,
                "deliveryDayMail": False,
                "deliveryDaySendTime": "07:00",
            },
            "current": {
                "internalOrderMails": False,
                "deliveryDayMail": True,
                "deliveryDaySendTime": "06:30",
            },
        }

    async def switched_off(self) -> dict[str, Any]:
        """Without the switch an internal order sends nothing."""

        order = await self.order("before")
        # Every order has an order number, whatever its source (§5.1).
        assert order["publicReference"] == f"LA-{UUID(order['id']).hex.upper()}"
        assert order["source"] == "acquisition"
        assert await self.keys(order["id"], OrderMailKind.CONFIRMATION) == []
        assert (await self.record(order["id"]))["buyerMailDue"] is False
        assert await self.mails(order["id"]) == {
            "confirmation": {
                "kind": "confirmation",
                "state": "not_due",
                "sentAt": None,
                "reason": "switched_off",
                "canResend": False,
            }
        }
        return order

    async def confirmation_once_when_review_ready(self) -> dict[str, Any]:
        order = await self.order("ready")
        key = f"order-confirmation-mail:{order['id']}"
        assert await self.keys(order["id"], OrderMailKind.CONFIRMATION) == [key]
        payload = json.loads(
            (await self.jobs(order["id"], OrderMailKind.CONFIRMATION))[0]["payload"]
        )
        # Ids and links only: no address waits in the queue.
        assert payload == {
            "actionId": str(self.data.action),
            "commitmentId": order["id"],
            "campaignUrl": f"{BASE_URL}/archive/buyer-mail-proof-{self.data.action}",
            "privacyUrl": f"{BASE_URL}/datenschutz",
            "imprintUrl": f"{BASE_URL}/impressum",
        }
        # The replay of the lost answer writes no second job.
        replay = await self.post(
            self.orders, self.body("ready"), self.key("order-ready"), "acquirer"
        )
        assert replay.status_code == 201 and replay.json()["replayed"] is True
        assert await self.keys(order["id"], OrderMailKind.CONFIRMATION) == [key]
        assert (await self.record(order["id"]))["buyerMailDue"] is True
        assert (await self.mails(order["id"]))["confirmation"]["state"] == "queued"

        assert await self.work(order["id"], OrderMailKind.CONFIRMATION) == "completed"
        mail = self.sent[-1]
        assert mail.payload["to"] == self.data.email("ready")
        text = str(mail.payload["text"])
        for expected in (
            f"Bestellnummer: {order['publicReference']}",
            f"Ihre Bestellung wurde von einem Mitglied des {CLUB} für Sie erfasst.",
            f"schreiben Sie uns bitte an {CLUB_EMAIL}.",
            "- Krapfenbox: 2 Boxen (48 Stück) × 36,00 € = 72,00 €",
            f"Datenschutzerklärung: {BASE_URL}/datenschutz",
        ):
            assert expected in text, expected
        # Nothing about the driver or the delivery contact reaches the buyer.
        for forbidden in (DRIVER_NOTE, "Pforte", "999999"):
            assert forbidden not in text, forbidden
        status = (await self.mails(order["id"]))["confirmation"]
        assert status["state"] == "sent" and status["canResend"] is True
        assert status["reason"] is None
        assert datetime.fromisoformat(status["sentAt"]) <= datetime.now(timezone.utc)

        # An order of the web admin ("admin") follows the same rule.
        admin = await self.order("admin", user="charity", source="admin")
        assert len(await self.keys(admin["id"], OrderMailKind.CONFIRMATION)) == 1
        # No address, no mail.
        silent = await self.order("silent", email=False)
        assert await self.keys(silent["id"], OrderMailKind.CONFIRMATION) == []
        assert (await self.mails(silent["id"]))["confirmation"]["reason"] == "no_email"
        assert (await self.record(silent["id"]))["buyerMailDue"] is False
        return order

    async def drafts(self) -> None:
        """A draft sends nothing; it is confirmed once when it is completed."""

        captured = datetime.now(timezone.utc) - timedelta(hours=3)
        draft = await self.order("draft", ready=False, captured_at=captured)
        assert draft["status"] == "draft"
        assert await self.keys(draft["id"], OrderMailKind.CONFIRMATION) == []
        assert (await self.mails(draft["id"]))["confirmation"] == {
            "kind": "confirmation",
            "state": "not_due",
            "sentAt": None,
            "reason": "order_draft",
            "canResend": False,
        }
        assert (await self.record(draft["id"]))["buyerMailDue"] is False
        # The completion comes from the PWA queue (capturedAt) and is sent
        # twice: the order becomes review-ready once and is confirmed once.
        completion: dict[str, object] = {
            "deliveryRecipient": self.address("draft"),
            "deliveryWindowId": str(self.data.window),
            "capturedAt": (captured + timedelta(hours=1)).isoformat(),
        }
        path = f"{self.orders}/{draft['id']}/complete"
        for expected_replay in (False, True):
            done = await self.post(path, completion, self.key("complete"), "acquirer")
            assert done.status_code == 200, done.text
            assert done.json()["status"] == "review_ready"
            assert done.json()["replayed"] is expected_replay
        assert await self.keys(draft["id"], OrderMailKind.CONFIRMATION) == [
            f"order-confirmation-mail:{draft['id']}"
        ]
        assert await self.work(draft["id"], OrderMailKind.CONFIRMATION) == "completed"
        assert self.sent[-1].payload["to"] == self.data.email("draft")

        # A manager completes another draft with delivery and billing data.
        managed = await self.order("managed", ready=False)
        completion_path = f"{self.orders}/{managed['id']}/delivery-completion"

        def manager_body(version: str, street: str) -> dict[str, object]:
            return {
                "expectedVersion": version,
                "invoiceRecipient": {**self.address("managed"), "email": None},
                "deliveryRecipient": {
                    **self.address("managed"),
                    "streetLine1": street,
                },
                "deliveryWindowId": str(self.data.window),
            }

        first = await self.post(
            completion_path,
            manager_body(managed["deliveryCompletionVersion"], "Marktplatz 3"),
            self.key("managed-1"),
        )
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "review_ready"
        keys = await self.keys(managed["id"], OrderMailKind.CONFIRMATION)
        assert keys == [f"order-confirmation-mail:{managed['id']}"]
        assert await self.work(managed["id"], OrderMailKind.CONFIRMATION) == "completed"
        # A later change of the address sends no second confirmation.
        second = await self.post(
            completion_path,
            manager_body(first.json()["deliveryCompletionVersion"], "Marktplatz 4"),
            self.key("managed-2"),
        )
        assert second.status_code == 200, second.text
        assert await self.keys(managed["id"], OrderMailKind.CONFIRMATION) == keys
        assert (await self.mails(managed["id"]))["confirmation"]["state"] == "sent"

    async def not_requested(self, before: dict[str, Any]) -> None:
        """An order from before the switch has no mail to send again."""

        status = (await self.mails(before["id"]))["confirmation"]
        assert status == {
            "kind": "confirmation",
            "state": "not_due",
            "sentAt": None,
            "reason": "not_requested",
            "canResend": False,
        }
        key = self.key("resend-before")
        refused = await self.resend(before["id"], "confirmation", key)
        assert refused.status_code == 409, refused.text
        assert self.error(refused) == "buyer_mail_resend_not_allowed"
        assert await self.receipts(key) == 0
        # Cancelling it now tells the buyer: the switch is on.
        assert (await self.record(before["id"]))["buyerMailDue"] is True

    async def send_again(self, order: dict[str, Any]) -> None:
        order_id = str(order["id"])
        base = f"order-confirmation-mail:{order_id}"
        for user in ("acquirer", "outsider"):
            forbidden = await self.resend(
                order_id, "confirmation", self.key(f"resend-{user}"), user
            )
            assert forbidden.status_code == 403, forbidden.text
            listing = await self.get(f"{self.orders}/{order_id}/buyer-mails", user)
            assert listing.status_code == 403, listing.text
        no_key = await self.resend(order_id, "confirmation", None)
        assert no_key.status_code == 422, no_key.text
        assert (
            await self.resend(order_id, "delivery", self.key("resend-kind"))
        ).status_code == 422
        missing = await self.resend(
            str(uuid4()), "confirmation", self.key("resend-missing")
        )
        assert missing.status_code == 404, missing.text
        # An open order has no cancellation notice.
        early = await self.resend(order_id, "cancellation", self.key("resend-early"))
        assert early.status_code == 409, early.text
        assert self.error(early) == "buyer_mail_not_applicable"
        assert await self.keys(order_id, OrderMailKind.CONFIRMATION) == [base]

        key = self.key("resend-1")
        for _ in range(2):
            # The second call is the replay of a lost answer.
            accepted = await self.resend(order_id, "confirmation", key)
            assert accepted.status_code == 202, accepted.text
            assert accepted.json()["state"] == "queued"
            assert accepted.json()["canResend"] is False
            assert accepted.json()["sentAt"] is not None
        assert await self.keys(order_id, OrderMailKind.CONFIRMATION) == [
            base,
            f"{base}:resend:1",
        ]
        other = await self.resend(str(order_id), "cancellation", key)
        assert other.status_code == 409, other.text
        # While it waits, another resend is refused and leaves no receipt.
        waiting_key = self.key("resend-waiting")
        waiting = await self.resend(order_id, "confirmation", waiting_key)
        assert waiting.status_code == 409, waiting.text
        assert self.error(waiting) == "buyer_mail_already_queued"
        assert await self.receipts(waiting_key) == 0
        audit = await self.db.fetch(
            "SELECT actor_user_id, payload FROM audit_event WHERE entity_id = $1 "
            "AND event_type = 'order_mail_resent'",
            UUID(order_id),
        )
        assert [json.loads(row["payload"]) for row in audit] == [
            {"kind": "confirmation", "resend": 1}
        ]
        assert audit[0]["actor_user_id"] == self.data.users["charity"]

        before = len(self.sent)
        assert await self.work(order_id, OrderMailKind.CONFIRMATION) == "completed"
        assert len(self.sent) == before + 1
        assert self.sent[-1].idempotency_key == f"{base}:resend:1"
        assert self.sent[-1].payload["to"] == self.data.email("ready")
        # The key that was refused before works now and takes the next number.
        second = await self.resend(order_id, "confirmation", waiting_key)
        assert second.status_code == 202, second.text
        assert (await self.keys(order_id, OrderMailKind.CONFIRMATION))[-1] == (
            f"{base}:resend:2"
        )
        # Two parallel resends of one order never take the same number: one
        # is queued, the other finds the mail waiting.
        assert await self.work(order_id, OrderMailKind.CONFIRMATION) == "completed"
        parallel = await asyncio.gather(
            *(
                self.resend(order_id, "confirmation", self.key(f"parallel-{index}"))
                for index in range(2)
            )
        )
        assert sorted(response.status_code for response in parallel) == [202, 409]
        assert (await self.keys(order_id, OrderMailKind.CONFIRMATION))[-1] == (
            f"{base}:resend:3"
        )

    async def mailbox_limit(self, order: dict[str, Any]) -> None:
        """A resend counts for the limit per mailbox like every order mail."""

        order_id = str(order["id"])
        # Three mails went to this mailbox in the last hour; the limit is 3.
        outcome = await self.work(
            order_id, OrderMailKind.CONFIRMATION, recipient_limit=3
        )
        assert outcome == "order_mail_recipient_limit"
        status = (await self.mails(order_id))["confirmation"]
        assert status["state"] == "failed"
        assert status["reason"] == "recipient_limit"
        assert status["canResend"] is True
        assert status["sentAt"] is not None
        retry = await self.resend(order_id, "confirmation", self.key("after-limit"))
        assert retry.status_code == 202, retry.text
        assert await self.work(order_id, OrderMailKind.CONFIRMATION) == "completed"
        assert self.sent[-1].idempotency_key.endswith(":resend:4")

    async def cancellation(self, ready: dict[str, Any]) -> None:
        order_id = str(ready["id"])
        await self.cancel(order_id)
        notice = f"order-cancellation-mail:{order_id}"
        assert await self.keys(order_id, OrderMailKind.CANCELLATION) == [notice]
        record = await self.record(order_id)
        assert record["buyerMailDue"] is False
        mails = await self.mails(order_id)
        assert list(mails) == ["confirmation", "cancellation"]
        # A confirmation of a cancelled order is not sent again.
        assert mails["confirmation"]["state"] == "sent"
        assert mails["confirmation"]["canResend"] is False
        assert mails["cancellation"]["state"] == "queued"
        refused = await self.resend(order_id, "confirmation", self.key("cancelled"))
        assert refused.status_code == 409, refused.text
        assert self.error(refused) == "buyer_mail_not_due"
        assert await self.work(order_id, OrderMailKind.CANCELLATION) == "completed"
        text = str(self.sent[-1].payload["text"])
        assert self.sent[-1].payload["to"] == self.data.email("ready")
        assert f"Bestellnummer: {ready['publicReference']}" in text
        assert "storniert. Sie wird nicht geliefert." in text
        for forbidden in (REASON, DRIVER_NOTE, "Pforte"):
            assert forbidden not in text, forbidden
        again = await self.resend(order_id, "cancellation", self.key("notice-again"))
        assert again.status_code == 202, again.text
        assert (await self.keys(order_id, OrderMailKind.CANCELLATION))[-1] == (
            f"{notice}:resend:1"
        )

        # A draft was never confirmed: its cancellation is no news.
        draft = await self.order("cancelled-draft", ready=False)
        assert (await self.record(draft["id"]))["buyerMailDue"] is False
        await self.cancel(draft["id"])
        assert await self.keys(draft["id"], OrderMailKind.CANCELLATION) == []
        assert {
            kind: status["reason"]
            for kind, status in (await self.mails(draft["id"])).items()
        } == {"confirmation": "order_draft", "cancellation": "order_draft"}

        # Switched off again: neither a notice nor a waiting confirmation.
        late = await self.order("late")
        assert len(await self.keys(late["id"], OrderMailKind.CONFIRMATION)) == 1
        await self.switch(False)
        assert (await self.record(late["id"]))["buyerMailDue"] is False
        before = len(self.sent)
        assert await self.work(late["id"], OrderMailKind.CONFIRMATION) == "completed"
        assert len(self.sent) == before
        assert (await self.mails(late["id"]))["confirmation"] == {
            "kind": "confirmation",
            "state": "skipped",
            "sentAt": None,
            "reason": "switched_off",
            "canResend": False,
        }
        await self.cancel(late["id"])
        assert await self.keys(late["id"], OrderMailKind.CANCELLATION) == []
        await self.switch(True)

    async def erased_buyer(self) -> None:
        """After a privacy erasure nothing is sent, not even again."""

        order = await self.order("erased")
        assert await self.work(order["id"], OrderMailKind.CONFIRMATION) == "completed"
        accepted = await self.resend(order["id"], "confirmation", self.key("erased-1"))
        assert accepted.status_code == 202, accepted.text
        # The erasure clears the address while the resend waits.
        await self.db.execute(
            "UPDATE commitment SET customer_snapshot = customer_snapshot"
            " || '{\"email\": null}'::jsonb WHERE id = $1",
            UUID(order["id"]),
        )
        before = len(self.sent)
        assert await self.work(order["id"], OrderMailKind.CONFIRMATION) == "completed"
        assert len(self.sent) == before
        status = (await self.mails(order["id"]))["confirmation"]
        assert status["state"] == "skipped" and status["reason"] == "no_email"
        assert status["canResend"] is False
        refused = await self.resend(order["id"], "confirmation", self.key("erased-2"))
        assert refused.status_code == 409, refused.text
        assert (await self.record(order["id"]))["buyerMailDue"] is False


async def main() -> None:
    os.environ.pop("LEONAID_SURVEY_ERASURE_ARCHIVE_DIR", None)
    data = Fixture()
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=3
    )
    try:
        await data.create(connection)
        app = create_app(settings())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE_URL
            ) as client:
                await Proof(client, data, connection, pool).run()
    finally:
        await pool.close()
        await connection.close()
    print(
        "buyer-mails-api: OK: order numbers, settings row, confirmation once "
        "per internal order, cancellation notice, mail status, resend, "
        "mailbox limit and erased buyer proven against PostgreSQL"
    )


def test_buyer_mails_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
