#!/usr/bin/env python3
"""Real FastAPI/PostgreSQL contract for versioned action templates."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4, uuid5

import asyncpg
import httpx

from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
SESSION_NAMESPACE = UUID("d69948ee-bb22-4eed-ac01-f0d24c067151")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(user_id: UUID) -> str:
    return f"poc051-{user_id}-real-server-session-token"


async def seed_sessions(connection: asyncpg.Connection[Any]) -> dict[UUID, str]:
    now = datetime.now(timezone.utc)
    users = (KLARA_ID, ANNA_ID)
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        list(users),
    )
    result: dict[UUID, str] = {}
    for user_id in users:
        token = token_for(user_id)
        result[user_id] = token
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at, last_seen_at,
                fresh_login_at, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $5, $5, $5)
            """,
            uuid5(SESSION_NAMESPACE, str(user_id)),
            user_id,
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )
    return result


def cookies(token: str) -> dict[str, str]:
    return {SESSION_COOKIE_NAME: token}


def request_headers(label: str) -> dict[str, str]:
    digest = hashlib.sha256(label.encode()).hexdigest()[:24]
    return {"X-Request-ID": f"poc051:{digest}", "Accept": "application/json"}


def template_payload(
    *,
    key: str,
    slug: str,
    name: str,
    version: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "templateKey": key,
        "carrierName": "Lions Hilfswerk Beispielstadt",
        "name": name,
        "purpose": "Förderung lokaler Kinder- und Jugendprojekte.",
        "startsOn": "2027-09-01",
        "endsOn": "2027-11-15",
        "archiveSlug": slug,
        "beneficiaries": [
            {
                "organizationName": "Kinderhafen Beispielstadt",
                "publicDescription": "Ermöglicht kostenfreie Bildungsangebote.",
            }
        ],
        "goal": {
            "goalValue": "10000",
            "actualValue": "500",
            "unit": "EUR",
            "currency": "EUR",
        },
    }
    if version is not None:
        payload["templateVersion"] = version
    return payload


def require_template_response(
    body: dict[str, Any],
    *,
    version: int,
    price: int,
    title: str,
) -> UUID:
    action = body.get("action")
    template = body.get("template")
    offerings = body.get("offerings")
    order_form = body.get("orderForm")
    if (
        not isinstance(action, dict)
        or not isinstance(template, dict)
        or not isinstance(offerings, list)
        or len(offerings) != 1
        or not isinstance(order_form, dict)
        or template.get("key") != "krapfentaxi"
        or template.get("version") != version
        or offerings[0].get("code") != "krapfenbox-24"
        or offerings[0].get("piecesPerUnit") != 24
        or offerings[0].get("unitPriceMinor") != price
        or order_form.get("title") != title
        or action.get("capabilities")
        != ["acquisition", "invoicing", "offerings", "ordering"]
    ):
        raise ContractFailure("Krapfentaxi-Konfiguration ist unvollständig")
    return UUID(str(action["id"]))


async def publish_version_two(connection: asyncpg.Connection[Any]) -> None:
    await connection.execute(
        """
        INSERT INTO action_template_version (
            template_key, version, display_name, description
        )
        VALUES (
            'krapfentaxi', 2, 'Krapfentaxi',
            'Zweite reale Testversion mit angepasstem Preis.'
        )
        """
    )
    await connection.executemany(
        """
        INSERT INTO action_template_capability (
            template_key, template_version, capability
        )
        VALUES ('krapfentaxi', 2, $1)
        """,
        [
            (capability,)
            for capability in ("acquisition", "offerings", "ordering", "invoicing")
        ],
    )
    await connection.execute(
        """
        INSERT INTO action_template_offering (
            template_key, template_version, code, name, status, unit,
            pieces_per_unit, unit_price_minor, currency, sort_order
        )
        VALUES (
            'krapfentaxi', 2, 'krapfenbox-24', 'Krapfenbox',
            'draft', 'box', 24, 4200, 'EUR', 0
        )
        """
    )
    await connection.execute(
        """
        INSERT INTO action_template_order_form (
            template_key, template_version, form_key, title, introduction,
            submit_label, require_company_name, require_contact_name,
            require_email, require_phone, require_delivery_address,
            require_billing_address, allow_message
        )
        VALUES (
            'krapfentaxi', 2, 'sponsor-bestellung',
            'Krapfenboxen 2028 bestellen',
            'Unterstützen Sie die nächste Krapfentaxi-Aktion.',
            'Bestellung absenden',
            true, true, true, false, true, true, true
        )
        """
    )


