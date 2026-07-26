#!/usr/bin/env python3
"""Cross-check the POC-081 browser proof against the real API and PostgreSQL."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx

from leonaid.domain.sessions import SESSION_COOKIE_NAME

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
EXPECTED = {
    "itemCount": 10,
    "totalBoxes": 31,
    "totalMinor": 111_600,
    "totalPieces": 744,
}


class VerificationFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise VerificationFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def klara_token() -> str:
    return f"poc080-{KLARA_ID}-server-session-token-value"


async def verify() -> None:
    proof_path = Path(require_env("UI_PROOF_PATH"))
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    commitment_id = UUID(str(proof["browserCapture"]["commitmentId"]))
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        database = await connection.fetchrow(
            """
            SELECT
                count(DISTINCT commitment.id)::integer AS item_count,
                coalesce(sum(
                    CASE WHEN commitment_line.unit_snapshot = 'box'
                        THEN commitment_line.quantity ELSE 0 END
                ), 0)::integer AS total_boxes,
                coalesce(sum(
                    commitment_line.quantity
                    * coalesce(commitment_line.pieces_per_unit_snapshot, 0)
                ), 0)::integer AS total_pieces,
                coalesce(sum(commitment_line.line_total_minor), 0)::integer
                    AS total_minor
            FROM commitment
            JOIN commitment_line
              ON commitment_line.commitment_id = commitment.id
            WHERE commitment.action_id = $1
            """,
            ACTION_ID,
        )
        created = await connection.fetchrow(
            """
            SELECT
                count(*) OVER ()::integer AS duplicate_count,
                commitment.status,
                commitment.total_minor,
                commitment_line.quantity,
                (
                    commitment_line.quantity
                    * coalesce(commitment_line.pieces_per_unit_snapshot, 0)
                )::integer AS piece_count
            FROM commitment
            JOIN commitment_line
              ON commitment_line.commitment_id = commitment.id
            WHERE commitment.id = $1
            """,
            commitment_id,
        )
    finally:
        await connection.close()

    if database is None or created is None:
        raise VerificationFailure(
            "Der im Browser erzeugte Datensatz fehlt in PostgreSQL"
        )
    database_totals = {
        "itemCount": int(database["item_count"]),
        "totalBoxes": int(database["total_boxes"]),
        "totalMinor": int(database["total_minor"]),
        "totalPieces": int(database["total_pieces"]),
    }
    if database_totals != EXPECTED:
        raise VerificationFailure(
            f"PostgreSQL-Gesamtsummen weichen vom Golden-Ergebnis ab: {database_totals}"
        )
    if (
        int(created["duplicate_count"]) != 1
        or str(created["status"]) != "review_ready"
        or int(created["total_minor"]) != 7_200
        or int(created["quantity"]) != 2
        or int(created["piece_count"]) != 48
    ):
        raise VerificationFailure(
            "Der Browser-Datensatz ist nicht genau einmal oder fachlich falsch gespeichert"
        )

    api_url = require_env("API_BASE_URL").rstrip("/")
    async with httpx.AsyncClient(base_url=api_url, timeout=60) as client:
        response = await client.get(
            f"/api/v1/actions/{ACTION_ID}/commitments",
            headers={"Cookie": f"{SESSION_COOKIE_NAME}={klara_token()}"},
        )
        response.raise_for_status()
        value = response.json()
    api_totals = {
        "itemCount": len(value["items"]),
        "totalBoxes": value["totalBoxes"],
        "totalMinor": value["currencyTotals"][0]["totalMinor"],
        "totalPieces": value["totalPieces"],
    }
    if not any(
        item["commitment"]["id"] == str(commitment_id)
        and item["commitment"]["status"] == "review_ready"
        for item in value["items"]
    ):
        raise VerificationFailure("Die Admin-API liefert den Browser-Datensatz nicht")
    if (
        api_totals != EXPECTED
        or proof["adminApi"] != EXPECTED
        or proof["adminBrowser"] != EXPECTED
        or database_totals != api_totals
    ):
        raise VerificationFailure(
            "Golden-Summen stimmen zwischen Browser, API und PostgreSQL nicht überein"
        )

    print(
        "commitment-ui-verification: Browser, Admin-API und PostgreSQL "
        "melden 10 Bestellungen, 31 Boxen/744 Stück und 1.116,00 EUR"
    )


if __name__ == "__main__":
    asyncio.run(verify())
