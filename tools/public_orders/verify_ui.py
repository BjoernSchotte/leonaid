#!/usr/bin/env python3
"""Verify the visible POC-072 browser journeys against real persisted state."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import httpx

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
MUSTERWERK_ID = UUID("40000000-0000-4000-8000-000000000001")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")


class VerificationFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise VerificationFailure(f"Umgebungsvariable fehlt: {name}")
    return value


async def twenty_record(
    client: httpx.AsyncClient,
    collection: str,
    record_id: UUID,
) -> dict[str, Any]:
    response = await client.get(f"/rest/{collection}/{record_id}")
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    record: object = None
    if isinstance(data, dict):
        if len(data) == 1:
            nested = next(iter(data.values()))
            record = nested if isinstance(nested, dict) else data
        else:
            record = data
    if not isinstance(record, dict):
        raise VerificationFailure(f"Twenty-{collection}-Datensatz fehlt")
    return record


async def exercise(connection: asyncpg.Connection[Any]) -> None:
    proof_path = Path(require_env("UI_PROOF_PATH"))
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    validation = proof.get("validation")
    orders = proof.get("orders")
    if validation != {
        "firstFocusedField": "givenName",
        "retainedCompanyName": "POC072 Browseratelier GmbH",
    }:
        raise VerificationFailure("Browser bewies Eingabe-Erhalt und Fokus nicht")
    if not isinstance(orders, list) or {
        item.get("scenario") for item in orders if isinstance(item, dict)
    } != {"new-company", "existing-company", "person-without-company"}:
        raise VerificationFailure("Die drei öffentlichen E2E-Personas fehlen")

    expected: dict[str, dict[str, str | int | UUID]] = {
        "new-company": {
            "name": "POC072 Browseratelier GmbH",
            "quantity": 2,
            "recipient": KLARA_ID,
        },
        "existing-company": {
            "name": "Musterwerk GmbH",
            "quantity": 1,
            "recipient": ANNA_ID,
        },
        "person-without-company": {
            "name": "Paula Privat",
            "quantity": 3,
            "recipient": KLARA_ID,
        },
    }
    async with httpx.AsyncClient(
        base_url=require_env("TWENTY_BASE_URL").rstrip("/"),
        headers={
            "Authorization": f"Bearer {require_env('TWENTY_INTEGRATION_API_KEY')}"
        },
        timeout=60,
    ) as twenty:
        for item in orders:
            if not isinstance(item, dict):
                raise VerificationFailure("UI-Nachweis enthält keinen Bestellfall")
            scenario = str(item["scenario"])
            reference = str(item["publicReference"])
            configured = expected[scenario]
            row = await connection.fetchrow(
                """
                SELECT
                    id, twenty_company_id, twenty_person_id,
                    customer_snapshot, source, status, total_minor
                FROM commitment
                WHERE action_id = $1
                  AND public_reference = $2
                """,
                ACTION_ID,
                reference,
            )
            if row is None:
                raise VerificationFailure(f"UI-Bestellung fehlt: {scenario}")
            line = await connection.fetchrow(
                """
                SELECT quantity, pieces_per_unit_snapshot, unit_price_minor
                FROM commitment_line
                WHERE commitment_id = $1
                """,
                row["id"],
            )
            snapshot = row["customer_snapshot"]
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)
            quantity_value = configured["quantity"]
            if not isinstance(quantity_value, int):
                raise VerificationFailure("Testmenge ist ungültig")
            quantity = quantity_value
            if (
                not isinstance(snapshot, dict)
                or snapshot.get("displayName") != configured["name"]
                or str(row["source"]) != "public_form"
                or str(row["status"]) != "review_ready"
                or int(row["total_minor"]) != quantity * 3_600
                or line is None
                or int(line["quantity"]) != quantity
                or int(line["pieces_per_unit_snapshot"]) != 24
                or int(line["unit_price_minor"]) != 3_600
            ):
                raise VerificationFailure(
                    f"UI-Bestellung ist fachlich unvollständig: {scenario}"
                )
            recipients = await connection.fetch(
                """
                SELECT recipient.user_id
                FROM activity_event AS event
                JOIN activity_event_recipient AS recipient
                  ON recipient.activity_event_id = event.id
                WHERE event.payload ->> 'commitmentId' = $1
                """,
                str(row["id"]),
            )
            if {entry["user_id"] for entry in recipients} != {configured["recipient"]}:
                raise VerificationFailure(
                    f"UI-Bestellung adressiert falsche Aktivität: {scenario}"
                )
            if scenario == "existing-company":
                if row["twenty_company_id"] != MUSTERWERK_ID:
                    raise VerificationFailure("UI hat bestehende Firma nicht verwendet")
            elif scenario == "new-company":
                record = await twenty_record(
                    twenty,
                    "companies",
                    row["twenty_company_id"],
                )
                if record.get("name") != configured["name"]:
                    raise VerificationFailure("UI-Firma fehlt direkt in Twenty")
            else:
                if row["twenty_company_id"] is not None:
                    raise VerificationFailure(
                        "Privatperson wurde als Firma gespeichert"
                    )
                record = await twenty_record(
                    twenty,
                    "people",
                    row["twenty_person_id"],
                )
                if (
                    record.get("name", {}).get("firstName") != "Paula"
                    or record.get("name", {}).get("lastName") != "Privat"
                    or record.get("companyId") not in {None, ""}
                ):
                    raise VerificationFailure("UI-Privatperson fehlt direkt in Twenty")
    print(
        "public-orders-ui: OK:",
        "drei sichtbare Bestellwege, Fokus/Eingabe-Erhalt und reale Persistenz bewiesen",
    )


async def main() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        await exercise(connection)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
