"""Public HTTP/transaction proof. Only the external CRM port is a recording fake."""

import asyncio
import json
from dataclasses import replace
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.delivery import AsyncpgDeliveryRepository
from leonaid.adapters.postgres.legal_configuration import (
    AsyncpgLegalConfigurationRepository,
)
from leonaid.adapters.postgres.public_orders import AsyncpgPublicOrderRepository
from leonaid.application.crm import CompanyData, CompanyRecord, PersonData, PersonRecord
from leonaid.application.public_orders import PublicOrderService, PublicOrderTokenCodec
from leonaid.domain.identity import AccountStatus, IdentityPrincipal, UserAccount
from tools.delivery.http_configuration import http_app


class RecordingCrm:
    """Fail on unexpected CRM operations; support existing company/contact paths."""

    def __init__(self):
        self.company = CompanyRecord(uuid4(), CompanyData(name="HTTP Test Company"))
        self.person = PersonRecord(
            uuid4(),
            PersonData(
                "HTTP",
                "Customer",
                email="http@example.invalid",
                company_twenty_id=self.company.twenty_id,
            ),
        )
        self.calls = []
        self.before_search = None
        self.create_new = False

    async def search_companies(self, query, *, correlation_id):
        self.calls.append("search_companies")
        if self.before_search:
            await self.before_search()
        return () if self.create_new else (self.company,)

    async def search_people(self, *, given_name, family_name, correlation_id):
        self.calls.append("search_people")
        return () if self.create_new else (self.person,)

    async def list_companies(self, *, correlation_id):
        self.calls.append("list_companies")
        return ()

    async def get_company(self, identifier, *, correlation_id):
        self.calls.append("get_company")
        return None

    async def get_person(self, identifier, *, correlation_id):
        self.calls.append("get_person")
        return None

    async def create_company(self, identifier, data, *, correlation_id):
        self.calls.append("create_company")
        self.company = CompanyRecord(identifier, data)
        return self.company, None

    async def create_person(self, identifier, data, *, correlation_id):
        self.calls.append("create_person")
        self.person = PersonRecord(identifier, data)
        return self.person, None


