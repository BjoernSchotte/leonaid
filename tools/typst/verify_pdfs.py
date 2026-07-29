"""Verify Typst invoices with two independent real PDF engines."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

import fitz  # type: ignore[import-untyped]
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

from leonaid.adapters.typst import RENDER_VERSION, render_payload
from leonaid.application.invoice_documents import InvoiceDocumentSnapshot

A4_WIDTH_POINTS = 595.28
A4_HEIGHT_POINTS = 841.89
FORBIDDEN_PDF_KEYS = frozenset(
    {"/AA", "/GoToR", "/JavaScript", "/JS", "/Launch", "/OpenAction", "/URI"}
)


class PdfVerificationError(RuntimeError):
    pass


def _normal_text(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split())


def _forbidden_keys(value: Any, seen: set[tuple[int, int]]) -> set[str]:
    if isinstance(value, IndirectObject):
        identity = (value.idnum, value.generation)
        if identity in seen:
            return set()
        seen.add(identity)
        value = value.get_object()
    if isinstance(value, DictionaryObject):
        dictionary_keys = {str(key) for key in value if str(key) in FORBIDDEN_PDF_KEYS}
        for nested in value.values():
            if not hasattr(nested, "get_data"):
                dictionary_keys.update(_forbidden_keys(nested, seen))
        return dictionary_keys
    if isinstance(value, ArrayObject):
        array_keys: set[str] = set()
        for nested in value:
            array_keys.update(_forbidden_keys(nested, seen))
        return array_keys
    return set()


def _assert_expected_text(
    *,
    snapshot: InvoiceDocumentSnapshot,
    extracted: str,
    engine: str,
) -> None:
    presentation = render_payload(snapshot)
    payment_details = cast(dict[str, object], presentation["paymentDetails"])
    expected = [
        "Rechnung",
        snapshot.number,
        snapshot.issuer.legal_name,
        snapshot.issuer.street_line_1,
        snapshot.recipient.recipient_name,
        snapshot.recipient.street_line_1,
        presentation["issuedOn"],
        presentation["serviceOn"],
        presentation["dueOn"],
        presentation["net"],
        presentation["tax"],
        presentation["gross"],
        snapshot.tax_note,
        snapshot.payment_reference,
        snapshot.payment_details.account_holder,
        payment_details["iban"],
    ]
    if snapshot.payment_details.bic is not None:
        expected.append(snapshot.payment_details.bic)
    expected.extend(line.description for line in snapshot.lines)
    rendered_lines = cast(list[dict[str, object]], presentation["lines"])
    expected.extend(str(line["gross"]) for line in rendered_lines)
    normalized = _normal_text(extracted)
    missing = [
        str(value) for value in expected if _normal_text(str(value)) not in normalized
    ]
    if missing:
        raise PdfVerificationError(
            f"{engine} vermisst in {snapshot.number}: {missing[:4]}"
        )


def _snapshot_from_manifest(item: dict[str, object]) -> InvoiceDocumentSnapshot:
    snapshot = item.get("snapshot")
    if not isinstance(snapshot, dict) or not all(
        isinstance(key, str) for key in snapshot
    ):
        raise PdfVerificationError("Renderer-Manifest enthält keinen Snapshot.")
    return InvoiceDocumentSnapshot.from_payload(snapshot)


def _verify_metadata(
    *,
    snapshot: InvoiceDocumentSnapshot,
    reader: PdfReader,
) -> None:
    metadata = reader.metadata
    if metadata is None:
        raise PdfVerificationError(f"Metadaten fehlen: {snapshot.number}")
    if metadata.title != f"Rechnung {snapshot.number}":
        raise PdfVerificationError(f"PDF-Titel ist falsch: {snapshot.number}")
    if metadata.author != snapshot.issuer.legal_name:
        raise PdfVerificationError(f"PDF-Autor ist falsch: {snapshot.number}")
    keywords = str(metadata.get("/Keywords", ""))
    if "LeonAid" not in keywords or RENDER_VERSION not in keywords:
        raise PdfVerificationError(f"Render-Version fehlt: {snapshot.number}")
    creation_date = metadata.creation_date
    if creation_date is None or creation_date != snapshot.issued_at:
        raise PdfVerificationError(
            f"PDF-Erzeugungszeit ist nicht der Freigabezeitpunkt: {snapshot.number}"
        )


def _render_pages(
    document: fitz.Document, image_directory: Path, number: str
) -> list[Path]:
    paths: list[Path] = []
    matrix = fitz.Matrix(2, 2)
    for page_index, page in enumerate(document):
        pixmap = page.get_pixmap(matrix=matrix, alpha=False, colorspace=fitz.csRGB)
        target = image_directory / f"{number}-page-{page_index + 1}.png"
        pixmap.save(target)
        paths.append(target)
    return paths


def _assert_golden_images(
    *,
    rendered: list[Path],
    golden_directory: Path,
    number: str,
) -> None:
    golden = sorted(golden_directory.glob(f"{number}-page-*.png"))
    if not golden:
        raise PdfVerificationError(f"Freigegebene Golden-Bilder fehlen: {number}")
    if len(rendered) != len(golden):
        raise PdfVerificationError(f"Seitenzahl weicht vom Golden-Bild ab: {number}")
    for actual, expected in zip(rendered, golden, strict=True):
        actual_pixmap = fitz.Pixmap(str(actual))
        expected_pixmap = fitz.Pixmap(str(expected))
        same_geometry = (
            actual_pixmap.width == expected_pixmap.width
            and actual_pixmap.height == expected_pixmap.height
            and actual_pixmap.n == expected_pixmap.n
        )
        if not same_geometry or actual_pixmap.samples != expected_pixmap.samples:
            actual_digest = hashlib.sha256(actual_pixmap.samples).hexdigest()[:12]
            expected_digest = hashlib.sha256(expected_pixmap.samples).hexdigest()[:12]
            raise PdfVerificationError(
                f"Visuelle Abweichung {actual.name}: "
                f"{actual_digest} statt {expected_digest}"
            )


def _verify_one(
    *,
    pdf_path: Path,
    snapshot: InvoiceDocumentSnapshot,
    image_directory: Path,
    golden_directory: Path | None,
) -> dict[str, object]:
    reader = PdfReader(pdf_path, strict=True)
    if not reader.pages:
        raise PdfVerificationError(f"pypdf findet keine Seiten: {snapshot.number}")
    for page in reader.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        if abs(width - A4_WIDTH_POINTS) > 0.5 or abs(height - A4_HEIGHT_POINTS) > 0.5:
            raise PdfVerificationError(f"Seitenformat ist nicht A4: {snapshot.number}")
    pypdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    _assert_expected_text(snapshot=snapshot, extracted=pypdf_text, engine="pypdf")
    _verify_metadata(snapshot=snapshot, reader=reader)
    forbidden = _forbidden_keys(reader.trailer, set())
    if forbidden:
        raise PdfVerificationError(
            f"Externe/aktive PDF-Ressourcen gefunden: {sorted(forbidden)}"
        )

    with fitz.open(pdf_path) as document:
        if document.page_count != len(reader.pages):
            raise PdfVerificationError(
                f"PDF-Engines widersprechen sich bei {snapshot.number}."
            )
        mupdf_text = "\n".join(page.get_text("text") for page in document)
        _assert_expected_text(snapshot=snapshot, extracted=mupdf_text, engine="MuPDF")
        font_xrefs = {
            int(font[0])
            for page in document
            for font in page.get_fonts(full=True)
            if int(font[0]) > 0
        }
        if not font_xrefs:
            raise PdfVerificationError(
                f"PDF verwendet keine Schrift: {snapshot.number}"
            )
        for xref in font_xrefs:
            _name, extension, _font_type, content = document.extract_font(xref)
            if not extension or not content:
                raise PdfVerificationError(
                    f"Schrift ist nicht eingebettet: {snapshot.number}, XRef {xref}"
                )
        images = _render_pages(document, image_directory, snapshot.number)

    if snapshot.number == "KT26-LAYOUT-0001" and len(images) < 2:
        raise PdfVerificationError("Der Layout-Grenzfall erzeugt keinen Seitenumbruch.")
    if golden_directory is not None and snapshot.number in {
        "KT26-0001",
        "KT26-LAYOUT-0001",
    }:
        _assert_golden_images(
            rendered=images,
            golden_directory=golden_directory,
            number=snapshot.number,
        )
    return {
        "number": snapshot.number,
        "pages": len(images),
        "fonts": len(font_xrefs),
        "pypdfTextCharacters": len(pypdf_text),
        "mupdfTextCharacters": len(mupdf_text),
    }


def verify(
    *,
    pdf_directory: Path,
    image_directory: Path,
    golden_directory: Path | None,
    template: Path,
) -> list[dict[str, object]]:
    template_source = template.read_text(encoding="utf-8")
    if re.search(r"https?://|@preview|#image\s*\(", template_source, re.I):
        raise PdfVerificationError(
            "Die Rechnungsvorlage referenziert eine externe Laufzeitressource."
        )
    manifest_value: Any = json.loads(
        (pdf_directory / "contract-manifest.json").read_text(encoding="utf-8")
    )
    if not isinstance(manifest_value, list):
        raise PdfVerificationError("Renderer-Manifest ist keine Liste.")
    image_directory.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for value in manifest_value:
        if not isinstance(value, dict) or not all(
            isinstance(key, str) for key in value
        ):
            raise PdfVerificationError("Renderer-Manifest enthält ungültigen Eintrag.")
        snapshot = _snapshot_from_manifest(value)
        pdf_path = pdf_directory / str(value.get("filename"))
        expected_digest = str(value.get("sha256"))
        actual_digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            raise PdfVerificationError(f"PDF-Prüfsumme ist falsch: {snapshot.number}")
        results.append(
            _verify_one(
                pdf_path=pdf_path,
                snapshot=snapshot,
                image_directory=image_directory,
                golden_directory=golden_directory,
            )
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_directory", type=Path)
    parser.add_argument("image_directory", type=Path)
    parser.add_argument(
        "--golden-directory",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--template",
        type=Path,
        required=True,
    )
    arguments = parser.parse_args()
    try:
        results = verify(
            pdf_directory=arguments.pdf_directory,
            image_directory=arguments.image_directory,
            golden_directory=arguments.golden_directory,
            template=arguments.template,
        )
    except (OSError, PdfVerificationError, ValueError) as error:
        print(f"typst-pdf-verification: ERROR: {error}", file=sys.stderr)
        return 1
    page_counts = [item["pages"] for item in results]
    total_pages = sum(value for value in page_counts if isinstance(value, int))
    print(
        "typst-pdf-verification: OK: "
        f"{len(results)} PDFs in pypdf und MuPDF geöffnet; "
        f"{total_pages} Seiten geprüft"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
