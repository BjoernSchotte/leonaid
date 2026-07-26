#!/usr/bin/env python3
"""Real FastAPI/PostgreSQL commitment contract for POC-080."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import httpx

from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
ACTIVE_OFFERING_ID = UUID("70000000-0000-4000-8000-000000000001")
INACTIVE_OFFERING_ID = UUID("70000000-0000-4000-8000-000000000002")
MUSTERWERK_ID = UUID("40000000-0000-4000-8000-000000000001")
FREE_COMPANY_ID = UUID("40000000-0000-4000-8000-000000000004")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
SESSION_NAMESPACE = UUID("cd56365a-c7a0-4e32-80b7-9453310487ac")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(user_id: UUID) -> str:
    return f"poc080-{user_id}-server-session-token-value"


def session_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


async def seed_sessions(connection: asyncpg.Connection[Any]) -> dict[UUID, str]:
    now = datetime.now(timezone.utc)
    users = (KLARA_ID, ANNA_ID)
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        list(users),
    )
    tokens: dict[UUID, str] = {}
    for user_id in users:
        token = token_for(user_id)
        tokens[user_id] = token
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at,
                last_seen_at, fresh_login_at, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $5, $5, $5)
            """,
            uuid5(SESSION_NAMESPACE, str(user_id)),
            user_id,
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )
    return tokens


def error_code(response: httpx.Response) -> str:
    payload = response.json()
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Vertrag")
    return str(error.get("code"))


async def post_commitment(
    client: httpx.AsyncClient,
    *,
    token: str,
    idempotency_key: str,
    request_id: str,
    body: Mapping[str, object],
) -> httpx.Response:
    return await client.post(
        f"/api/v1/actions/{ACTION_ID}/commitments",
        headers={
            **session_headers(token),
            "Idempotency-Key": idempotency_key,
            "X-Request-ID": request_id,
        },
        json=body,
    )


def buyer(company_id: UUID, display_name: str) -> dict[str, object]:
    return {
        "partyKind": "company",
        "twentyId": str(company_id),
        "displayName": display_name,
        "email": "einkauf@synthetic.leonaid.invalid",
    }


def recipient(name: str) -> dict[str, object]:
    return {
        "recipientName": name,
        "streetLine1": "Rechnungsweg 9",
        "postalCode": "86150",
        "city": "Augsburg",
        "countryCode": "DE",
        "email": "rechnung@synthetic.leonaid.invalid",
    }


def body_for(
    *,
    source: str,
    company_id: UUID,
    company_name: str,
    offering_id: UUID = ACTIVE_OFFERING_ID,
    quantity: int = 2,
    quoted_price: int = 1,
    ready: bool = False,
) -> dict[str, object]:
    return {
        "source": source,
        "readyForReview": ready,
        "buyer": buyer(company_id, company_name),
        "invoiceRecipient": recipient(f"{company_name} Rechnungseingang"),
        "lines": [
            {
                "offeringId": str(offering_id),
                "quantity": quantity,
                "unit": "box",
                "quotedUnitPriceMinor": quoted_price,
            }
        ],
    }


async def assert_seeded_sources(connection: asyncpg.Connection[Any]) -> None:
    rows = await connection.fetch(
        """
        SELECT source, count(*) AS count
        FROM commitment
        WHERE id::text LIKE '80000000-0000-4000-8000-%'
        GROUP BY source
        ORDER BY source
        """
    )
    counts = {str(row["source"]): int(row["count"]) for row in rows}
    if counts != {"acquisition": 3, "admin": 1, "public_form": 2}:
        raise ContractFailure(f"Golden-Quellen sind unvollständig: {counts}")
    line_count = await connection.fetchval(
        """
        SELECT count(*)
        FROM commitment_line
        WHERE commitment_id::text LIKE '80000000-0000-4000-8000-%'
        """
    )
    if line_count != 6:
        raise ContractFailure(
            f"Golden-Bestellpositionen wurden nicht vollständig persistiert: {line_count}"
        )
    totals = await connection.fetchrow(
        """
        SELECT
            sum(commitment_line.quantity)::integer AS box_count,
            sum(
                commitment_line.quantity
                * commitment_line.pieces_per_unit_snapshot
            )::integer AS piece_count,
            sum(commitment_line.line_total_minor)::integer AS total_minor
        FROM commitment_line
        WHERE commitment_id::text LIKE '80000000-0000-4000-8000-%'
        """
    )
    if (
        totals is None
        or totals["box_count"] != 25
        or totals["piece_count"] != 600
        or totals["total_minor"] != 90_000
    ):
        raise ContractFailure(
            "Golden-Mengen und -Beträge wurden nicht vollständig persistiert"
        )
    offering = await connection.fetchrow(
        """
        SELECT
            allowed_quantity_units, available_from, available_until,
            pieces_per_unit, unit_price_minor, currency
        FROM offering
        WHERE id = $1
        """,
        ACTIVE_OFFERING_ID,
    )
    if (
        offering is None
        or list(offering["allowed_quantity_units"]) != ["box"]
        or offering["available_from"] is None
        or offering["available_until"] is None
        or offering["pieces_per_unit"] != 24
        or offering["unit_price_minor"] != 3_600
        or offering["currency"] != "EUR"
    ):
        raise ContractFailure("Golden-Angebot besitzt keinen vollständigen Vertrag")


