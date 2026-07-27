"""Render versioned invoice snapshots with the production Typst adapter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from leonaid.adapters.typst import TypstInvoiceRenderer, TypstRenderError
from leonaid.application.invoice_documents import InvoiceDocumentSnapshot
from leonaid.domain.errors import DomainInvariantError


class FixtureRenderError(RuntimeError):
    pass


def load_snapshot(path: Path) -> InvoiceDocumentSnapshot:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FixtureRenderError(
            f"Ungültiger Rechnungssnapshot: {path.name}"
        ) from error
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) for key in payload
    ):
        raise FixtureRenderError(f"Rechnungssnapshot ist kein JSON-Objekt: {path.name}")
    return InvoiceDocumentSnapshot.from_payload(payload)


def render_directory(source: Path, output: Path) -> list[dict[str, object]]:
    fixtures = sorted(source.glob("KT26-*.json"))
    if not fixtures:
        raise FixtureRenderError("Keine versionierten Golden-Rechnungen gefunden.")
    output.mkdir(parents=True, exist_ok=True)
    renderer = TypstInvoiceRenderer()
    manifest: list[dict[str, object]] = []
    for path in fixtures:
        snapshot = load_snapshot(path)
        first = renderer.render(snapshot)
        second = renderer.render(snapshot)
        if first.content != second.content or first.sha256 != second.sha256:
            raise FixtureRenderError(
                f"Rendering ist nicht byte-deterministisch: {snapshot.number}"
            )
        target = output / f"{snapshot.number}.pdf"
        target.write_bytes(first.content)
        manifest.append(
            {
                "invoiceId": str(snapshot.invoice_id),
                "number": snapshot.number,
                "filename": target.name,
                "renderVersion": first.render_version,
                "sha256": first.sha256,
                "size": len(first.content),
            }
        )
    (output / "render-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    try:
        manifest = render_directory(
            arguments.source.resolve(),
            arguments.output.resolve(),
        )
    except (
        DomainInvariantError,
        FixtureRenderError,
        OSError,
        TypstRenderError,
    ) as error:
        print(f"typst-fixtures: ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "typst-fixtures: OK: "
        f"{len(manifest)} Rechnungen mit identischen Doppelrenderings"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
