#!/usr/bin/env python3
"""Core search over HTTP: full FastAPI app, middleware and real PostgreSQL.

Runs as a contract script in the schema gate (``tools/schema/test.sh``) and,
with ``CORE_DATABASE_URL`` set, under pytest. Every result is opened through
the endpoint behind its admin route to prove the search shows nothing the
account could not read there.
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
                approved_by_user_id, document_version, idempotency_key
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
                $4, $6, 1, $7
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
        users = list(self.users.values())
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