async def prove_public_http(
    pool: asyncpg.Pool, action_id: UUID, admin_id: UUID
) -> None:
    schedules = AsyncpgDeliveryRepository(pool)
    config = await schedules.get(action_id)
    window = next(w for w in config.windows if not w.retired)
    alias = await pool.fetchval(
        "SELECT alias FROM public_action_alias WHERE action_id=$1 LIMIT 1", action_id
    )
    offering = await pool.fetchval(
        "SELECT id FROM offering WHERE action_id=$1 AND status='active' LIMIT 1",
        action_id,
    )
    secret = "synthetic-delivery-public-http-proof-secret"
    crm = RecordingCrm()
    service = PublicOrderService(
        AsyncpgPublicOrderRepository(pool),
        crm,
        PublicOrderTokenCodec(secret),
        AsyncpgLegalConfigurationRepository(pool),
    )
    app, identity = http_app(
        IdentityPrincipal(
            UserAccount(
                admin_id, "admin@example.invalid", "Test", AccountStatus.ACTIVE
            ),
            frozenset(),
            (),
        )
    )
    identity.current = None  # These are actual anonymous public requests.
    app.state.public_order_service = service
    app.state.public_order_fingerprint_secret = secret
    body = {
        "accessToken": service.issue_access_token(action_id, alias),
        "commandId": str(uuid4()),
        "party": {
            "companyName": "HTTP Test Company",
            "givenName": "HTTP",
            "familyName": "Customer",
            "email": "http@example.invalid",
        },
        "deliveryRecipient": {
            "recipientName": "Warehouse",
            "streetLine1": "Delivery road 2",
            "postalCode": "12345",
            "city": "Test",
            "countryCode": "DE",
        },
        "invoiceRecipient": {
            "recipientName": "Billing",
            "streetLine1": "Invoice road 1",
            "postalCode": "12345",
            "city": "Test",
            "countryCode": "DE",
            "email": "http@example.invalid",
        },
        "deliveryWindowId": str(window.id),
        "deliveryContact": {"name": "Separate delivery contact", "phone": "+49 123-45"},
        "lines": [
            {
                "offeringId": str(offering),
                "quantity": 2,
                "unit": "box",
                "quotedUnitPriceMinor": 3600,
            }
        ],
        "privacyAcknowledged": True,
        "bindingOrderConfirmed": True,
        "privacyNoticeVersion": "krapfentaxi-privacy-v1",
    }
    path = f"/api/v1/public/actions/{alias}/orders"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def post(changes):
            return await client.post(
                path,
                json={**body, **changes},
                headers={"User-Agent": f"synthetic-proof-{uuid4()}"},
            )

        foreign = await pool.fetchval(
            "SELECT id FROM action_delivery_window WHERE action_id<>$1 LIMIT 1",
            action_id,
        )
        for changes in (
            {"deliveryWindowId": None},
            {"deliveryWindowId": str(foreign)},
            {"deliveryRecipient": {**body["deliveryRecipient"], "city": ""}},
            {"deliveryContact": {"name": "Not\none line"}},
            {"deliveryWindowSnapshot": {"startsAt": "2037-12-04T01:00:00Z"}},
        ):
            response = await post({**changes, "commandId": str(uuid4())})
            assert response.status_code == 422, response.text
            assert not crm.calls
        response = await post({})
        assert response.status_code == 201, response.text
        assert response.headers["cache-control"] == "no-store"
        result = response.json()
        commitment_id = UUID(result["commitmentId"])
        stored = await pool.fetchrow(
            "SELECT * FROM commitment WHERE id=$1", commitment_id
        )
        assert (
            json.loads(stored["delivery_contact_snapshot"]) == body["deliveryContact"]
        )
        assert json.loads(stored["delivery_window_snapshot"]) == window.snapshot(
            config.timezone
        )
        assert (
            json.loads(stored["invoice_recipient_snapshot"])["streetLine1"]
            == "Invoice road 1"
        )
        assert "Separate delivery contact" not in response.text
        assert crm.calls == ["search_companies", "search_people"]

        async def retire(identifier):
            current = await schedules.get(action_id)
            await schedules.save(
                replace(
                    current,
                    windows=tuple(
                        replace(w, retired=True) if w.id == identifier else w
                        for w in current.windows
                    ),
                )
            )

        await retire(window.id)
        replay = await post({})
        assert replay.status_code == 200 and replay.json()["commitmentId"] == str(
            commitment_id
        )
        assert len(crm.calls) == 2
        assert (await post({"deliveryContact": {"name": "Changed"}})).status_code == 409
        assert (await post({"commandId": str(uuid4())})).status_code == 422
        assert len(crm.calls) == 2

        # The incumbent order transaction holds the action/configuration locks
        # across CRM resolution. A concurrent edit must wait, then affect only
        # subsequent orders; awaiting its completion inside CRM would deadlock.
        next_window = next(
            w for w in (await schedules.get(action_id)).windows if not w.retired
        )
        before_count = await pool.fetchval(
            "SELECT count(*) FROM commitment WHERE action_id=$1", action_id
        )

        retirement = None

        async def retire_during_crm():
            nonlocal retirement
            retirement = asyncio.create_task(retire(next_window.id))

            async def wait_for_database_lock():
                while not await pool.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%FOR UPDATE%')"
                ):
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_for_database_lock(), timeout=5)
            assert not retirement.done()

        crm.before_search = retire_during_crm
        raced = await post(
            {"commandId": str(uuid4()), "deliveryWindowId": str(next_window.id)}
        )
        assert raced.status_code == 201, raced.text
        assert (
            await pool.fetchval(
                "SELECT count(*) FROM commitment WHERE action_id=$1", action_id
            )
            == before_count + 1
        )
        crm.before_search = None
        assert retirement is not None
        await asyncio.wait_for(retirement, timeout=5)
        calls_after_race = len(crm.calls)
        rejected = await post(
            {"commandId": str(uuid4()), "deliveryWindowId": str(next_window.id)}
        )
        assert rejected.status_code == 422
        assert len(crm.calls) == calls_after_race

        # Preserve the incumbent new-company address behavior; delivery contact
        # must never become the CRM buyer/contact.
        last_window = next(
            w for w in (await schedules.get(action_id)).windows if not w.retired
        )
        crm.create_new = True
        created = await post(
            {"commandId": str(uuid4()), "deliveryWindowId": str(last_window.id)}
        )
        assert created.status_code == 201, created.text
        assert crm.company.data.address.street_line_1 == "Delivery road 2"
        assert crm.person.data.given_name == "HTTP" and crm.person.data.phone is None
        audit = await pool.fetch(
            "SELECT payload::text AS payload FROM audit_event WHERE action_id=$1",
            action_id,
        )
        assert all("Separate delivery contact" not in row["payload"] for row in audit)
    print(
        "KLF-030 public HTTP PASS: anonymous transport and PostgreSQL, invalid delivery before CRM, immutable snapshots, replay, retirement serialized with booking, existing company-address behavior and contact isolation; CRM is a recording fake"
    )
