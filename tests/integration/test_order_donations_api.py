#!/usr/bin/env python3
"""Extra donation with an order: full app, real PostgreSQL.

Runs as a contract script in the schema gate (``tools/schema/test.sh``) and,
with ``CORE_DATABASE_URL`` set, under pytest. Proves spec §8.6 (ADR-0016):

- the form switch and what it needs (order form, capability `donations`),
  and that the capability cannot go while the switch is on;
- an order carries a donation amount only when the form offers one;
- a binding internal order creates the donation with its number at once, a
  draft keeps only the amount until it is completed, and an order with a
  donation needs a complete invoice recipient to become binding;
- the order total never includes the donation;
- a public order creates the donation and queues its pledge mail by itself,
  and the order confirmation names the donation;
- cancelling an order cancels its unpaid donation by default, never a paid
  one.

The legal configuration is one row for the installation: the proof activates
its own version and puts the previous state back at the end.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.order_mails import AsyncpgOrderMailReader
from leonaid.adapters.postgres.public_orders import AsyncpgPublicOrderRepository
from leonaid.application.commitments import CommitmentLineDraft
from leonaid.application.errors import Conflict
from leonaid.application.order_mails import (
    OrderMailKind,
    OrderMailLinks,
    render_order_confirmation,
)
from leonaid.application.public_orders import (
    PublicOrderCrmOutcome,
    PublicOrderDraft,
    PublicOrderPartyDraft,
    ResolvedPublicParty,
)
from leonaid.adapters.postgres.legal_configuration import (
    AsyncpgLegalConfigurationRepository,
)
from leonaid.configuration import Settings
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.calendar import local_day
from leonaid.domain.commitments import (
    BuyerSnapshot,
    CommitmentPartyKind,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
)
from leonaid.domain.donations import (
    ExemptionNoticeKind,
    ReceiptSigning,
    ReceivingBody,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)
from leonaid.entrypoints.fastapi.platform import create_app

BASE_URL = "https://order-donations.leonaid.invalid"
REASON = "Sponsor hat die Bestellung zurückgezogen"


def settings() -> Settings:
    return Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-order-donation-secret-32-chars",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-order-donation-encrypt-32-ch",
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
    """An action whose orders may carry a donation, and one without."""

    def __init__(self) -> None:
        self.tag = f"OD{uuid4().hex[:8].upper()}"
        self.alias = f"orderdonation{self.tag.lower()}"
        self.action = uuid4()
        # Orders, no `donations` capability.
        self.plain = uuid4()
        # Still a draft: its capabilities can change.
        self.draft = uuid4()
        self.offerings = {
            self.action: uuid4(),
            self.plain: uuid4(),
            self.draft: uuid4(),
        }
        self.company = uuid4()
        self.user = uuid4()
        self.token = uuid4().hex + uuid4().hex
        self.legal_version = uuid4()
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
            pledge_prefix=f"{self.tag}S-",
            receipt_prefix=f"{self.tag}Z-",
            number_width=4,
            pledge_text=(
                "Ihre Spende ist freiwillig. Sie erhalten dafür keine "
                "Gegenleistung. Dieses Schreiben ist keine Rechnung."
            ),
            receipt_liability_text=(
                "Hinweis: Wer vorsätzlich oder grob fahrlässig eine unrichtige "
                "Zuwendungsbestätigung erstellt, haftet für die entgangene Steuer."
            ),
        )

    def number(self, serial: int) -> str:
        return f"{self.tag}S-{serial:04d}"

    async def create(self, connection: asyncpg.Connection[Any]) -> None:
        now = datetime.now(timezone.utc)
        await connection.execute(
            "INSERT INTO user_account (id, email, display_name, status) "
            "VALUES ($1, $2, $3, 'active')",
            self.user,
            f"charity.{self.tag.lower()}@leonaid.invalid",
            f"Charity {self.tag}",
        )
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at, last_seen_at,
                fresh_login_at, device_hint, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $5, 'Order donation proof', $5, $5)
            """,
            uuid4(),
            self.user,
            session_token_digest(self.token),
            now + SESSION_LIFETIME,
            now,
        )
        self.previous_state = await connection.fetchrow(
            "SELECT active_version_id, draft_version_id FROM legal_configuration_state"
        )
        await self._legal_version(connection)
        for action_id, name, capabilities, status in (
            (self.action, "Spenden", ("offerings", "ordering", "donations"), "active"),
            (self.plain, "Ohne", ("offerings", "ordering"), "active"),
            (self.draft, "Entwurf", ("offerings", "ordering", "donations"), "draft"),
        ):
            await connection.execute(
                """
                INSERT INTO charity_action (
                    id, carrier_name, name, purpose, status, starts_on, ends_on,
                    archive_slug, publication_starts_at, publication_ends_at
                )
                VALUES ($1, 'Order donation proof', $2, 'Jugendhilfe im Ort',
                        $4, '2026-01-01', '2099-12-31', $3,
                        CASE WHEN $4 = 'active'
                             THEN CURRENT_TIMESTAMP - interval '1 day' END,
                        CASE WHEN $4 = 'active'
                             THEN CURRENT_TIMESTAMP + interval '30 days' END)
                """,
                action_id,
                f"Aktion {self.tag} {name}",
                f"order-donation-{action_id}",
                status,
            )
            await connection.execute(
                "INSERT INTO beneficiary (id, action_id, organization_name, "
                "public_description, sort_order) VALUES ($1, $2, 'Proof', 'Proof', 0)",
                uuid4(),
                action_id,
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
                self.user,
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
            capability_list = sorted(capabilities)
            await connection.execute(
                """
                INSERT INTO action_template_snapshot (
                    action_id, template_key, template_version, display_name,
                    configuration
                )
                VALUES ($1, 'blank', 1, 'Leere Aktion', $2::jsonb)
                """,
                action_id,
                json.dumps(
                    {
                        "capabilities": capability_list,
                        "offerings": [],
                        "orderForm": None,
                    }
                ),
            )
            await connection.execute(
                """
                INSERT INTO order_form_configuration (
                    id, action_id, form_key, status, title, introduction,
                    submit_label, require_company_name, require_contact_name,
                    require_email, require_phone, require_delivery_address,
                    require_billing_address, allow_message
                )
                VALUES ($1, $2, 'bestellung', 'active', 'Bestellung', 'Bestellen',
                        'Bestellen', false, true, true, false, false, true, true)
                """,
                uuid4(),
                action_id,
            )
        await connection.execute(
            "INSERT INTO public_action_alias (alias, action_id, is_primary, enabled, "
            "campaign_redirect) VALUES ($1, $2, true, true, false)",
            self.alias,
            self.action,
        )

    async def remove_legal_configuration(
        self, connection: asyncpg.Connection[Any]
    ) -> None:
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

    async def _legal_version(self, connection: asyncpg.Connection[Any]) -> None:
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
            VALUES ($1, $2, 'Order donation Hilfswerk e.V.', 'Clubweg 1', '86150',
                    'Augsburg', 'DE', '103/999/99999',
                    'finanzen@order-donation.leonaid.invalid',
                    'Order donation Hilfswerk e.V.', 'DE89370400440532013000',
                    'COBADEFFXXX', 'small_business', 0,
                    'Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.', $3, 4, 14,
                    'Vertragserfüllung für den Nachweis.',
                    'Nachweis: Datenschutzhinweis für die Bestellung.',
                    'order-donation-v1',
                    'datenschutz@order-donation.leonaid.invalid',
                    3650, 3650, 730, 3650, 3650, 'pending',
                    'STEUER-OD-1', 'DATENSCHUTZ-OD-1', $4, $5::jsonb)
            """,
            self.legal_version,
            version,
            f"{self.tag}R-",
            self.user,
            json.dumps(self.body().payload()),
        )
        await connection.execute(
            "UPDATE legal_configuration_state SET active_version_id = $1",
            self.legal_version,
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
        self.headers = {"Cookie": f"{SESSION_COOKIE_NAME}={data.token}"}

    @staticmethod
    def key() -> str:
        return f"order-donation:{uuid4()}"

    @staticmethod
    def error(response: httpx.Response, status: int, code: str) -> None:
        assert response.status_code == status, (status, code, response.text)
        assert response.json()["error"]["code"] == code, response.text

    async def get(self, path: str) -> httpx.Response:
        return await self.client.get(path, headers=self.headers)

    async def send(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None,
        key: str | None = None,
    ) -> httpx.Response:
        headers = {**self.headers, "Origin": BASE_URL}
        if key is not None:
            headers["Idempotency-Key"] = key
        return await self.client.request(method, path, headers=headers, json=body)

    def order(
        self,
        name: str,
        *,
        action: UUID | None = None,
        donation: int | None = None,
        ready: bool = True,
        recipient: bool = True,
    ) -> dict[str, object]:
        action = action or self.data.action
        body: dict[str, object] = {
            "source": "admin",
            "readyForReview": ready,
            "buyer": {
                "partyKind": "company",
                "twentyId": str(self.data.company),
                "displayName": f"Bäckerei {self.data.tag} {name}",
                "email": f"{name}.{self.data.tag.lower()}@buyer.leonaid.invalid",
            },
            "invoiceRecipient": (
                {
                    "recipientName": f"Bäckerei {self.data.tag} {name}",
                    "streetLine1": "Marktplatz 3",
                    "postalCode": "86150",
                    "city": "Augsburg",
                    "countryCode": "DE",
                    "email": f"{name}.{self.data.tag.lower()}@buyer.leonaid.invalid",
                }
                if recipient
                else None
            ),
            "lines": [
                {
                    "offeringId": str(self.data.offerings[action]),
                    "quantity": 2,
                    "unit": "box",
                }
            ],
        }
        if donation is not None:
            body["donationAmountMinor"] = donation
        return body

    def orders(self, action: UUID | None = None) -> str:
        return f"/api/v1/actions/{action or self.data.action}/commitments"

    async def record(self, commitment_id: str) -> dict[str, Any]:
        listing = await self.get(self.orders())
        assert listing.status_code == 200, listing.text
        return next(
            dict(item)
            for item in listing.json()["items"]
            if item["commitment"]["id"] == commitment_id
        )

    async def donation_of(self, commitment_id: str) -> asyncpg.Record | None:
        return await self.db.fetchrow(
            "SELECT id, number, status, source, pledged_minor, donor_snapshot, "
            "created_by_user_id FROM donation WHERE commitment_id = $1",
            UUID(commitment_id),
        )

    async def run(self) -> None:
        await self.the_switch_needs_form_and_capability()
        await self.no_donation_while_the_form_does_not_offer_it()
        await self.a_binding_order_creates_the_donation()
        await self.a_draft_keeps_the_amount_until_it_is_completed()
        await self.a_public_order_pledges_and_mails_by_itself()
        await self.cancelling_the_order_cancels_an_unpaid_donation()
        await self.the_capability_stays_while_the_switch_is_on()

    async def the_switch_needs_form_and_capability(self) -> None:
        path = f"/api/v1/actions/{self.data.action}/order-form/donation"
        context = await self.get(
            f"/api/v1/actions/{self.data.action}/commitment-capture"
        )
        assert context.status_code == 200, context.text
        assert context.json()["donationReceivingBody"] is None
        self.error(
            await self.send(
                "PUT",
                f"/api/v1/actions/{self.data.plain}/order-form/donation",
                {"allowDonation": True},
            ),
            409,
            "order_form_donation_capability_missing",
        )
        switched = await self.send("PUT", path, {"allowDonation": True})
        assert switched.status_code == 200, switched.text
        assert switched.json()["orderForm"]["allowDonation"] is True
        again = await self.send("PUT", path, {"allowDonation": True})
        assert again.status_code == 200, again.text
        audits = await self.db.fetchval(
            "SELECT count(*) FROM audit_event WHERE action_id = $1 "
            "AND event_type = 'order_form_donation_changed'",
            self.data.action,
        )
        assert audits == 1
        context = await self.get(
            f"/api/v1/actions/{self.data.action}/commitment-capture"
        )
        assert context.json()["donationReceivingBody"] == self.data.body().legal_name
        # Switching off an action without the capability is always possible.
        off = await self.send(
            "PUT",
            f"/api/v1/actions/{self.data.plain}/order-form/donation",
            {"allowDonation": False},
        )
        assert off.status_code == 200, off.text

    async def no_donation_while_the_form_does_not_offer_it(self) -> None:
        self.error(
            await self.send(
                "POST",
                self.orders(self.data.plain),
                self.order("plain", action=self.data.plain, donation=2500),
                self.key(),
            ),
            409,
            "commitment_donation_not_offered",
        )
        for amount in (99, 1_000_001):
            refused = await self.send(
                "POST", self.orders(), self.order("range", donation=amount), self.key()
            )
            assert refused.status_code == 422, refused.text
        # Without a receiving body the switch has no effect.
        await self.db.execute(
            "UPDATE legal_configuration_state SET active_version_id = NULL"
        )
        try:
            context = await self.get(
                f"/api/v1/actions/{self.data.action}/commitment-capture"
            )
            assert context.json()["donationReceivingBody"] is None
            self.error(
                await self.send(
                    "POST",
                    self.orders(),
                    self.order("nobody", donation=2500),
                    self.key(),
                ),
                409,
                "commitment_donation_not_offered",
            )
        finally:
            await self.db.execute(
                "UPDATE legal_configuration_state SET active_version_id = $1",
                self.data.legal_version,
            )
        assert (
            await self.db.fetchval(
                "SELECT count(*) FROM commitment WHERE action_id = ANY($1::uuid[])",
                [self.data.action, self.data.plain],
            )
            == 0
        )

    async def a_binding_order_creates_the_donation(self) -> None:
        key = self.key()
        body = self.order("ready", donation=2500)
        created = await self.send("POST", self.orders(), body, key)
        assert created.status_code == 201, created.text
        order = created.json()
        self.ready_order = str(order["id"])
        assert order["status"] == "review_ready"
        # The order total is the goods alone.
        assert order["totalMinor"] == 7200
        donation = await self.donation_of(self.ready_order)
        assert donation is not None
        assert donation["number"] == self.data.number(1)
        assert donation["status"] == "pledged"
        assert donation["source"] == "admin"
        assert donation["pledged_minor"] == 2500
        assert donation["created_by_user_id"] == self.data.user
        donor = json.loads(donation["donor_snapshot"])
        # The donor is the order's invoice recipient, linked to the CRM party.
        assert donor["name"] == f"Bäckerei {self.data.tag} ready"
        assert donor["streetLine1"] == "Marktplatz 3"
        assert donor["partyKind"] == "company"
        assert donor["twentyId"] == str(self.data.company)
        # No mail by itself for an internal order: a manager sends the pledge.
        assert (
            await self.db.fetchval(
                "SELECT count(*) FROM invoice_delivery WHERE donation_id = $1",
                donation["id"],
            )
            == 0
        )
        record = await self.record(self.ready_order)
        assert record["donation"] == {
            "pledgedMinor": 2500,
            "donationId": str(donation["id"]),
            "number": self.data.number(1),
            "status": "pledged",
        }
        # The donation page links it to its order.
        donations = await self.get(f"/api/v1/actions/{self.data.action}/donations")
        assert donations.status_code == 200, donations.text
        assert donations.json()["donorSearch"] is False
        listed = donations.json()["items"][0]
        assert listed["commitmentId"] == self.ready_order
        assert listed["source"] == "admin"
        # Replay: the same order, no second donation; other content, refused.
        replay = await self.send("POST", self.orders(), body, key)
        assert replay.status_code in (200, 201), replay.text
        assert replay.json()["id"] == self.ready_order
        self.error(
            await self.send(
                "POST", self.orders(), self.order("ready", donation=2600), key
            ),
            409,
            "idempotency_conflict",
        )
        assert (
            await self.db.fetchval(
                "SELECT count(*) FROM donation WHERE action_id = $1", self.data.action
            )
            == 1
        )
        # An order without a donation has none.
        plain = await self.send("POST", self.orders(), self.order("none"), self.key())
        assert plain.status_code == 201, plain.text
        assert (await self.record(str(plain.json()["id"])))["donation"] is None

    async def a_draft_keeps_the_amount_until_it_is_completed(self) -> None:
        draft = await self.send(
            "POST",
            self.orders(),
            self.order("draft", donation=1500, ready=False),
            self.key(),
        )
        assert draft.status_code == 201, draft.text
        draft_id = str(draft.json()["id"])
        assert draft.json()["status"] == "draft"
        assert await self.donation_of(draft_id) is None
        record = await self.record(draft_id)
        assert record["donation"] == {
            "pledgedMinor": 1500,
            "donationId": None,
            "number": None,
            "status": None,
        }
        completed = await self.send(
            "POST", f"{self.orders()}/{draft_id}/complete", {}, self.key()
        )
        assert completed.status_code == 200, completed.text
        donation = await self.donation_of(draft_id)
        assert donation is not None
        assert donation["number"] == self.data.number(2)
        assert donation["pledged_minor"] == 1500
        # Without an invoice recipient the order cannot become binding: the
        # recipient is the donor. Neither the order nor a number changes.
        incomplete = await self.send(
            "POST",
            self.orders(),
            self.order("incomplete", donation=1500, ready=False, recipient=False),
            self.key(),
        )
        assert incomplete.status_code == 201, incomplete.text
        incomplete_id = str(incomplete.json()["id"])
        self.error(
            await self.send(
                "POST", f"{self.orders()}/{incomplete_id}/complete", {}, self.key()
            ),
            422,
            "commitment_donation_recipient_required",
        )
        assert (await self.record(incomplete_id))["commitment"]["status"] == "draft"
        assert await self.donation_of(incomplete_id) is None
        self.error(
            await self.send(
                "POST",
                self.orders(),
                self.order("direct", donation=1500, recipient=False),
                self.key(),
            ),
            422,
            "commitment_donation_recipient_required",
        )
        assert (
            await self.db.fetchval(
                "SELECT next_number FROM document_series "
                "WHERE kind = 'donation' AND prefix = $1",
                f"{self.data.tag}S-",
            )
            == 3
        )

    def public_draft(self, donation: int | None) -> PublicOrderDraft:
        email = f"public.{self.data.tag.lower()}@buyer.leonaid.invalid"
        return PublicOrderDraft(
            party=PublicOrderPartyDraft(
                company_name=None,
                given_name="Petra",
                family_name=f"Privat {self.data.tag}",
                email=email,
            ),
            delivery_recipient=DeliveryRecipientSnapshot(
                recipient_name=f"Petra Privat {self.data.tag}",
                street_line_1="Gartenweg 4",
                postal_code="12345",
                city="Musterstadt",
            ),
            invoice_recipient=InvoiceRecipientSnapshot(
                recipient_name=f"Petra Privat {self.data.tag}",
                street_line_1="Gartenweg 4",
                postal_code="12345",
                city="Musterstadt",
                email=email,
            ),
            lines=(
                CommitmentLineDraft(
                    offering_id=self.data.offerings[self.data.action],
                    quantity=1,
                    unit=OfferingUnit.BOX,
                    quoted_unit_price_minor=3600,
                ),
            ),
            message=None,
            privacy_acknowledged=True,
            binding_order_confirmed=True,
            privacy_notice_version="order-donation-v1",
            donation_amount_minor=donation,
        )

    async def record_public(self, draft: PublicOrderDraft) -> str:
        """What the public endpoint does after the CRM resolved the buyer."""

        repository = AsyncpgPublicOrderRepository(self.pool)
        key = f"public-order:{uuid4()}"
        request_hash = draft.request_hash(
            action_id=self.data.action, public_alias=self.data.alias
        )
        now = datetime.now(timezone.utc)
        async with repository.order_command(
            lock_key=key, idempotency_key=key, request_hash=request_hash
        ) as command:
            result = await command.record_order(
                action_id=self.data.action,
                public_alias=self.data.alias,
                party=ResolvedPublicParty(
                    buyer=BuyerSnapshot(
                        party_kind=CommitmentPartyKind.PERSON,
                        twenty_id=uuid4(),
                        display_name=draft.invoice_recipient.recipient_name,
                        email=draft.party.email,
                    ),
                    contact_twenty_id=None,
                    outcome=PublicOrderCrmOutcome.CREATED,
                ),
                draft=draft,
                idempotency_key=key,
                request_hash=request_hash,
                request_id=f"order-donation-{uuid4()}",
                occurred_at=now,
            )
            await command.complete(result)
        return str(result.commitment.id)

    async def a_public_order_pledges_and_mails_by_itself(self) -> None:
        try:
            self.public_draft(50)
        except DomainInvariantError as error:
            assert error.code == "public_order_donation_amount_invalid"
        else:
            raise AssertionError("a donation below 1,00 € was accepted")
        order_id = await self.record_public(self.public_draft(5000))
        donation = await self.donation_of(order_id)
        assert donation is not None
        assert donation["number"] == self.data.number(3)
        assert donation["source"] == "public_form"
        assert donation["created_by_user_id"] is None
        assert (
            await self.db.fetchval(
                "SELECT total_minor FROM commitment WHERE id = $1", UUID(order_id)
            )
            == 3600
        )
        # The pledge mail is queued in the order's transaction, for a PDF
        # that is still being rendered, and nobody of the club asked for it.
        delivery = await self.db.fetchrow(
            """
            SELECT delivery.requested_by_user_id, delivery.recipient_email_snapshot,
                   delivery.subject_snapshot, document.status, event.status AS job
            FROM invoice_delivery AS delivery
            JOIN generated_document AS document
              ON document.id = delivery.generated_document_id
            JOIN outbox_event AS event ON event.id = delivery.outbox_event_id
            WHERE delivery.donation_id = $1
            """,
            donation["id"],
        )
        assert delivery is not None
        assert delivery["requested_by_user_id"] is None
        assert delivery["recipient_email_snapshot"] == (
            f"public.{self.data.tag.lower()}@buyer.leonaid.invalid"
        )
        assert delivery["subject_snapshot"].startswith(
            f"Spendenzusage {self.data.number(3)} · "
        )
        assert delivery["status"] == "pending"
        assert delivery["job"] == "pending"
        # The donation page shows that delivery.
        donations = await self.get(f"/api/v1/actions/{self.data.action}/donations")
        listed = next(
            item
            for item in donations.json()["items"]
            if item["id"] == str(donation["id"])
        )
        assert len(listed["pledgeDeliveries"]) == 1
        assert listed["source"] == "public_form"
        # The order confirmation names the donation in its own paragraph.
        facts = await AsyncpgOrderMailReader(self.pool).facts(
            UUID(order_id), OrderMailKind.CONFIRMATION
        )
        assert facts is not None and facts.donation is not None
        legal = await AsyncpgLegalConfigurationRepository(
            self.pool
        ).active_configuration()
        assert legal is not None
        mail = render_order_confirmation(
            facts,
            legal,
            OrderMailLinks(
                campaign_url=None,
                privacy_url=BASE_URL + "/datenschutz",
                imprint_url=BASE_URL + "/impressum",
            ),
        )
        assert "Ihre Spende\n" in mail.text
        assert (
            f"Sie haben zusätzlich eine Spende von 50,00 € an "
            f"{self.data.body().legal_name} zugesagt."
        ) in mail.text.replace("\n", " ")
        assert f"Spendenzusage {self.data.number(3)}" in mail.text
        assert "in einer eigenen E-Mail" in mail.text
        # A form that does not offer a donation refuses the amount, and the
        # order is not stored.
        await self.db.execute(
            "UPDATE order_form_configuration SET allow_donation = false "
            "WHERE action_id = $1",
            self.data.action,
        )
        try:
            before = await self.db.fetchval("SELECT count(*) FROM commitment")
            try:
                await self.record_public(self.public_draft(5000))
            except Conflict as refused:
                assert refused.code == "public_order_donation_not_offered"
            else:
                raise AssertionError("a form without the switch took a donation")
            assert await self.db.fetchval("SELECT count(*) FROM commitment") == before
            without = await self.record_public(self.public_draft(None))
            assert await self.donation_of(without) is None
        finally:
            await self.db.execute(
                "UPDATE order_form_configuration SET allow_donation = true "
                "WHERE action_id = $1",
                self.data.action,
            )

    async def cancel(self, commitment_id: str, **extra: object) -> httpx.Response:
        record = await self.record(commitment_id)
        return await self.send(
            "POST",
            f"{self.orders()}/{commitment_id}/cancellation",
            {
                "expectedVersion": record["commitment"]["deliveryCompletionVersion"],
                "reason": REASON,
                **extra,
            },
            self.key(),
        )

    async def cancelling_the_order_cancels_an_unpaid_donation(self) -> None:
        # Default: the unpaid donation goes with the order.
        cancelled = await self.cancel(self.ready_order)
        assert cancelled.status_code in (200, 201), cancelled.text
        donation = await self.donation_of(self.ready_order)
        assert donation is not None and donation["status"] == "cancelled"
        reason = await self.db.fetchval(
            "SELECT cancel_reason FROM donation WHERE id = $1", donation["id"]
        )
        assert reason == REASON
        assert (await self.record(self.ready_order))["donation"]["status"] == (
            "cancelled"
        )
        # Opt out: the donation stays.
        kept = await self.send(
            "POST", self.orders(), self.order("kept", donation=2000), self.key()
        )
        assert kept.status_code == 201, kept.text
        kept_id = str(kept.json()["id"])
        response = await self.cancel(kept_id, cancelDonation=False)
        assert response.status_code in (200, 201), response.text
        kept_donation = await self.donation_of(kept_id)
        assert kept_donation is not None and kept_donation["status"] == "pledged"
        # A paid donation is never cancelled with the order.
        paid = await self.send(
            "POST", self.orders(), self.order("paid", donation=3000), self.key()
        )
        assert paid.status_code == 201, paid.text
        paid_id = str(paid.json()["id"])
        paid_donation = await self.donation_of(paid_id)
        assert paid_donation is not None
        booked = await self.send(
            "POST",
            f"/api/v1/actions/{self.data.action}/donations/"
            f"{paid_donation['id']}/payment",
            {
                "amountMinor": 3000,
                "receivedOn": local_day(datetime.now(timezone.utc)).isoformat(),
            },
            self.key(),
        )
        assert booked.status_code == 201, booked.text
        response = await self.cancel(paid_id)
        assert response.status_code in (200, 201), response.text
        still = await self.donation_of(paid_id)
        assert still is not None and still["status"] == "paid"

    async def the_capability_stays_while_the_switch_is_on(self) -> None:
        """Capabilities change only in draft or planning; the form switch
        keeps the capability it needs."""

        base = f"/api/v1/actions/{self.data.draft}"
        on = await self.send(
            "PUT", f"{base}/order-form/donation", {"allowDonation": True}
        )
        assert on.status_code == 200, on.text
        action = await self.get(base)
        assert action.status_code == 200, action.text
        body = {
            "revision": action.json()["revision"],
            "capabilities": ["offerings", "ordering"],
        }
        self.error(
            await self.send("PUT", f"{base}/capabilities", body),
            422,
            "order_form_donation_capability_missing",
        )
        off = await self.send(
            "PUT", f"{base}/order-form/donation", {"allowDonation": False}
        )
        assert off.status_code == 200, off.text
        assert off.json()["orderForm"]["allowDonation"] is False
        removed = await self.send("PUT", f"{base}/capabilities", body)
        assert removed.status_code == 200, removed.text
        assert removed.json()["capabilities"] == ["offerings", "ordering"]


async def main() -> None:
    os.environ.pop("LEONAID_SURVEY_ERASURE_ARCHIVE_DIR", None)
    data = Fixture()
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=2
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
        await data.remove_legal_configuration(connection)
        await pool.close()
        await connection.close()
    print(
        "order-donations-api: OK: form switch, donation with internal and "
        "public orders, pledge mail by itself, confirmation paragraph and "
        "cancellation proven against PostgreSQL"
    )


def test_order_donations_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
