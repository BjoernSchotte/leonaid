"""Deterministic server-side Typst invoice renderer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from leonaid.application.invoice_documents import (
    InvoiceDocumentSnapshot,
    RenderedInvoiceDocument,
)

TYPST_VERSION = "0.13.1"
TEMPLATE_VERSION = "invoice-v2"
RENDER_VERSION = f"{TEMPLATE_VERSION}+typst-{TYPST_VERSION}"
DEFAULT_TEMPLATE = Path(__file__).with_name("templates") / "invoice-v2.typ"

UNIT_LABELS = {
    "box": ("Box", "Boxen"),
    "piece": ("Stück", "Stück"),
    "sponsoring": ("Position", "Positionen"),
}


class TypstRenderError(RuntimeError):
    """Stable adapter error without leaking temporary paths or source payloads."""


def _date_label(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _money_label(amount_minor: int, currency: str) -> str:
    major, minor = divmod(amount_minor, 100)
    grouped = f"{major:,}".replace(",", ".")
    return f"{grouped},{minor:02d} {currency}"


def _unit_label(unit: str, quantity: int) -> str:
    singular, plural = UNIT_LABELS.get(unit, (unit, unit))
    return singular if quantity == 1 else plural


def _iban_label(value: str) -> str:
    return " ".join(value[index : index + 4] for index in range(0, len(value), 4))


def render_payload(snapshot: InvoiceDocumentSnapshot) -> dict[str, object]:
    """Create renderer-only presentation data from the immutable snapshot."""

    return {
        "renderVersion": RENDER_VERSION,
        "number": snapshot.number,
        "title": f"Rechnung {snapshot.number}",
        "issuedOn": _date_label(snapshot.issued_at.date()),
        "serviceOn": _date_label(snapshot.service_on),
        "dueOn": _date_label(snapshot.due_on),
        "issuer": snapshot.issuer.payload(),
        "paymentDetails": {
            **snapshot.payment_details.payload(),
            "iban": _iban_label(snapshot.payment_details.iban),
        },
        "recipient": snapshot.recipient.payload(),
        "lines": [
            {
                "description": line.description,
                "quantity": str(line.quantity),
                "unit": _unit_label(line.unit.value, line.quantity),
                "unitPrice": _money_label(
                    line.unit_price_gross.amount_minor,
                    line.unit_price_gross.currency,
                ),
                "net": _money_label(line.net.amount_minor, line.net.currency),
                "tax": _money_label(line.tax.amount_minor, line.tax.currency),
                "gross": _money_label(line.gross.amount_minor, line.gross.currency),
            }
            for line in snapshot.lines
        ],
        "net": _money_label(snapshot.net.amount_minor, snapshot.net.currency),
        "tax": _money_label(snapshot.tax.amount_minor, snapshot.tax.currency),
        "gross": _money_label(snapshot.gross.amount_minor, snapshot.gross.currency),
        "taxNote": snapshot.tax_note,
        "paymentReference": snapshot.payment_reference,
    }


class TypstInvoiceRenderer:
    def __init__(
        self,
        *,
        executable: str = "typst",
        template: Path = DEFAULT_TEMPLATE,
        timeout_seconds: int = 30,
    ) -> None:
        self._executable = executable
        self._template = template
        self._timeout_seconds = timeout_seconds
        self._runtime_verified = False

    def _verify_runtime(self) -> None:
        if self._runtime_verified:
            return
        try:
            result = subprocess.run(
                [self._executable, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise TypstRenderError(
                "Der gepinnte Typst-Renderer ist nicht ausführbar."
            ) from error
        expected = f"typst {TYPST_VERSION}"
        if result.returncode != 0 or not result.stdout.strip().startswith(expected):
            raise TypstRenderError(
                f"Typst-Laufzeit weicht vom erwarteten Stand {TYPST_VERSION} ab."
            )
        self._runtime_verified = True

    def render(
        self,
        snapshot: InvoiceDocumentSnapshot,
    ) -> RenderedInvoiceDocument:
        self._verify_runtime()
        if not self._template.is_file():
            raise TypstRenderError(
                f"Die versionierte Vorlage {TEMPLATE_VERSION} fehlt."
            )
        creation_timestamp = int(snapshot.issued_at.timestamp())
        with tempfile.TemporaryDirectory(prefix="leonaid-typst-") as temporary:
            work = Path(temporary)
            source = work / "invoice.typ"
            data = work / "invoice.json"
            output = work / "invoice.pdf"
            shutil.copyfile(self._template, source)
            data.write_text(
                json.dumps(
                    render_payload(snapshot),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            environment = {
                "HOME": temporary,
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "SOURCE_DATE_EPOCH": str(creation_timestamp),
            }
            try:
                result = subprocess.run(
                    [
                        self._executable,
                        "compile",
                        "--creation-timestamp",
                        str(creation_timestamp),
                        "--jobs",
                        "1",
                        str(source),
                        str(output),
                    ],
                    cwd=work,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise TypstRenderError(
                    f"Rechnung {snapshot.number} konnte nicht gerendert werden."
                ) from error
            if result.returncode != 0:
                raise TypstRenderError(
                    f"Typst konnte Rechnung {snapshot.number} nicht rendern."
                )
            try:
                content = output.read_bytes()
            except OSError as error:
                raise TypstRenderError(
                    f"Typst hat für Rechnung {snapshot.number} kein PDF abgelegt."
                ) from error
        return RenderedInvoiceDocument.create(
            content=content,
            filename=f"Rechnung-{snapshot.number}.pdf",
            render_version=RENDER_VERSION,
        )