async def insert_operational_source_data(
    connection: asyncpg.Connection[Any],
    action_id: UUID,
    offering_id: UUID,
) -> tuple[UUID, UUID]:
    commitment_id = uuid4()
    invoice_id = uuid4()
    await connection.execute(
        """
        INSERT INTO commitment (
            id, action_id, twenty_company_id, source, status,
            customer_snapshot, currency, total_minor
        )
        VALUES (
            $1, $2, $3, 'admin', 'invoiced',
            '{"name":"Operative Quelle GmbH"}'::jsonb, 'EUR', 3600
        )
        """,
        commitment_id,
        action_id,
        uuid4(),
    )
    await connection.execute(
        """
        INSERT INTO commitment_line (
            id, commitment_id, offering_id, description_snapshot,
            quantity, unit_snapshot, pieces_per_unit_snapshot,
            unit_price_minor, line_total_minor
        )
        VALUES ($1, $2, $3, 'Krapfenbox', 1, 'box', 24, 3600, 3600)
        """,
        uuid4(),
        commitment_id,
        offering_id,
    )
    await connection.execute(
        """
        INSERT INTO invoice (
            id, commitment_id, number, status, currency,
            net_minor, tax_minor, gross_minor,
            recipient_snapshot, line_snapshot, tax_note
        )
        VALUES (
            $1, $2, 'TPL51-0001', 'draft', 'EUR',
            3600, 0, 3600,
            '{"name":"Operative Quelle GmbH"}'::jsonb,
            '[{"description":"Krapfenbox","amountMinor":3600}]'::jsonb,
            'Kein Ausweis von Umsatzsteuer.'
        )
        """,
        invoice_id,
        commitment_id,
    )
    return commitment_id, invoice_id


