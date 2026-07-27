"""Exercise deterministic normal and multi-page invoice rendering."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from leonaid.adapters.typst import TypstInvoiceRenderer, TypstRenderError
from leonaid.application.invoice_documents import InvoiceDocumentSnapshot
from leonaid.domain.errors import DomainInvariantError


class RenderContractError(RuntimeError):
    pass


def _load_payload(path: Path) -> dict[str, object]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RenderContractError(f"Ungültiges Snapshot-JSON: {path.name}")
    return value


def _stress_snapshot(base: dict[str, object]) -> InvoiceDocumentSnapshot:
    payload = json.loads(json.dumps(base))
    payload["invoiceId"] = "90000000-0000-4000-8000-000000000091"
    payload["number"] = "KT26-LAYOUT-0001"
    payload["recipient"] = {
        "recipientName": (
            "Arbeitsgemeinschaft für besonders nachhaltige "
            "Unternehmenspartnerschaften Süddeutschland mbH & Co. KG"
        ),
        "streetLine1": (
            "Dr.-Elisabeth-von-der-Wirkungsgemeinschaft-Promenade 127, "
            "Gebäudeabschnitt Nord"
        ),
        "postalCode": "86199",
        "city": "Augsburg-Haunstetten-Siebenbrunn",
        "countryCode": "DE",
        "email": "rechnung@partnerschaften.invalid",
    }
    lines: list[dict[str, object]] = []
    amount_minor = 0
    for index in range(1, 29):
        quantity = (index % 4) + 1
        unit_price_minor = 1234 + index
        gross_minor = quantity * unit_price_minor
        amount_minor += gross_minor
        lines.append(
            {
                "description": (
                    f"Charity-Leistung {index:02d}: Krapfenboxen für die "
                    "gemeinsame Spendenaktion mit dokumentierter Auslieferung"
                ),
                "quantity": quantity,
                "unit": "box",
                "unitPriceGrossMinor": unit_price_minor,
                "taxRateBasisPoints": 0,
                "netMinor": gross_minor,
                "taxMinor": 0,
                "grossMinor": gross_minor,
                "currency": "EUR",
            }
        )
    payload["lines"] = lines
    payload["totals"] = {
        "netMinor": amount_minor,
        "taxMinor": 0,
        "grossMinor": amount_minor,
        "currency": "EUR",
    }
    payload["paymentReference"] = "KT26-LAYOUT-0001"
    return InvoiceDocumentSnapshot.from_payload(payload)


def _render_twice(
    *,
    renderer: TypstInvoiceRenderer,
    snapshot: InvoiceDocumentSnapshot,
    output: Path,
) -> dict[str, object]:
    first = renderer.render(snapshot)
    second = renderer.render(snapshot)
    if first.content != second.content or first.sha256 != second.sha256:
        raise RenderContractError(
            f"Rendering ist nicht byte-deterministisch: {snapshot.number}"
        )
    target = output / f"{snapshot.number}.pdf"
    target.write_bytes(first.content)
    return {
        "number": snapshot.number,
        "filename": target.name,
        "renderVersion": first.render_version,
        "sha256": first.sha256,
        "size": len(first.content),
        "snapshot": snapshot.payload(),
    }


def run_contract(
    *,
    database_snapshots: Path,
    fixture_directory: Path,
    output: Path,
) -> list[dict[str, object]]:
    database_value: Any = json.loads(database_snapshots.read_text(encoding="utf-8"))
    if not isinstance(database_value, list):
        raise RenderContractError("Der Datenbankexport ist keine Snapshot-Liste.")
    database_payloads = sorted(
        database_value,
        key=lambda item: str(item["number"]) if isinstance(item, dict) else "",
    )
    fixture_payloads = [
        _load_payload(path) for path in sorted(fixture_directory.glob("KT26-*.json"))
    ]
    fixture_payloads.sort(key=lambda item: str(item["number"]))
    if database_payloads != fixture_payloads:
        raise RenderContractError(
            "Datenbankexport und versionierte Renderer-Snapshots sind nicht identisch."
        )

    output.mkdir(parents=True, exist_ok=True)
    renderer = TypstInvoiceRenderer()
    manifest = [
        _render_twice(
            renderer=renderer,
            snapshot=InvoiceDocumentSnapshot.from_payload(payload),
            output=output,
        )
        for payload in fixture_payloads
    ]
    manifest.append(
        _render_twice(
            renderer=renderer,
            snapshot=_stress_snapshot(fixture_payloads[0]),
            output=output,
        )
    )
    (output / "contract-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database_snapshots", type=Path)
    parser.add_argument("fixture_directory", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    try:
        manifest = run_contract(
            database_snapshots=arguments.database_snapshots,
            fixture_directory=arguments.fixture_directory,
            output=arguments.output,
        )
    except (
        DomainInvariantError,
        json.JSONDecodeError,
        OSError,
        RenderContractError,
        TypstRenderError,
    ) as error:
        print(f"typst-render-contract: ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "typst-render-contract: OK: "
        f"{len(manifest)} Rechnungen zweifach und byte-identisch gerendert"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