async def exercise(connection: asyncpg.Connection[Any]) -> None:
    await assert_seeded_sources(connection)
    tokens = await seed_sessions(connection)
    api_url = require_env("API_BASE_URL").rstrip("/")
    acquisition_body = body_for(
        source="acquisition",
        company_id=MUSTERWERK_ID,
        company_name="Musterwerk GmbH",
    )

    async with httpx.AsyncClient(base_url=api_url, timeout=60) as api:
        capture_context = await api.get(
            f"/api/v1/actions/{ACTION_ID}/commitment-capture",
            headers=session_headers(tokens[ANNA_ID]),
        )
        capture_context.raise_for_status()
        capture_value = capture_context.json()
        if (
            capture_value["actionName"] != "Krapfentaxi 2026"
            or len(capture_value["offerings"]) != 1
            or capture_value["offerings"][0]["id"] != str(ACTIVE_OFFERING_ID)
            or capture_value["offerings"][0]["unitPriceMinor"] != 3_600
        ):
            raise ContractFailure("Akquisiteur erhält keinen korrekten Bestellkontext")

        forbidden_list = await api.get(
            f"/api/v1/actions/{ACTION_ID}/commitments",
            headers=session_headers(tokens[ANNA_ID]),
        )
        if forbidden_list.status_code != 403:
            raise ContractFailure(
                "Akquisiteur konnte den vollständigen Admin-Arbeitsvorrat lesen"
            )

        seeded_list = await api.get(
            f"/api/v1/actions/{ACTION_ID}/commitments",
            headers=session_headers(tokens[KLARA_ID]),
        )
        seeded_list.raise_for_status()
        seeded_value = seeded_list.json()
        if (
            len(seeded_value["items"]) != 6
            or seeded_value["totalBoxes"] != 25
            or seeded_value["totalPieces"] != 600
            or seeded_value["currencyTotals"]
            != [{"currency": "EUR", "totalMinor": 90_000}]
            or {item["commitment"]["source"] for item in seeded_value["items"]}
            != {"acquisition", "public_form", "admin"}
            or any(
                not item["commitment"]["buyer"]["displayName"]
                for item in seeded_value["items"]
            )
        ):
            raise ContractFailure(
                "Golden-Gesamtsummen oder Bestell-Snapshots fehlen in der Admin-API"
            )

        created = await post_commitment(
            api,
            token=tokens[ANNA_ID],
            idempotency_key="poc080:acquisition:musterwerk",
            request_id="poc080:create-acquisition",
            body=acquisition_body,
        )
        created.raise_for_status()
        value = created.json()
        if (
            value["source"] != "acquisition"
            or value["status"] != "draft"
            or value["totalMinor"] != 7_200
            or value["currency"] != "EUR"
            or value["totalBoxes"] != 2
            or value["totalPieces"] != 48
            or value["lines"][0]["unitPriceMinor"] != 3_600
            or value["lines"][0]["lineTotalMinor"] != 7_200
            or value["replayed"]
        ):
            raise ContractFailure(
                "Serverpreis, Mengen oder Quelle wurden falsch berechnet"
            )
        commitment_id = UUID(str(value["id"]))

        replay = await post_commitment(
            api,
            token=tokens[ANNA_ID],
            idempotency_key="poc080:acquisition:musterwerk",
            request_id="poc080:replay-acquisition",
            body=acquisition_body,
        )
        replay.raise_for_status()
        replay_value = replay.json()
        if (
            UUID(str(replay_value["id"])) != commitment_id
            or not replay_value["replayed"]
        ):
            raise ContractFailure(
                "Idempotente Wiederholung erzeugte ein neues Commitment"
            )

        conflict_body = body_for(
            source="acquisition",
            company_id=MUSTERWERK_ID,
            company_name="Musterwerk GmbH",
            quantity=3,
        )
        conflict = await post_commitment(
            api,
            token=tokens[ANNA_ID],
            idempotency_key="poc080:acquisition:musterwerk",
            request_id="poc080:conflicting-replay",
            body=conflict_body,
        )
        if (
            conflict.status_code != 409
            or error_code(conflict) != "idempotency_conflict"
        ):
            raise ContractFailure(
                "Abweichende idempotente Wiederholung wurde akzeptiert"
            )

        forbidden_admin = await post_commitment(
            api,
            token=tokens[ANNA_ID],
            idempotency_key="poc080:forbidden:admin",
            request_id="poc080:forbidden-admin",
            body=body_for(
                source="admin",
                company_id=MUSTERWERK_ID,
                company_name="Musterwerk GmbH",
            ),
        )
        if (
            forbidden_admin.status_code != 403
            or error_code(forbidden_admin) != "action_management_required"
        ):
            raise ContractFailure("Akquisiteur konnte eine Admin-Bestellung ausgeben")

        unassigned = await post_commitment(
            api,
            token=tokens[ANNA_ID],
            idempotency_key="poc080:unassigned:company",
            request_id="poc080:unassigned-company",
            body=body_for(
                source="acquisition",
                company_id=FREE_COMPANY_ID,
                company_name="Freie Firma e.K.",
            ),
        )
        if (
            unassigned.status_code != 403
            or error_code(unassigned) != "commitment_party_not_assigned"
        ):
            raise ContractFailure("Nicht zugeordnete Firma wurde als Akquise erfasst")

        inactive = await post_commitment(
            api,
            token=tokens[KLARA_ID],
            idempotency_key="poc080:inactive:offering",
            request_id="poc080:inactive-offering",
            body=body_for(
                source="admin",
                company_id=FREE_COMPANY_ID,
                company_name="Freie Firma e.K.",
                offering_id=INACTIVE_OFFERING_ID,
            ),
        )
        if (
            inactive.status_code != 422
            or error_code(inactive) != "offering_not_available"
        ):
            raise ContractFailure("Inaktives Angebot wurde bestellt")

        admin = await post_commitment(
            api,
            token=tokens[KLARA_ID],
            idempotency_key="poc080:admin:free-company",
            request_id="poc080:create-admin",
            body=body_for(
                source="admin",
                company_id=FREE_COMPANY_ID,
                company_name="Freie Firma e.K.",
                quantity=1,
                quoted_price=999_999,
                ready=True,
            ),
        )
        admin.raise_for_status()
        admin_value = admin.json()
        if (
            admin_value["source"] != "admin"
            or admin_value["status"] != "review_ready"
            or admin_value["totalMinor"] != 3_600
            or admin_value["lines"][0]["unitPriceMinor"] != 3_600
        ):
            raise ContractFailure("Admin-Commitment verwendet keinen Serverpreis")

        parallel_body = body_for(
            source="acquisition",
            company_id=MUSTERWERK_ID,
            company_name="Musterwerk GmbH",
            quantity=1,
            ready=True,
        )
        parallel_responses = await asyncio.gather(
            *(
                post_commitment(
                    api,
                    token=tokens[ANNA_ID],
                    idempotency_key="poc081:parallel:musterwerk",
                    request_id=f"poc081:parallel:{index}",
                    body=parallel_body,
                )
                for index in range(12)
            )
        )
        for response in parallel_responses:
            response.raise_for_status()
        parallel_values = [response.json() for response in parallel_responses]
        parallel_ids = {item["id"] for item in parallel_values}
        if (
            len(parallel_ids) != 1
            or sum(not item["replayed"] for item in parallel_values) != 1
            or any(item["totalMinor"] != 3_600 for item in parallel_values)
        ):
            raise ContractFailure(
                "Parallele Submits erzeugten mehr als ein fachliches Commitment"
            )

        final_list = await api.get(
            f"/api/v1/actions/{ACTION_ID}/commitments",
            headers=session_headers(tokens[KLARA_ID]),
        )
        final_list.raise_for_status()
        final_value = final_list.json()
        if (
            len(final_value["items"]) != 9
            or final_value["totalBoxes"] != 29
            or final_value["totalPieces"] != 696
            or final_value["currencyTotals"]
            != [{"currency": "EUR", "totalMinor": 104_400}]
        ):
            raise ContractFailure(
                "API-Summen nach serieller und paralleler Erfassung sind falsch"
            )

    persisted = await connection.fetchrow(
        """
        SELECT
            commitment.source,
            commitment.customer_snapshot,
            commitment.invoice_recipient_snapshot,
            commitment.total_minor,
            commitment_line.quantity,
            commitment_line.unit_price_minor,
            commitment_line.line_total_minor,
            commitment_line.pieces_per_unit_snapshot
        FROM commitment
        JOIN commitment_line
          ON commitment_line.commitment_id = commitment.id
        WHERE commitment.id = $1
        """,
        commitment_id,
    )
    if persisted is None:
        raise ContractFailure("Erzeugtes Commitment fehlt in PostgreSQL")
    buyer_snapshot = persisted["customer_snapshot"]
    recipient_snapshot = persisted["invoice_recipient_snapshot"]
    if isinstance(buyer_snapshot, str):
        buyer_snapshot = json.loads(buyer_snapshot)
    if isinstance(recipient_snapshot, str):
        recipient_snapshot = json.loads(recipient_snapshot)
    if not isinstance(buyer_snapshot, dict) or not isinstance(recipient_snapshot, dict):
        raise ContractFailure("PostgreSQL-Snapshots besitzen kein JSON-Objekt")
    if (
        buyer_snapshot["displayName"] != "Musterwerk GmbH"
        or recipient_snapshot["recipientName"] != "Musterwerk GmbH Rechnungseingang"
        or persisted["total_minor"] != 7_200
        or persisted["quantity"] != 2
        or persisted["unit_price_minor"] != 3_600
        or persisted["line_total_minor"] != 7_200
        or persisted["pieces_per_unit_snapshot"] != 24
    ):
        raise ContractFailure("Persistierte Snapshots oder Serverbeträge sind falsch")
    duplicate_count = await connection.fetchval(
        "SELECT count(*) FROM commitment WHERE idempotency_key = $1",
        "poc080:acquisition:musterwerk",
    )
    audit_count = await connection.fetchval(
        """
        SELECT count(*)
        FROM audit_event
        WHERE event_type = 'commitment_created'
          AND request_id IN ('poc080:create-acquisition', 'poc080:create-admin')
        """
    )
    parallel_count = await connection.fetchval(
        "SELECT count(*) FROM commitment WHERE idempotency_key = $1",
        "poc081:parallel:musterwerk",
    )
    parallel_audit_count = await connection.fetchval(
        """
        SELECT count(*)
        FROM audit_event
        WHERE event_type = 'commitment_created'
          AND entity_id = (
              SELECT id
              FROM commitment
              WHERE idempotency_key = 'poc081:parallel:musterwerk'
          )
        """
    )
    if (
        duplicate_count != 1
        or audit_count != 2
        or parallel_count != 1
        or parallel_audit_count != 1
    ):
        raise ContractFailure(
            "Idempotenz oder transaktionaler Commitment-Audit ist unvollständig"
        )

    print(
        "commitment-contract: drei Golden-Quellen, Capture-/Admin-API, "
        "Serverpreise, 25 Boxen/600 Stück, getrennte Snapshots und zwölf "
        "parallele Submits als genau ein Commitment real bewiesen"
    )


async def main() -> None:
    connection = await asyncpg.connect(
        require_env("CORE_DATABASE_URL"),
        timeout=10,
    )
    try:
        await exercise(connection)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
