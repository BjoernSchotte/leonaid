"""Render versioned invoice snapshots with the production Typst adapter."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
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
        target.unlink(missing_ok=True)
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
    (output / "render-manifest.json").unlink(missing_ok=True)
    (output / "render-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def cached_manifest(
    source: Path, output: Path, renderer_id: str
) -> list[dict[str, object]]:
    """Reuse only matching renderer/inputs and independently hashed output bytes."""
    digest = hashlib.sha256(renderer_id.encode() + Path(__file__).read_bytes())
    for path in sorted(source.glob("KT26-*.json")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    key = digest.hexdigest()
    receipt = output / ".render-cache.json"
    try:
        cache = json.loads(receipt.read_text())
        manifest = json.loads((output / "render-manifest.json").read_text())
        if (
            cache["key"] == key
            and manifest
            and all(
                Path(item["filename"]).name == item["filename"]
                and not (output / item["filename"]).is_symlink()
                and hashlib.sha256((output / item["filename"]).read_bytes()).hexdigest()
                == item["sha256"]
                for item in manifest
            )
            and hashlib.sha256(
                (output / "render-manifest.json").read_bytes()
            ).hexdigest()
            == cache["manifestSha256"]
        ):
            print("typst-fixtures: reuse verified immutable PDFs")
            return list(manifest)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    receipt.unlink(missing_ok=True)
    manifest = render_directory(source, output)
    receipt.write_text(
        json.dumps(
            {
                "key": key,
                "manifestSha256": hashlib.sha256(
                    (output / "render-manifest.json").read_bytes()
                ).hexdigest(),
            }
        )
        + "\n"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--renderer-id", help="Opt into verified reuse for this immutable image ID"
    )
    arguments = parser.parse_args()
    try:
        output = arguments.output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        # A local seed and a test may request the same synthetic PDFs concurrently.
        with (output / ".render.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            manifest = (
                cached_manifest(
                    arguments.source.resolve(), output, arguments.renderer_id
                )
                if arguments.renderer_id
                else render_directory(arguments.source.resolve(), output)
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
