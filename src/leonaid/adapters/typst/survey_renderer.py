"""Private-data-free, deterministic Typst survey analysis reports."""

from __future__ import annotations

import json
import io
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pypdf import PdfReader
from pypdf.generic import ByteStringObject, ContentStream, TextStringObject

from leonaid.application.surveys.analysis_snapshot import AnalysisSnapshot
from leonaid.application.surveys.export_rendering import (
    SurveyExportArtifact,
    SurveyExportRenderError,
    SurveyExportSource,
)

TYPST_VERSION = "0.13.1"
RENDER_VERSION = f"survey-analysis-v1+typst-{TYPST_VERSION}"
DEFAULT_TEMPLATE = Path(__file__).with_name("templates") / "survey-analysis-v1.typ"
STATUSES = {
    "in_progress": "In Bearbeitung",
    "partial": "Teilweise beantwortet",
    "completed": "Abgeschlossen",
}


def number(value: int | float | None) -> str:
    if value is None:
        return "Nicht verfügbar"
    return f"{value:,.2f}".rstrip("0").rstrip(".").translate(str.maketrans(",.", ".,"))


def render_payload(source: SurveyExportSource) -> dict[str, Any]:
    snapshot = AnalysisSnapshot.model_validate(source.snapshot.model_dump())
    questions = []
    for question in snapshot.questions:

        def distribution(label: str, denominator: int, counts: Any) -> dict[str, Any]:
            return {
                "label": label,
                "denominator": denominator,
                "rows": [
                    {
                        "label": bucket.label,
                        "count": bucket.count,
                        "denominator": denominator,
                        "percentage": bucket.percentage or 0,
                        "percentageLabel": number(bucket.percentage) + " %"
                        if bucket.percentage is not None
                        else "Nicht verfügbar",
                    }
                    for bucket in counts
                ],
            }

        groups = (
            [distribution("Antwortverteilung", question.answered, question.counts)]
            if question.counts
            else []
        )

        groups.extend(
            distribution(row.label, row.answered, row.counts)
            for row in question.matrixRows
        )
        metrics = [
            {"label": label, "value": number(getattr(question, key))}
            for key, label in (
                ("sum", "Summe"),
                ("mean", "Mittelwert"),
                ("minimum", "Minimum"),
                ("maximum", "Maximum"),
                ("nps", "Net Promoter Score"),
            )
            if getattr(question, key) is not None
        ]
        questions.append(
            {
                "id": question.questionId,
                "title": question.title,
                "kind": question.kind,
                "relevant": question.relevant,
                "answered": question.answered,
                "unanswered": question.unanswered,
                "hidden": question.hidden,
                "invalid": question.invalid,
                "metrics": metrics,
                "groups": groups,
                "matrixRows": [
                    {
                        "label": row.label,
                        "answered": row.answered,
                        "unanswered": row.unanswered,
                        "invalid": row.invalid,
                    }
                    for row in question.matrixRows
                ],
            }
        )
    return {
        "title": source.title,
        "snapshotId": snapshot.id,
        "surveyId": snapshot.surveyId,
        "createdAt": snapshot.createdAt,
        "versionId": snapshot.filter.versionId,
        "versionNumber": snapshot.versionNumber,
        "rendererVersion": snapshot.rendererVersion,
        "renderVersion": RENDER_VERSION,
        "capabilityProfile": snapshot.capabilityProfile,
        "statuses": ", ".join(STATUSES[s] for s in snapshot.filter.statuses),
        "testData": "Testantworten" if snapshot.filter.isTest else "Echte Antworten",
        "createdFrom": snapshot.filter.createdFrom or "Ohne Untergrenze",
        "createdBefore": snapshot.filter.createdBefore or "Ohne Obergrenze",
        "participationCount": snapshot.participationCount,
        "statusCounts": [
            {"label": STATUSES[k], "count": v}
            for k, v in snapshot.statusCounts.model_dump().items()
        ],
        "lastPages": [
            {"label": p.title, "count": p.count} for p in snapshot.lastPageCounts
        ],
        "questions": questions,
    }


