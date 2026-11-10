"""Exercise deterministic normal and multi-page rendering of invoices and
cancellation invoices, and of donation pledges."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from leonaid.adapters.typst import (
    TypstDonationPledgeRenderer,
    TypstInvoiceCancellationRenderer,
    TypstInvoiceRenderer,
    TypstRenderError,
)
from leonaid.application.invoice_documents import InvoiceDocumentSnapshot
from leonaid.domain.donations import DonationPledgeDocument
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.invoice_cancellation_documents import InvoiceCancellationDocument


class RenderContractError(RuntimeError):
    pass


def _load_payload(path: Path) -> dict[str, object]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RenderContractError(f"invalid snapshot JSON: {path.name}")
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


def _stress_cancellation(
    invoice_base: dict[str, object],
    cancellation_base: dict[str, object],
) -> InvoiceCancellationDocument:
    """A cancellation invoice of the multi-page invoice, with money received."""

    original = _stress_snapshot(invoice_base)
    payload = json.loads(json.dumps(cancellation_base))
    payload["cancellationId"] = "97000000-0000-4000-8000-000000000091"
    payload["invoiceId"] = str(original.invoice_id)
    payload["number"] = "KT26-LAYOUT-0002"
    payload["originalNumber"] = original.number
    payload["recipient"] = original.recipient.payload()
    payload["lines"] = [line.payload() for line in original.lines]
    payload["totals"] = original.payload()["totals"]
    payload["receivedMinor"] = original.gross.amount_minor
    return InvoiceCancellationDocument.from_payload(payload)


def _stress_pledge(base: dict[str, object]) -> DonationPledgeDocument:
    """The longest values a pledge can carry: the letter breaks the page."""

    payload = json.loads(json.dumps(base))
    payload["donationId"] = "d0000000-0000-4000-8000-000000000091"
    payload["number"] = "SP26-LAYOUT-0001"
    payload["amountMinor"] = 100_000_000
    payload["donor"] = {
        **payload["donor"],
        "name": (
            "Arbeitsgemeinschaft für besonders nachhaltige "
            "Unternehmenspartnerschaften Süddeutschland mbH & Co. KG"
        ),
        "streetLine1": (
            "Dr.-Elisabeth-von-der-Wirkungsgemeinschaft-Promenade 127, "
            "Gebäudeabschnitt Nord"
        ),
        "postalCode": "86199",
        "city": "Augsburg-Haunstetten-Siebenbrunn",
    }
    payload["actionName"] = (
        "Gemeinsame Weihnachtsaktion der Serviceclubs im Landkreis mit "
        "Krapfentaxi, Glühweinstand und Benefizkonzert 2026"
    )
    payload["actionPurpose"] = (
        "Der Erlös geht je zur Hälfte an die offene Jugendarbeit der "
        "Gemeinde und an die Tafel im Ort; über die Verwendung berichtet "
        "der Club nach Abschluss der Aktion auf seiner Internetseite."
    )
    sentence = (
        "Ihre Spende ist freiwillig; Sie erhalten dafür keine Gegenleistung, "
        "und dieses Schreiben ist keine Rechnung. "
    )
    payload["body"] = {
        **payload["body"],
        "legalName": (
            "Förderverein der Freunde und Förderer des Lions Clubs "
            "Musterstadt an der Beispielach und Umgebung e. V."
        ),
        "bankAccountHolder": (
            "Förderverein der Freunde und Förderer des Lions Clubs "
            "Musterstadt an der Beispielach und Umgebung e. V."
        ),
        "pledgeText": (sentence * 17).strip(),
    }
    return DonationPledgeDocument.from_payload(payload)


KINDS: dict[type, str] = {
    InvoiceDocumentSnapshot: "invoice",
    InvoiceCancellationDocument: "invoice_cancellation",
    DonationPledgeDocument: "donation_pledge",
}


def _render_twice(
    *,
    renderer: (
        TypstInvoiceRenderer
        | TypstInvoiceCancellationRenderer
        | TypstDonationPledgeRenderer
    ),
    snapshot: (
        InvoiceDocumentSnapshot | InvoiceCancellationDocument | DonationPledgeDocument
    ),
    output: Path,
) -> dict[str, object]:
    first = renderer.render(snapshot)  # type: ignore[arg-type]
    second = renderer.render(snapshot)  # type: ignore[arg-type]
    if first.content != second.content or first.sha256 != second.sha256:
        raise RenderContractError(
            f"rendering is not byte-deterministic: {snapshot.number}"
        )
    target = output / f"{snapshot.number}.pdf"
    target.write_bytes(first.content)
    return {
        "kind": KINDS[type(snapshot)],
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
    cancellation_directory: Path,
    donation_directory: Path,
    output: Path,
) -> list[dict[str, object]]:
    database_value: Any = json.loads(database_snapshots.read_text(encoding="utf-8"))
    if not isinstance(database_value, list):
        raise RenderContractError("The database export is not a snapshot list.")
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
            "Database export and versioned renderer snapshots are not identical."
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
    # Cancellation invoices: the versioned snapshots and a multi-page one.
    cancellation_payloads = [
        _load_payload(path)
        for path in sorted(cancellation_directory.glob("KT26-*.json"))
    ]
    if not cancellation_payloads:
        raise RenderContractError("No versioned cancellation invoices found.")
    cancellation_renderer = TypstInvoiceCancellationRenderer()
    for payload in cancellation_payloads:
        manifest.append(
            _render_twice(
                renderer=cancellation_renderer,
                snapshot=InvoiceCancellationDocument.from_payload(payload),
                output=output,
            )
        )
    manifest.append(
        _render_twice(
            renderer=cancellation_renderer,
            snapshot=_stress_cancellation(
                fixture_payloads[0], cancellation_payloads[-1]
            ),
            output=output,
        )
    )
    # Donation pledges: the versioned snapshots and the longest values.
    pledge_payloads = [
        _load_payload(path) for path in sorted(donation_directory.glob("SP26-*.json"))
    ]
    if not pledge_payloads:
        raise RenderContractError("No versioned donation pledges found.")
    pledge_renderer = TypstDonationPledgeRenderer()
    for payload in pledge_payloads:
        manifest.append(
            _render_twice(
                renderer=pledge_renderer,
                snapshot=DonationPledgeDocument.from_payload(payload),
                output=output,
            )
        )
    manifest.append(
        _render_twice(
            renderer=pledge_renderer,
            snapshot=_stress_pledge(pledge_payloads[0]),
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
    parser.add_argument("cancellation_directory", type=Path)
    parser.add_argument("donation_directory", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    try:
        manifest = run_contract(
            database_snapshots=arguments.database_snapshots,
            fixture_directory=arguments.fixture_directory,
            cancellation_directory=arguments.cancellation_directory,
            donation_directory=arguments.donation_directory,
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
        f"{len(manifest)} documents rendered twice with identical bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