async def exercise(
    connection: asyncpg.Connection[Any],
    tokens: dict[UUID, str],
) -> None:
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=30,
    ) as client:
        anna_list = await client.get(
            "/api/v1/action-templates",
            cookies=cookies(tokens[ANNA_ID]),
            headers=request_headers("anna-list"),
        )
        if anna_list.status_code != 403:
            raise ContractFailure("Akquisiteur konnte Aktionstemplates verwenden")

        initial_list = await client.get(
            "/api/v1/action-templates",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("template-list-v1"),
        )
        initial_list.raise_for_status()
        items = initial_list.json()["items"]
        if [(item["key"], item["version"]) for item in items] != [
            ("blank", 1),
            ("krapfentaxi", 1),
        ]:
            raise ContractFailure(
                "PoC-Liste enthält nicht exakt leere Aktion und Krapfentaxi"
            )
        serialized = json.dumps(items).casefold()
        if "lions open" in serialized or "weihnachtsmarkt" in serialized:
            raise ContractFailure("Nachgelagerte Templates wurden vorweggenommen")

        v1_response = await client.post(
            "/api/v1/actions/from-template",
            json=template_payload(
                key="krapfentaxi",
                slug="krapfentaxi-template-2027",
                name="Krapfentaxi Template 2027",
            ),
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("create-v1"),
        )
        v1_response.raise_for_status()
        v1_body = v1_response.json()
        v1_action_id = require_template_response(
            v1_body,
            version=1,
            price=3600,
            title="Krapfenboxen bestellen",
        )
        v1_offering_id = UUID(str(v1_body["offerings"][0]["id"]))

        blank_response = await client.post(
            "/api/v1/actions/from-template",
            json=template_payload(
                key="blank",
                slug="neutrale-template-aktion-2027",
                name="Neutrale Template-Aktion 2027",
            ),
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("create-blank"),
        )
        blank_response.raise_for_status()
        blank = blank_response.json()
        if (
            blank["template"]["key"] != "blank"
            or blank["action"]["capabilities"] != []
            or blank["offerings"] != []
            or blank["orderForm"] is not None
        ):
            raise ContractFailure("Leere Aktion ist nicht technisch neutral")

        try:
            await connection.execute(
                """
                UPDATE action_template_version
                SET display_name = 'Manipuliert'
                WHERE template_key = 'krapfentaxi' AND version = 1
                """
            )
        except asyncpg.PostgresError:
            pass
        else:
            raise ContractFailure("Veröffentlichte Template-Version war veränderbar")

        await publish_version_two(connection)
        current_list = await client.get(
            "/api/v1/action-templates",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("template-list-v2"),
        )
        current_list.raise_for_status()
        current_items = current_list.json()["items"]
        if [(item["key"], item["version"]) for item in current_items] != [
            ("blank", 1),
            ("krapfentaxi", 2),
        ]:
            raise ContractFailure("Neueste veröffentlichte Template-Version fehlt")

        historical = await client.get(
            f"/api/v1/actions/{v1_action_id}/configuration",
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("historical-v1"),
        )
        historical.raise_for_status()
        require_template_response(
            historical.json(),
            version=1,
            price=3600,
            title="Krapfenboxen bestellen",
        )

        v2_response = await client.post(
            "/api/v1/actions/from-template",
            json=template_payload(
                key="krapfentaxi",
                slug="krapfentaxi-template-2028",
                name="Krapfentaxi Template 2028",
            ),
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("create-v2"),
        )
        v2_response.raise_for_status()
        require_template_response(
            v2_response.json(),
            version=2,
            price=4200,
            title="Krapfenboxen 2028 bestellen",
        )

        await insert_operational_source_data(
            connection,
            v1_action_id,
            v1_offering_id,
        )
        copy_response = await client.post(
            f"/api/v1/actions/{v1_action_id}/copies",
            json={
                "name": "Krapfentaxi Kopie 2029",
                "startsOn": "2029-09-01",
                "endsOn": "2029-11-15",
                "archiveSlug": "krapfentaxi-kopie-2029",
            },
            cookies=cookies(tokens[KLARA_ID]),
            headers=request_headers("copy-v1"),
        )
        copy_response.raise_for_status()
        copied = copy_response.json()
        copy_action_id = require_template_response(
            copied,
            version=1,
            price=3600,
            title="Krapfenboxen bestellen",
        )
        if (
            copied["template"]["copiedFromActionId"] != str(v1_action_id)
            or copied["action"]["status"] != "draft"
            or copied["action"]["goal"]["actualValue"] != "0"
            or copied["offerings"][0]["id"] == str(v1_offering_id)
        ):
            raise ContractFailure("Vorjahreskopie ist fachlich nicht sauber getrennt")

        snapshot = await connection.fetchrow(
            """
            SELECT
                (SELECT count(*) FROM commitment WHERE action_id = $1)
                    AS commitments,
                (
                    SELECT count(*)
                    FROM invoice
                    JOIN commitment ON commitment.id = invoice.commitment_id
                    WHERE commitment.action_id = $1
                ) AS invoices,
                (
                    SELECT count(*)
                    FROM generated_document
                    WHERE action_id = $1
                ) AS documents,
                (
                    SELECT count(*)
                    FROM action_membership
                    WHERE action_id = $1
                ) AS memberships,
                (SELECT count(*) FROM offering WHERE action_id = $1)
                    AS offerings,
                (
                    SELECT count(*)
                    FROM action_template_snapshot
                    WHERE action_id = $1
                      AND copied_from_action_id = $2
                      AND template_version = 1
                ) AS snapshots
            """,
            copy_action_id,
            v1_action_id,
        )
        if snapshot is None or dict(snapshot) != {
            "commitments": 0,
            "invoices": 0,
            "documents": 0,
            "memberships": 1,
            "offerings": 1,
            "snapshots": 1,
        }:
            raise ContractFailure(
                "Vorjahreskopie übernahm operative Daten oder verlor Konfiguration"
            )

        try:
            await connection.execute(
                """
                UPDATE action_template_snapshot
                SET configuration = '{}'::jsonb
                WHERE action_id = $1
                """,
                v1_action_id,
            )
        except asyncpg.PostgresError:
            pass
        else:
            raise ContractFailure("Aktions-Snapshot war nachträglich veränderbar")


async def run() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        tokens = await seed_sessions(connection)
        await exercise(connection, tokens)
    finally:
        await connection.close()
    print(
        "template-contract: Versionen, Snapshot-Isolation und saubere "
        "Vorjahreskopie real bewiesen"
    )


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except (ContractFailure, asyncpg.PostgresError, httpx.HTTPError) as error:
        print(f"template-contract: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
