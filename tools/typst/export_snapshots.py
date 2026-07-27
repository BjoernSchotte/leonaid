"""Export immutable invoice document snapshots from the real Core database."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

from leonaid.adapters.postgres.invoices import AsyncpgInvoiceRepository
from leonaid.application.invoice_documents import InvoiceDocumentSnapshot

GOLDEN_ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
GOLDEN_NUMBERS = frozenset({"KT26-0001", "KT26-0002", "KT26-0003"})


class SnapshotExportError(RuntimeError):
    pass


def _fixture_payloads(directory: Path) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for path in sorted(directory.glob("KT26-*.json")):
        value: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not all(
            isinstance(key, str) for key in value
        ):
            raise SnapshotExportError(f"Ungültige Golden-Datei: {path.name}")
        payloads.append(InvoiceDocumentSnapshot.from_payload(value).payload())
    return sorted(payloads, key=lambda item: str(item["number"]))


async def export_snapshots(
    *,
    database_url: str,
    fixture_directory: Path,
    output: Path,
) -> int:
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    try:
        records = await AsyncpgInvoiceRepository(pool).list_for_action(
            action_id=GOLDEN_ACTION_ID
        )
    finally:
        await pool.close()

    actual = sorted(
        [
            InvoiceDocumentSnapshot.from_invoice(record.invoice).payload()
            for record in records
            if record.invoice.number in GOLDEN_NUMBERS
        ],
        key=lambda item: str(item["number"]),
    )
    expected = _fixture_payloads(fixture_directory)
    if actual != expected:
        raise SnapshotExportError(
            "Die real gespeicherten Rechnungssnapshots weichen von den "
            "versionierten Golden-Rechnungen ab."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return len(actual)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture_directory", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    database_url = os.environ.get("CORE_DATABASE_URL")
    if not database_url:
        print("typst-snapshots: ERROR: CORE_DATABASE_URL fehlt", file=sys.stderr)
        return 1
    try:
        count = asyncio.run(
            export_snapshots(
                database_url=database_url,
                fixture_directory=arguments.fixture_directory,
                output=arguments.output,
            )
        )
    except (OSError, ValueError, asyncpg.PostgresError, SnapshotExportError) as error:
        print(f"typst-snapshots: ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "typst-snapshots: OK: "
        f"{count} echte Datenbank-Snapshots entsprechen Golden Data"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
