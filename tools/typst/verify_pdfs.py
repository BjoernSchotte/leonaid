"""Verify Typst invoices, cancellation invoices and donation pledges with two
independent real PDF engines."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import fitz  # type: ignore[import-untyped]
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

from leonaid.adapters.typst import (
    CANCELLATION_RENDER_VERSION,
    PLEDGE_RENDER_VERSION,
    RENDER_VERSION,
    cancellation_render_payload,
    pledge_render_payload,
    render_payload,
)
from leonaid.application.invoice_documents import InvoiceDocumentSnapshot
from leonaid.domain.donations import DonationPledgeDocument
from leonaid.domain.invoice_cancellation_documents import InvoiceCancellationDocument

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


@dataclass(frozen=True, slots=True)
class Subject:
    """What one rendered document must show, whatever its kind."""

    number: str
    title: str
    author: str
    render_version: str
    created_at: datetime
    expected_text: tuple[str, ...]
    # The multi-page edge cases must break the page.
    needs_page_break: bool
    # Words the document must not show: a pledge is no invoice.
    forbidden_text: tuple[str, ...] = ()
    # A letter that must stay on one page.
    single_page: bool = False


def _invoice_subject(snapshot: InvoiceDocumentSnapshot) -> Subject:
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
    return Subject(
        number=snapshot.number,
        title=f"Rechnung {snapshot.number}",
        author=snapshot.issuer.legal_name,
        render_version=RENDER_VERSION,
        created_at=snapshot.issued_at,
        expected_text=tuple(str(value) for value in expected),
        needs_page_break=snapshot.number == "KT26-LAYOUT-0001",
    )


def _cancellation_subject(document: InvoiceCancellationDocument) -> Subject:
    presentation = cancellation_render_payload(document)
    expected = [
        "Stornorechnung",
        document.number,
        presentation["reference"],
        presentation["introduction"],
        document.original_number,
        document.issuer.legal_name,
        document.issuer.street_line_1,
        document.recipient.recipient_name,
        document.recipient.street_line_1,
        presentation["issuedOn"],
        presentation["originalIssuedOn"],
        # Negative amounts: the minus sign is part of the proof.
        presentation["net"],
        presentation["tax"],
        presentation["gross"],
        document.tax_note,
        presentation["closing"],
    ]
    expected.extend(line.description for line in document.lines)
    rendered_lines = cast(list[dict[str, object]], presentation["lines"])
    expected.extend(str(line["gross"]) for line in rendered_lines)
    return Subject(
        number=document.number,
        title=f"Stornorechnung {document.number}",
        author=document.issuer.legal_name,
        render_version=CANCELLATION_RENDER_VERSION,
        created_at=document.issued_at,
        expected_text=tuple(str(value) for value in expected),
        needs_page_break=document.number == "KT26-LAYOUT-0002",
    )


def _pledge_subject(document: DonationPledgeDocument) -> Subject:
    presentation = pledge_render_payload(document)
    bank = cast(dict[str, object], presentation["bank"])
    expected = [
        "Spendenzusage",
        document.number,
        presentation["issuedOn"],
        presentation["amount"],
        presentation["thanks"],
        presentation["purpose"],
        presentation["request"],
        presentation["notice"],
        document.donor.name,
        document.donor.street_line_1,
        # The receiving body, never the invoice issuer.
        document.body.legal_name,
        document.body.street_line_1,
        document.body.tax_office,
        document.body.tax_number,
        document.body.bank_account_holder,
        bank["iban"],
        "Verwendungszweck",
    ]
    if document.body.bic is not None:
        expected.append(document.body.bic)
    return Subject(
        number=document.number,
        title=f"Spendenzusage {document.number}",
        author=document.body.legal_name,
        render_version=PLEDGE_RENDER_VERSION,
        created_at=document.issued_at,
        expected_text=tuple(str(value) for value in expected),
        # The longest values need a second page; a usual pledge is one letter.
        needs_page_break=document.number == "SP26-LAYOUT-0001",
        # "Rechnung" appears only in the body's own sentence "keine Rechnung".
        forbidden_text=(
            "Rechnungsnummer",
            "Rechnungsdatum",
            "Umsatzsteuer",
            "Netto",
            "Brutto",
            "Zahlbar bis",
        ),
        single_page=document.number != "SP26-LAYOUT-0001",
    )


def _assert_expected_text(
    *,
    subject: Subject,
    extracted: str,
    engine: str,
) -> None:
    normalized = _normal_text(extracted)
    missing = [
        value
        for value in subject.expected_text
        if _normal_text(value) not in normalized
    ]
    if missing:
        raise PdfVerificationError(
            f"{engine} is missing in {subject.number}: {missing[:4]}"
        )
    shown = [value for value in subject.forbidden_text if value in normalized]
    if shown:
        raise PdfVerificationError(
            f"{engine} finds invoice wording in {subject.number}: {shown}"
        )


def _subject_from_manifest(item: dict[str, object]) -> Subject:
    snapshot = item.get("snapshot")
    if not isinstance(snapshot, dict) or not all(
        isinstance(key, str) for key in snapshot
    ):
        raise PdfVerificationError("Renderer manifest contains no snapshot.")
    kind = item.get("kind", "invoice")
    if kind == "invoice":
        return _invoice_subject(InvoiceDocumentSnapshot.from_payload(snapshot))
    if kind == "invoice_cancellation":
        return _cancellation_subject(InvoiceCancellationDocument.from_payload(snapshot))
    if kind == "donation_pledge":
        return _pledge_subject(DonationPledgeDocument.from_payload(snapshot))
    raise PdfVerificationError(f"Renderer manifest names an unknown kind: {kind}")


def _verify_metadata(
    *,
    subject: Subject,
    reader: PdfReader,
) -> None:
    metadata = reader.metadata
    if metadata is None:
        raise PdfVerificationError(f"metadata missing: {subject.number}")
    if metadata.title != subject.title:
        raise PdfVerificationError(f"PDF title is wrong: {subject.number}")
    if metadata.author != subject.author:
        raise PdfVerificationError(f"PDF author is wrong: {subject.number}")
    keywords = str(metadata.get("/Keywords", ""))
    if "LeonAid" not in keywords or subject.render_version not in keywords:
        raise PdfVerificationError(f"render version missing: {subject.number}")
    creation_date = metadata.creation_date
    if creation_date is None or creation_date != subject.created_at:
        raise PdfVerificationError(
            f"PDF creation time is not the issue time: {subject.number}"
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
        raise PdfVerificationError(f"approved golden images missing: {number}")
    if len(rendered) != len(golden):
        raise PdfVerificationError(f"page count differs from golden image: {number}")
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
                f"visual difference {actual.name}: "
                f"{actual_digest} instead of {expected_digest}"
            )


def _verify_one(
    *,
    pdf_path: Path,
    snapshot: Subject,
    image_directory: Path,
    golden_directory: Path | None,
) -> dict[str, object]:
    reader = PdfReader(pdf_path, strict=True)
    if not reader.pages:
        raise PdfVerificationError(f"pypdf finds no pages: {snapshot.number}")
    for page in reader.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        if abs(width - A4_WIDTH_POINTS) > 0.5 or abs(height - A4_HEIGHT_POINTS) > 0.5:
            raise PdfVerificationError(f"page format is not A4: {snapshot.number}")
    pypdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    _assert_expected_text(subject=snapshot, extracted=pypdf_text, engine="pypdf")
    _verify_metadata(subject=snapshot, reader=reader)
    forbidden = _forbidden_keys(reader.trailer, set())
    if forbidden:
        raise PdfVerificationError(
            f"external/active PDF resources found: {sorted(forbidden)}"
        )

    with fitz.open(pdf_path) as document:
        if document.page_count != len(reader.pages):
            raise PdfVerificationError(f"PDF engines disagree on {snapshot.number}.")
        mupdf_text = "\n".join(page.get_text("text") for page in document)
        _assert_expected_text(subject=snapshot, extracted=mupdf_text, engine="MuPDF")
        font_xrefs = {
            int(font[0])
            for page in document
            for font in page.get_fonts(full=True)
            if int(font[0]) > 0
        }
        if not font_xrefs:
            raise PdfVerificationError(f"PDF uses no font: {snapshot.number}")
        for xref in font_xrefs:
            _name, extension, _font_type, content = document.extract_font(xref)
            if not extension or not content:
                raise PdfVerificationError(
                    f"font is not embedded: {snapshot.number}, XRef {xref}"
                )
        images = _render_pages(document, image_directory, snapshot.number)

    if snapshot.needs_page_break and len(images) < 2:
        raise PdfVerificationError(
            f"The layout edge case produces no page break: {snapshot.number}"
        )
    if snapshot.single_page and len(images) != 1:
        raise PdfVerificationError(
            f"The letter does not fit on one page: {snapshot.number}"
        )
    # Every rendered document has approved reference images.
    if golden_directory is not None:
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
    templates: list[Path],
) -> list[dict[str, object]]:
    for template in templates:
        template_source = template.read_text(encoding="utf-8")
        if re.search(r"https?://|@preview|#image\s*\(", template_source, re.I):
            raise PdfVerificationError(
                f"The template {template.name} references an external runtime resource."
            )
    manifest_value: Any = json.loads(
        (pdf_directory / "contract-manifest.json").read_text(encoding="utf-8")
    )
    if not isinstance(manifest_value, list):
        raise PdfVerificationError("Renderer manifest is not a list.")
    image_directory.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for value in manifest_value:
        if not isinstance(value, dict) or not all(
            isinstance(key, str) for key in value
        ):
            raise PdfVerificationError("Renderer manifest contains an invalid entry.")
        snapshot = _subject_from_manifest(value)
        pdf_path = pdf_directory / str(value.get("filename"))
        expected_digest = str(value.get("sha256"))
        actual_digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            raise PdfVerificationError(f"PDF checksum is wrong: {snapshot.number}")
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
        action="append",
        required=True,
        help="A versioned Typst template; repeat for every document kind.",
    )
    arguments = parser.parse_args()
    try:
        results = verify(
            pdf_directory=arguments.pdf_directory,
            image_directory=arguments.image_directory,
            golden_directory=arguments.golden_directory,
            templates=arguments.template,
        )
    except (OSError, PdfVerificationError, ValueError) as error:
        print(f"typst-pdf-verification: ERROR: {error}", file=sys.stderr)
        return 1
    page_counts = [item["pages"] for item in results]
    total_pages = sum(value for value in page_counts if isinstance(value, int))
    print(
        "typst-pdf-verification: OK: "
        f"{len(results)} PDFs opened in pypdf and MuPDF; "
        f"{total_pages} pages checked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
