#!/usr/bin/env python3
"""Verify browser read-state effects in the real PostgreSQL projection."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
BERND_ID = UUID("10000000-0000-4000-8000-000000000005")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
MUSTERWERK_ID = UUID("40000000-0000-4000-8000-000000000001")
DOPPELKONTAKT_ID = UUID("40000000-0000-4000-8000-000000000003")
FREIE_FIRMA_ID = UUID("40000000-0000-4000-8000-000000000004")


class VerificationFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise VerificationFailure(f"Umgebungsvariable fehlt: {name}")
    return value


async def verify(connection: asyncpg.Connection[Any]) -> dict[str, object]:
    rows = await connection.fetch(
        """
        SELECT
            event.twenty_company_id,
            recipient.user_id,
            recipient.read_at
        FROM activity_event AS event
        JOIN activity_event_recipient AS recipient
          ON recipient.activity_event_id = event.id
        WHERE event.event_type = 'public_order_received'
          AND event.twenty_company_id = ANY($1::uuid[])
        ORDER BY event.twenty_company_id, recipient.user_id
        """,
        [MUSTERWERK_ID, DOPPELKONTAKT_ID, FREIE_FIRMA_ID],
    )
    state = {(row["twenty_company_id"], row["user_id"]): row["read_at"] for row in rows}
    expected = {
        (MUSTERWERK_ID, ANNA_ID),
        (DOPPELKONTAKT_ID, ANNA_ID),
        (DOPPELKONTAKT_ID, BERND_ID),
        (FREIE_FIRMA_ID, KLARA_ID),
    }
    if set(state) != expected:
        raise VerificationFailure("Browsernachweis veränderte die Empfängermenge")
    if state[(MUSTERWERK_ID, ANNA_ID)] is None:
        raise VerificationFailure("Annas Browseraktion speicherte kein read_at")
    if any(
        state[key] is not None for key in expected if key != (MUSTERWERK_ID, ANNA_ID)
    ):
        raise VerificationFailure("Lesestatus eines anderen Empfängers wurde verändert")
    event_count = await connection.fetchval(
        """
        SELECT count(*)
        FROM activity_event
        WHERE event_type = 'public_order_received'
          AND twenty_company_id = ANY($1::uuid[])
        """,
        [MUSTERWERK_ID, DOPPELKONTAKT_ID, FREIE_FIRMA_ID],
    )
    if int(event_count) != 3:
        raise VerificationFailure("Browseraktion löschte oder duplizierte Ereignisse")
    return {
        "eventCount": int(event_count),
        "recipientCount": len(state),
        "readRecipient": str(ANNA_ID),
        "readParty": str(MUSTERWERK_ID),
    }


async def main() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        proof = await verify(connection)
    finally:
        await connection.close()
    proof_path = Path(require_env("UI_PROOF_PATH"))
    proof_path.write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "activity-feed-ui: OK:",
        "Browser-Lesestatus isoliert persistiert, Ereignisse unverändert",
    )


if __name__ == "__main__":
    asyncio.run(main())