def verify_glyphs(content: bytes) -> None:
    """Reject .notdef glyphs in the pinned Typst/CFF Identity-H output profile.

    Typst 0.13.1 emits glyph zero for unsupported characters without warning.
    Extracted Unicode alone cannot detect the visible replacement boxes.
    """
    try:
        reader = PdfReader(io.BytesIO(content))

        def check(stream: Any, resources: Any) -> None:
            for font_reference in resources.get("/Font", {}).values():
                font = font_reference.get_object()
                if font.get("/Encoding") != "/Identity-H" or any(
                    descendant.get_object().get("/Subtype") != "/CIDFontType0"
                    for descendant in font.get("/DescendantFonts", [])
                ):
                    raise SurveyExportRenderError("typst_font_profile_unverified")
            for operands, operator in ContentStream(stream, reader).operations:
                values = (
                    operands[0]
                    if operator == b"TJ"
                    else operands[-1:]
                    if operator in (b"Tj", b"'", b'"')
                    else []
                )
                for value in values:
                    if isinstance(value, (TextStringObject, ByteStringObject)):
                        raw = (
                            value.original_bytes
                            if isinstance(value, TextStringObject)
                            else bytes(value)
                        )
                        if len(raw) % 2 or any(
                            raw[i : i + 2] == b"\x00\x00" for i in range(0, len(raw), 2)
                        ):
                            raise SurveyExportRenderError("typst_font_glyph_missing")
            for reference in resources.get("/XObject", {}).values():
                obj = reference.get_object()
                if obj.get("/Subtype") == "/Form":
                    check(obj, obj.get("/Resources", resources))

        for page in reader.pages:
            check(page.get_contents(), page["/Resources"])
    except SurveyExportRenderError:
        raise
    except Exception:
        raise SurveyExportRenderError("typst_pdf_verification_failed") from None


class TypstSurveyRenderer:
    def __init__(
        self,
        *,
        executable: str = "typst",
        template: Path = DEFAULT_TEMPLATE,
        timeout_seconds: int = 30,
    ) -> None:
        self.executable = executable
        self.template = template
        self.timeout_seconds = timeout_seconds

    def render(self, source: SurveyExportSource) -> SurveyExportArtifact:
        try:
            runtime = subprocess.run(
                [self.executable, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if runtime.returncode != 0 or not re.match(
                r"^typst 0\.13\.1(?:\s|$)", runtime.stdout
            ):
                raise SurveyExportRenderError("typst_version_mismatch")
            payload = render_payload(source)
            timestamp = int(
                datetime.fromisoformat(source.snapshot.createdAt).timestamp()
            )
            with tempfile.TemporaryDirectory(prefix="survey-report-") as directory:
                work = Path(directory)
                shutil.copyfile(self.template, work / "report.typ")
                (work / "report.json").write_text(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [
                        self.executable,
                        "compile",
                        "--root",
                        directory,
                        "--creation-timestamp",
                        str(timestamp),
                        "--jobs",
                        "1",
                        str(work / "report.typ"),
                        str(work / "report.pdf"),
                    ],
                    cwd=work,
                    env={
                        "HOME": directory,
                        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                        "SOURCE_DATE_EPOCH": str(timestamp),
                    },
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
                # Diagnostics can contain authored text: discard them. Missing
                # glyphs additionally need inspection of the rendered PDF below.
                if result.returncode != 0 or result.stderr.strip():
                    raise SurveyExportRenderError("typst_report_failed")
                content = (work / "report.pdf").read_bytes()
                if not content.startswith(b"%PDF-"):
                    raise SurveyExportRenderError("typst_report_failed")
                verify_glyphs(content)
        except SurveyExportRenderError:
            raise
        except (OSError, ValueError, subprocess.SubprocessError):
            raise SurveyExportRenderError("typst_report_failed") from None
        return SurveyExportArtifact(
            f"survey-{UUID(source.snapshot.id)}-analysis.pdf",
            "application/pdf",
            RENDER_VERSION,
            content,
        )
