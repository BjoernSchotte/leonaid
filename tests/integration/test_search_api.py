#!/usr/bin/env python3
"""Core search over HTTP: full FastAPI app, middleware and real PostgreSQL.

Runs as a contract script in the schema gate (``tools/schema/test.sh``) and,
with ``CORE_DATABASE_URL`` set, under pytest. Every result is opened through
the endpoint behind its admin route to prove the search shows nothing the
account could not read there. Sponsors come from the search index
(``sponsor_search_entry``); the proof also covers the index itself: what the
sync writes, what the nightly pass deletes and what an erasure leaves.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.sponsor_search import (
    AsyncpgSponsorSearchIndex,
    SponsorSearchPrivacyContributor,
    write_sponsor_search_entries,
)
from leonaid.application.crm import CrmPartyKind
from leonaid.application.sponsor_search import PartyKey, SponsorParty
from leonaid.configuration import Settings
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)
from leonaid.entrypoints.fastapi.platform import create_app

BASE_URL = "https://search.leonaid.invalid"


def settings() -> Settings:
    return Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-search-proof-secret-only-32-chars",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-search-proof-encryption-32-chars",
            "LEONAID_PUBLIC_BASE_URL": BASE_URL,
            "LEONAID_ALLOWED_ORIGINS": BASE_URL,
            "TWENTY_BASE_URL": "http://127.0.0.1:9",
            # The acquisition endpoints behind the sponsor hits exist only
            # with a CRM key. The proof opens the ones that read PostgreSQL
            # alone; nothing here reaches Twenty (the address is closed).
            "TWENTY_INTEGRATION_API_KEY": "synthetic-search-proof-crm-key-32-chars",
            "TWENTY_HEALTH_URL": "http://127.0.0.1:9/health",
            "RUSTFS_HEALTH_URL": "http://127.0.0.1:9/health",
            "OBJECT_STORAGE_ENDPOINT_URL": "http://127.0.0.1:9",
            "OBJECT_STORAGE_BUCKET": "leonaid",
            "OBJECT_STORAGE_ACCESS_KEY": "synthetic-proof",
            "OBJECT_STORAGE_SECRET_KEY": "synthetic-proof",
        }
    )


class Fixture:
    """Two actions with an order and an invoice each, and five accounts."""

    def __init__(self) -> None:
        # Lower-case hex keeps the tag free of LIKE wildcards.
        self.tag = f"sq{uuid4().hex[:10]}"
        self.action_a = uuid4()
        self.action_b = uuid4()
        self.wildcard_action = uuid4()
        self.lookalike_action = uuid4()
        # Only public-form orders carry a reference (ck_commitment_public_reference).
        self.reference_a = f"LA-{uuid4().hex.upper()}"
        self.order_a = uuid4()
        self.order_b = uuid4()
        self.invoice_a = uuid4()
        self.invoice_b = uuid4()
        self.users: dict[str, UUID] = {
            name: uuid4()
            for name in ("admin", "charity", "acquirer", "finance", "outsider")
        }
        # Sponsors have their own tag, so the proofs of the other types keep
        # their exact result sets. A second acquirer of B is no member of A.
        self.sponsor_tag = f"sp{uuid4().hex[:10]}"
        self.second_acquirer = uuid4()
        self.companies = {name: uuid4() for name in ("alpha", "beta", "erased")}
        self.person = uuid4()
        # Assignment ids by a short name; see _sponsors().
        self.assignments = {
            name: uuid4()
            for name in (
                "a_open",
                "a_handed_over",
                "a_erased",
                "b_charity",
                "b_second",
                "lookalike",
            )
        }
        self.tokens = {name: uuid4().hex + uuid4().hex for name in self.users}
        self.sessions = {name: uuid4() for name in self.users}

    @property
    def actions(self) -> list[UUID]:
        return [
            self.action_a,
            self.action_b,
            self.wildcard_action,
            self.lookalike_action,
        ]

    def invoice_number(self, suffix: str) -> str:
        return f"{self.tag.upper()}-{suffix}"

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
                VALUES ($1, $2, $3, $4, $5, $5, 'Search proof', $5, $5)
                """,
                self.sessions[name],
                user_id,
                session_token_digest(self.tokens[name]),
                now + SESSION_LIFETIME,
                now,
            )
        await connection.execute(
            "INSERT INTO user_global_role (user_id, role) VALUES ($1, 'system_admin')",
            self.users["admin"],
        )
        names = {
            self.action_a: f"Aktion {self.tag} Alpha",
            self.action_b: f"Aktion {self.tag} Beta",
            self.wildcard_action: f"Aktion {self.tag} 100%_ Rabatt",
            self.lookalike_action: f"Aktion {self.tag} 1000 Rabatt",
        }
        for action_id, name in names.items():
            await connection.execute(
                """
                INSERT INTO charity_action (
                    id, carrier_name, name, purpose, status, starts_on, ends_on,
                    archive_slug
                )
                VALUES ($1, 'Search proof', $2, 'Proof', 'active',
                        '2026-01-01', '2026-12-31', $3)
                """,
                action_id,
                name,
                f"search-proof-{action_id}",
            )
            await connection.execute(
                "INSERT INTO beneficiary "
                "(id, action_id, organization_name, public_description, sort_order) "
                "VALUES ($1, $2, 'Search proof beneficiary', 'Proof', 0)",
                uuid4(),
                action_id,
            )
        for action_id in (self.action_a, self.action_b):
            await connection.execute(
                "INSERT INTO charity_action_capability (action_id, capability) "
                "VALUES ($1, 'invoicing')",
                action_id,
            )
        # The wildcard action has acquisition and no assignment; the
        # lookalike action has an assignment and no acquisition.
        for action_id in (self.action_a, self.action_b, self.wildcard_action):
            await connection.execute(
                "INSERT INTO charity_action_capability (action_id, capability) "
                "VALUES ($1, 'acquisition')",
                action_id,
            )
        memberships = (
            (self.action_a, "charity", "charity_admin"),
            (self.action_b, "charity", "acquirer"),
            (self.action_a, "acquirer", "acquirer"),
            (self.action_a, "finance", "finance_reader"),
            (self.action_b, "outsider", "driver"),
        )
        for action_id, name, role in memberships:
            await connection.execute(
                "INSERT INTO action_membership (id, action_id, user_id, role) "
                "VALUES ($1, $2, $3, $4)",
                uuid4(),
                action_id,
                self.users[name],
                role,
            )
        for action_id, order_id, invoice_id, suffix in (
            (self.action_a, self.order_a, self.invoice_a, "A1"),
            (self.action_b, self.order_b, self.invoice_b, "B1"),
        ):
            await self._order_with_invoice(
                connection, action_id, order_id, invoice_id, suffix
            )
        await self._sponsors(connection)

    def sponsor_name(self, suffix: str) -> str:
        return f"Sponsor {self.sponsor_tag} {suffix}"

    @property
    def sponsor_city(self) -> str:
        return f"Ort{self.sponsor_tag}"

    async def _sponsors(self, connection: asyncpg.Connection[Any]) -> None:
        """Assignments of three companies and one person, and their index."""

        await connection.execute(
            "INSERT INTO user_account (id, email, display_name, status) "
            "VALUES ($1, $2, 'Second Acquirer', 'active')",
            self.second_acquirer,
            f"second.{self.second_acquirer.hex}@leonaid.invalid",
        )
        for action_id, user_id in (
            (self.action_b, self.second_acquirer),
            (self.lookalike_action, self.users["acquirer"]),
        ):
            await connection.execute(
                "INSERT INTO action_membership (id, action_id, user_id, role) "
                "VALUES ($1, $2, $3, 'acquirer')",
                uuid4(),
                action_id,
                user_id,
            )
        acquirer, charity = self.users["acquirer"], self.users["charity"]
        alpha, beta = self.companies["alpha"], self.companies["beta"]
        for name, action_id, company_id, person_id, user_id, status in (
            ("a_open", self.action_a, alpha, None, acquirer, "open"),
            (
                "a_handed_over",
                self.action_a,
                None,
                self.person,
                acquirer,
                "handed_over",
            ),
            (
                "a_erased",
                self.action_a,
                self.companies["erased"],
                None,
                acquirer,
                "open",
            ),
            ("b_charity", self.action_b, beta, None, charity, "contacted"),
            ("b_second", self.action_b, beta, None, self.second_acquirer, "open"),
            ("lookalike", self.lookalike_action, alpha, None, acquirer, "open"),
        ):
            await connection.execute(
                """
                INSERT INTO acquisition_assignment (
                    id, action_id, twenty_company_id, twenty_person_id,
                    acquirer_user_id, status, priority
                )
                VALUES ($1, $2, $3, $4, $5, $6, 0)
                """,
                self.assignments[name],
                action_id,
                company_id,
                person_id,
                user_id,
                status,
            )
        now = datetime.now(timezone.utc)
        await write_sponsor_search_entries(
            connection,
            (
                self.party("alpha", self.sponsor_name("Alpha"), self.sponsor_city),
                self.party("beta", self.sponsor_name("Beta"), "Augsburg"),
                self.party("erased", self.sponsor_name("Erased"), "Augsburg"),
                SponsorParty(
                    PartyKey(CrmPartyKind.PERSON, self.person),
                    f"Petra {self.sponsor_tag}",
                    None,
                ),
            ),
            synced_at=now,
        )
        await connection.execute(
            "UPDATE sponsor_search_entry "
            "SET display_name = NULL, city = NULL, erased_at = $2 "
            "WHERE party_kind = 'company' AND twenty_id = $1",
            self.companies["erased"],
            now,
        )

    def party(self, company: str, name: str, city: str | None) -> SponsorParty:
        return SponsorParty(
            PartyKey(CrmPartyKind.COMPANY, self.companies[company]), name, city
        )

    async def _order_with_invoice(
        self,
        connection: asyncpg.Connection[Any],
        action_id: UUID,
        order_id: UUID,
        invoice_id: UUID,
        suffix: str,
    ) -> None:
        buyer = f"Firma {self.tag} {suffix}"
        reference = self.reference_a if order_id == self.order_a else None
        recipient = {
            "recipientName": buyer,
            "streetLine1": "Werkstraße 1",
            "postalCode": "86150",
            "city": "Augsburg",
            "countryCode": "DE",
            "email": None,
        }
        await connection.execute(
            """
            INSERT INTO commitment (
                id, action_id, twenty_company_id, source, status,
                customer_snapshot, invoice_recipient_snapshot,
                delivery_recipient_snapshot, currency, total_minor,
                idempotency_key, public_reference
            )
            VALUES ($1, $2, $3, $8, 'invoiced', $4::jsonb, $5::jsonb,
                    CASE WHEN $8 = 'public_form' THEN $5::jsonb END,
                    'EUR', 7200, $6, $7)
            """,
            order_id,
            action_id,
            uuid4(),
            json.dumps(
                {
                    "partyKind": "company",
                    "twentyId": str(uuid4()),
                    "displayName": buyer,
                    "email": None,
                }
            ),
            json.dumps(recipient),
            f"search-proof:{order_id}",
            reference,
            "public_form" if reference else "admin",
        )
        offering_id = uuid4()
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
            offering_id,
            action_id,
            f"box-{offering_id.hex[:12]}",
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
            offering_id,
        )
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
                $1, $2, $3, $4, 'issued', CURRENT_TIMESTAMP,
                '2026-11-15', '2026-11-29', 'EUR', 7200, 0, 7200,
                '{"legalName":"Search proof e.V.","streetLine1":"Clubweg 1","postalCode":"86150","city":"Augsburg","countryCode":"DE","taxIdentifier":"103/999/99999","email":"finanzen@leonaid.invalid"}'::jsonb,
                '{"accountHolder":"Search proof e.V.","iban":"DE89370400440532013000","bic":"COBADEFFXXX"}'::jsonb,
                $5::jsonb,
                '[{"description":"Krapfenbox","quantity":2,"unit":"box","unitPriceGrossMinor":3600,"taxRateBasisPoints":0,"netMinor":7200,"taxMinor":0,"grossMinor":7200,"currency":"EUR"}]'::jsonb,
                'small_business', 0,
                'Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.',
                $4, $6, 1, $7, '2026-11-15'
            )
            """,
            invoice_id,
            action_id,
            order_id,
            self.invoice_number(suffix),
            json.dumps(recipient),
            self.users["admin"],
            f"search-proof:{invoice_id}",
        )

    async def remove(self, connection: asyncpg.Connection[Any]) -> None:
        users = [*self.users.values(), self.second_acquirer]
        await connection.execute(
            "DELETE FROM sponsor_search_entry WHERE twenty_id = ANY($1::uuid[])",
            [*self.companies.values(), self.person],
        )
        await connection.execute(
            "DELETE FROM acquisition_assignment_history "
            "WHERE assignment_id = ANY($1::uuid[])",
            list(self.assignments.values()),
        )
        await connection.execute(
            "DELETE FROM acquisition_assignment WHERE action_id = ANY($1::uuid[])",
            self.actions,
        )
        await connection.execute(
            "DELETE FROM invoice WHERE id = ANY($1::uuid[])",
            [self.invoice_a, self.invoice_b],
        )
        await connection.execute(
            "DELETE FROM commitment_line WHERE commitment_id = ANY($1::uuid[])",
            [self.order_a, self.order_b],
        )
        await connection.execute(
            "DELETE FROM commitment WHERE id = ANY($1::uuid[])",
            [self.order_a, self.order_b],
        )
        await connection.execute(
            "DELETE FROM action_membership WHERE user_id = ANY($1::uuid[])", users
        )
        await connection.execute(
            "DELETE FROM user_global_role WHERE user_id = ANY($1::uuid[])", users
        )
        await connection.execute(
            "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])", users
        )
        await connection.execute(
            "DELETE FROM user_account WHERE id = ANY($1::uuid[])", users
        )
        await connection.execute(
            "DELETE FROM offering WHERE action_id = ANY($1::uuid[])", self.actions
        )
        await connection.execute(
            "DELETE FROM beneficiary WHERE action_id = ANY($1::uuid[])", self.actions
        )
        await connection.execute(
            "DELETE FROM charity_action_capability WHERE action_id = ANY($1::uuid[])",
            self.actions,
        )
        await connection.execute(
            "DELETE FROM charity_action WHERE id = ANY($1::uuid[])", self.actions
        )


class Session:
    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        self.client = client
        self.headers = {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}

    async def get(self, path: str, **params: object) -> httpx.Response:
        return await self.client.get(path, headers=self.headers, params=params)

    async def search(self, q: str, **params: object) -> list[dict[str, str]]:
        response = await self.get("/api/v1/search", q=q, **params)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        results = response.json()["results"]
        assert isinstance(results, list)
        return results


def kinds(results: list[dict[str, str]]) -> set[tuple[str, str]]:
    return {(item["type"], item["id"]) for item in results}


async def assert_readable_where_it_points(
    session: Session, results: list[dict[str, str]]
) -> None:
    """Each result opens through the API endpoint behind its admin route."""

    for item in results:
        href, kind, item_id = item["href"], item["type"], item["id"]
        if kind == "action":
            assert href == f"/admin/actions/{item_id}"
            detail = await session.get(f"/api/v1/actions/{item_id}")
            assert detail.status_code == 200, detail.text
        elif kind in {"order", "invoice"}:
            route = "orders" if kind == "order" else "invoices"
            endpoint = "commitments" if kind == "order" else "invoices"
            target = urlsplit(href)
            assert target.path == f"/admin/{route}", href
            query = parse_qs(target.query)
            action_ids = query.get("action", [])
            assert len(action_ids) == 1, href
            if kind == "invoice":
                # The invoice list view opens the record in its pane.
                assert query.get("open") == [item_id], href
            listing = await session.get(f"/api/v1/actions/{action_ids[0]}/{endpoint}")
            assert listing.status_code == 200, listing.text
            record = "commitment" if kind == "order" else "invoice"
            assert item_id in {entry[record]["id"] for entry in listing.json()["items"]}
        elif kind == "member":
            assert href == f"/admin/members?open={item_id}"
            member = await session.get(f"/api/v1/admin/members/{item_id}")
            assert member.status_code == 200, member.text
        elif kind == "sponsor":
            # The id is the assignment. The web pipeline opens its detail
            # (?open=), the acquisition app its sponsor (?assignment=).
            target = urlsplit(href)
            query = parse_qs(target.query)
            action_ids = query.get("action", [])
            assert len(action_ids) == 1, href
            if target.path == "/admin/acquisition":
                assert query.get("open") == [item_id], href
            else:
                assert target.path == "/app/sponsors", href
                assert query.get("assignment") == [item_id], href
            detail = await session.get(
                f"/api/v1/actions/{action_ids[0]}/acquisition/assignments/{item_id}"
            )
            assert detail.status_code == 200, detail.text
            assert detail.json()["assignment"]["id"] == item_id
        else:
            raise AssertionError(f"unexpected result type {kind}")


async def prove(
    client: httpx.AsyncClient,
    data: Fixture,
    connection: asyncpg.Connection[Any],
) -> None:
    tag = data.tag
    anonymous = await client.get("/api/v1/search", params={"q": tag})
    assert anonymous.status_code == 401, anonymous.text

    admin = Session(client, data.tokens["admin"])
    for params in (
        {"q": "a"},
        {"q": "x" * 81},
        {"q": "  "},
        {"q": tag, "limit": 0},
        {"q": tag, "limit": 21},
    ):
        invalid = await client.get(
            "/api/v1/search", headers=admin.headers, params=params
        )
        assert invalid.status_code == 422, (params, invalid.text)
        assert invalid.json()["error"]["code"] in {
            "request_invalid",
            "search_query_invalid",
        }

    everything = await admin.search(tag, limit=20)
    assert kinds(everything) >= {
        ("action", str(data.action_a)),
        ("action", str(data.action_b)),
        ("order", str(data.order_a)),
        ("order", str(data.order_b)),
        ("invoice", str(data.invoice_a)),
        ("invoice", str(data.invoice_b)),
        *(("member", str(user_id)) for user_id in data.users.values()),
    }
    await assert_readable_where_it_points(admin, everything)
    assert len(await admin.search(tag, limit=3)) == 3
    assert len(await admin.search(tag)) == 8

    # Charity admin of A, only acquirer in B: nothing of B except members of A.
    charity = Session(client, data.tokens["charity"])
    charity_results = await charity.search(tag, limit=20)
    assert {kind for kind, _id in kinds(charity_results)} == {
        "action",
        "order",
        "invoice",
        "member",
    }
    assert kinds(charity_results) == {
        ("action", str(data.action_a)),
        ("order", str(data.order_a)),
        ("invoice", str(data.invoice_a)),
        *(
            ("member", str(data.users[name]))
            for name in ("charity", "acquirer", "finance")
        ),
    }
    await assert_readable_where_it_points(charity, charity_results)
    invoice_a = next(item for item in charity_results if item["type"] == "invoice")
    assert invoice_a["title"] == data.invoice_number("A1")
    assert invoice_a["context"] == f"Firma {tag} A1 · Aktion {tag} Alpha"
    order_a = next(item for item in charity_results if item["type"] == "order")
    assert order_a["context"] == (
        f"{data.reference_a} · Aktion {tag} Alpha · Fakturiert"
    )
    # The public reference finds its order.
    by_reference = await charity.search(data.reference_a.lower())
    assert kinds(by_reference) == {("order", str(data.order_a))}
    assert await charity.search(data.invoice_number("B1")) == []
    for hidden in (
        f"/api/v1/actions/{data.action_b}/invoices",
        f"/api/v1/actions/{data.action_b}",
    ):
        assert (await charity.get(hidden)).status_code in {403, 404}

    # No finance or admin role: a matching invoice number finds nothing.
    acquirer = Session(client, data.tokens["acquirer"])
    assert await acquirer.search(data.invoice_number("A1")) == []
    assert await acquirer.search(tag, limit=20) == []
    assert (
        await acquirer.get(f"/api/v1/actions/{data.action_a}/invoices")
    ).status_code == 403

    outsider = Session(client, data.tokens["outsider"])
    assert await outsider.search(tag, limit=20) == []

    finance = Session(client, data.tokens["finance"])
    finance_results = await finance.search(tag, limit=20)
    assert kinds(finance_results) == {("invoice", str(data.invoice_a))}
    await assert_readable_where_it_points(finance, finance_results)

    await prove_sponsors(admin, charity, acquirer, finance, outsider, data, connection)

    # LIKE wildcards in the query are literal characters.
    wildcard = await admin.search(f"{tag} 100%_")
    assert kinds(wildcard) == {("action", str(data.wildcard_action))}
    assert await admin.search(f"{tag}%Alpha") == []
    assert await admin.search(f"{tag}_") == []

    # Prefix matches rank first; whitespace is collapsed.
    ranked = await admin.search(f"  {data.invoice_number('A1').lower()}  ")
    assert ranked[0]["id"] == str(data.invoice_a)

    # Like the invoice list, search hides invoices once invoicing is off.
    assert kinds(await admin.search(data.invoice_number("B1"))) == {
        ("invoice", str(data.invoice_b))
    }
    await connection.execute(
        "DELETE FROM charity_action_capability "
        "WHERE action_id = $1 AND capability = 'invoicing'",
        data.action_b,
    )
    assert await admin.search(data.invoice_number("B1")) == []


def sponsor_targets(results: list[dict[str, str]]) -> dict[str, str]:
    """Assignment id → the page its hit opens."""

    return {
        item["id"]: urlsplit(item["href"]).path
        for item in results
        if item["type"] == "sponsor"
    }


async def prove_sponsors(
    admin: Session,
    charity: Session,
    acquirer: Session,
    finance: Session,
    outsider: Session,
    data: Fixture,
    connection: asyncpg.Connection[Any],
) -> None:
    tag = data.sponsor_tag
    ids = {name: str(value) for name, value in data.assignments.items()}

    # System admin: every assignment of every action with acquisition, one
    # hit per assignment, all in the web pipeline. Not the erased sponsor and
    # not the action without acquisition.
    everything = await admin.search(tag, limit=20)
    assert {item["type"] for item in everything} == {"sponsor"}
    assert sponsor_targets(everything) == {
        ids[name]: "/admin/acquisition"
        for name in ("a_open", "a_handed_over", "b_charity", "b_second")
    }
    await assert_readable_where_it_points(admin, everything)
    alpha = next(item for item in everything if item["id"] == ids["a_open"])
    assert alpha["title"] == data.sponsor_name("Alpha")
    assert alpha["context"] == f"Aktion {data.tag} Alpha · {data.sponsor_city}"
    person = next(item for item in everything if item["id"] == ids["a_handed_over"])
    assert person["title"] == f"Petra {tag}"
    assert person["context"] == f"Aktion {data.tag} Alpha"
    # The city finds the sponsor too; a name prefix ranks first.
    assert sponsor_targets(await admin.search(data.sponsor_city.lower())) == {
        ids["a_open"]: "/admin/acquisition"
    }
    assert (await admin.search(f"petra {tag}"))[0]["id"] == ids["a_handed_over"]
    # The pipeline of an action opens for a system admin without membership.
    board = await admin.get(
        f"/api/v1/actions/{data.wildcard_action}/acquisition/activity-board",
        scope="action",
    )
    assert board.status_code == 200, board.text
    assert board.json()["workItems"] == []

    # Charity admin of A and acquirer in B: every assignment of A in the web
    # pipeline, in B only the own one, in the acquisition app.
    charity_hits = await charity.search(tag, limit=20)
    assert sponsor_targets(charity_hits) == {
        ids["a_open"]: "/admin/acquisition",
        ids["a_handed_over"]: "/admin/acquisition",
        ids["b_charity"]: "/app/sponsors",
    }
    await assert_readable_where_it_points(charity, charity_hits)
    assert (
        await charity.get(
            f"/api/v1/actions/{data.action_b}/acquisition/assignments/{ids['b_second']}"
        )
    ).status_code in {403, 404}
    assert (
        await charity.get(
            f"/api/v1/actions/{data.wildcard_action}/acquisition/activity-board",
            scope="action",
        )
    ).status_code == 403

    # Acquirer of A: the own assignment that is not handed over.
    acquirer_hits = await acquirer.search(tag, limit=20)
    assert sponsor_targets(acquirer_hits) == {ids["a_open"]: "/app/sponsors"}
    await assert_readable_where_it_points(acquirer, acquirer_hits)
    assert (
        await acquirer.get(
            f"/api/v1/actions/{data.action_a}/acquisition/assignments/"
            f"{ids['a_handed_over']}"
        )
    ).status_code in {403, 404}

    # Finance reader and driver see no sponsor.
    assert await finance.search(tag, limit=20) == []
    assert await outsider.search(tag, limit=20) == []

    await prove_search_index(data, connection)

    # Without the acquisition capability the pipeline is closed; so is search.
    await connection.execute(
        "DELETE FROM charity_action_capability "
        "WHERE action_id = $1 AND capability = 'acquisition'",
        data.action_b,
    )
    assert sponsor_targets(await admin.search(tag, limit=20)).keys() == {
        ids["a_open"],
        ids["a_handed_over"],
    }
    assert sponsor_targets(await charity.search(tag, limit=20)).keys() == {
        ids["a_open"],
        ids["a_handed_over"],
    }


async def prove_search_index(
    data: Fixture, connection: asyncpg.Connection[Any]
) -> None:
    """The index writes of the sync and the erasure, on real PostgreSQL."""

    pool = await create_pool(os.environ["CORE_DATABASE_URL"], maximum_size=3)
    index = AsyncpgSponsorSearchIndex(pool)
    now = datetime.now(timezone.utc)

    async def entry(twenty_id: UUID) -> asyncpg.Record | None:
        return await connection.fetchrow(
            "SELECT * FROM sponsor_search_entry WHERE twenty_id = $1", twenty_id
        )

    try:
        # One worker at a time.
        async with index.exclusive_run() as first:
            assert first is True
            async with index.exclusive_run() as second:
                assert second is False
        async with index.exclusive_run() as again:
            assert again is True

        # The changed pass updates entries that exist and adds none.
        stranger = SponsorParty(
            PartyKey(CrmPartyKind.COMPANY, uuid4()), "Fremde Firma", "Ulm"
        )
        renamed = data.party("beta", data.sponsor_name("Beta neu"), "Ulm")
        assert await index.refresh((stranger, renamed), synced_at=now) == 1
        assert await entry(stranger.key.twenty_id) is None
        beta = await entry(data.companies["beta"])
        assert beta is not None
        assert (beta["display_name"], beta["city"]) == (renamed.display_name, "Ulm")

        # An erased entry stays erased, whatever the sync reads from Twenty.
        back = data.party("erased", data.sponsor_name("Erased"), "Augsburg")
        assert await index.refresh((back,), synced_at=now) == 0
        assert (
            await write_sponsor_search_entries(connection, (back,), synced_at=now) == 0
        )
        erased = await entry(data.companies["erased"])
        assert erased is not None and erased["display_name"] is None
        assert erased["erased_at"] is not None

        # The full pass walks every referenced party once, in a stable order.
        ours = {*data.companies.values(), data.person}
        seen: list[PartyKey] = []
        after: PartyKey | None = None
        while True:
            page = await index.referenced_parties(after, 2)
            if not page:
                break
            assert len(page) <= 2
            seen.extend(page)
            after = page[-1]
        assert len(seen) == len(set(seen))
        assert [key.kind for key in seen] == sorted(key.kind for key in seen)
        assert ours <= {key.twenty_id for key in seen}
        assert PartyKey(CrmPartyKind.PERSON, data.person) in seen

        # A batch writes what Twenty has, deletes what it no longer has
        # (the erased marker too) and moves the cursor in one transaction.
        read = (
            PartyKey(CrmPartyKind.COMPANY, data.companies["beta"]),
            PartyKey(CrmPartyKind.COMPANY, data.companies["erased"]),
        )
        state_before = await index.sync_state()
        written, deleted = await index.store_full_batch(
            read,
            (data.party("beta", data.sponsor_name("Beta"), "Augsburg"),),
            synced_at=now,
        )
        assert (written, deleted) == (1, 1)
        assert await entry(data.companies["erased"]) is None
        assert (await index.sync_state()).full_pass_after == read[-1]
        await index.finish_full_pass(now)
        finished = await index.sync_state()
        assert finished.full_pass_after is None
        assert finished.full_pass_completed_at == now
        await connection.execute(
            "UPDATE sponsor_search_sync SET full_pass_completed_at = $1",
            state_before.full_pass_completed_at,
        )

        # An entry whose party has no assignment any more is deleted.
        orphan = SponsorParty(
            PartyKey(CrmPartyKind.PERSON, uuid4()), "Ohne Zuordnung", None
        )
        assert (
            await write_sponsor_search_entries(connection, (orphan,), synced_at=now)
            == 1
        )
        assert await index.delete_unreferenced() >= 1
        assert await entry(orphan.key.twenty_id) is None
        assert await entry(data.companies["alpha"]) is not None

        # The privacy erasure finds the party by the buyer's e-mail address
        # in an order and removes name and city; a foreign party stays.
        email = f"buyer.{data.sponsor_tag}@leonaid.invalid"
        await connection.execute(
            "UPDATE commitment "
            "SET twenty_company_id = $2, "
            "customer_snapshot = customer_snapshot || $3::jsonb "
            "WHERE id = $1",
            data.order_a,
            data.companies["alpha"],
            json.dumps({"email": email.upper()}),
        )
        contributor = SponsorSearchPrivacyContributor()
        assert await contributor.references(connection, email) == ()
        assert (
            await contributor.anonymize(connection, "other@leonaid.invalid", now) == 0
        )
        assert await contributor.anonymize(connection, email, now) == 1
        assert await contributor.anonymize(connection, email, now) == 0
        alpha = await entry(data.companies["alpha"])
        assert alpha is not None
        assert (alpha["display_name"], alpha["city"]) == (None, None)
        assert alpha["erased_at"] == now
        beta = await entry(data.companies["beta"])
        assert beta is not None and beta["display_name"] is not None

        # A party without an entry gets the marker too (the first full pass
        # has not run, the worker has no CRM key, Twenty was down): a company
        # and a person of the subject's orders.
        await connection.execute(
            "DELETE FROM sponsor_search_entry WHERE twenty_id = ANY($1::uuid[])",
            [data.companies["alpha"], data.person],
        )
        await connection.execute(
            "UPDATE commitment SET twenty_person_id = $2, twenty_company_id = NULL "
            "WHERE id = $1",
            data.order_b,
            data.person,
        )
        await connection.execute(
            "UPDATE commitment "
            "SET invoice_recipient_snapshot = invoice_recipient_snapshot || $2::jsonb "
            "WHERE id = $1",
            data.order_b,
            json.dumps({"email": email}),
        )
        later = datetime.now(timezone.utc)
        assert await contributor.anonymize(connection, email, later) == 2
        for twenty_id, kind in (
            (data.companies["alpha"], "company"),
            (data.person, "person"),
        ):
            marker = await entry(twenty_id)
            assert marker is not None, kind
            assert marker["party_kind"] == kind
            assert (marker["display_name"], marker["city"]) == (None, None)
            assert marker["erased_at"] == later
        # The full pass reads both from Twenty; neither name comes back.
        alpha_party = data.party("alpha", data.sponsor_name("Alpha"), data.sponsor_city)
        person_party = SponsorParty(
            PartyKey(CrmPartyKind.PERSON, data.person),
            f"Petra {data.sponsor_tag}",
            None,
        )
        for party in (alpha_party, person_party):
            written, deleted = await index.store_full_batch(
                (party.key,), (party,), synced_at=later
            )
            assert (written, deleted) == (0, 0)
            assert await index.refresh((party,), synced_at=later) == 0
            marker = await entry(party.key.twenty_id)
            assert marker is not None and marker["display_name"] is None
        await index.finish_full_pass(later)
        await connection.execute(
            "UPDATE sponsor_search_sync SET full_pass_completed_at = $1",
            state_before.full_pass_completed_at,
        )
        # A new assignment for the party ends the marker: the entry is back
        # with what the CRM holds then.
        assert (
            await write_sponsor_search_entries(
                connection, (alpha_party,), synced_at=later, new_assignment=True
            )
            == 1
        )
        alpha = await entry(data.companies["alpha"])
        assert alpha is not None
        assert alpha["display_name"] == alpha_party.display_name
        assert alpha["erased_at"] is None
        # A marker whose party lost its last assignment goes with the pass.
        stray = uuid4()
        await connection.execute(
            "UPDATE commitment SET twenty_person_id = $2 WHERE id = $1",
            data.order_b,
            stray,
        )
        # (The company's marker is back as well: it was just lifted.)
        assert await contributor.anonymize(connection, email, later) == 2
        assert await entry(stray) is not None
        assert await index.delete_unreferenced() >= 1
        assert await entry(stray) is None

        # The changed pass records up to when it has read Twenty's changes.
        read_before = (await index.sync_state()).changed_read_until
        await index.finish_changed_pass(later)
        state = await index.sync_state()
        assert state.changed_read_until == later
        assert state.last_success is not None and state.last_success >= later
        await connection.execute(
            "UPDATE sponsor_search_sync SET changed_pass_read_until = $1", read_before
        )
        # Restore the entries for the proofs that follow.
        await write_sponsor_search_entries(
            connection,
            (alpha_party, person_party),
            synced_at=now,
            new_assignment=True,
        )
    finally:
        await pool.close()


async def main() -> None:
    # The schema gate runs without the recovery volume; the survey erasure
    # archive is not part of this proof, so the app must not publish to it.
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
                await prove(client, data, connection)
    finally:
        await data.remove(connection)
        await connection.close()
    print("search-api: OK: role-filtered core search proven against PostgreSQL")


def test_search_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
