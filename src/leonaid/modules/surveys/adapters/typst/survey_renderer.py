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

from pypdf import PdfReader
from pypdf.generic import ByteStringObject, ContentStream, TextStringObject

from leonaid.modules.surveys.application.disclosure import (
    AnalysisSnapshot as DisclosedSnapshot,
)
from leonaid.modules.surveys.application.export_rendering import (
    SurveyExportArtifact,
    SurveyExportRenderError,
    SurveyExportSource,
    export_filename,
    UNRELEASED_CONDITION_NOTE,
    shown_count,
    withheld_legend,
    withheld_note,
)

TYPST_VERSION = "0.13.1"
# v7: report PDFs under the disclosure rules of review round 5 (Task
# 5.6b). Bump with every change of disclose() (see DISCLOSED_SINCE).
RENDER_VERSION = f"survey-analysis-v7+typst-{TYPST_VERSION}"
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
    # The export adapter passes the disclosed snapshot (k = 5); the renderer
    # draws what it gets, so its own checks can use full numbers.
    snapshot = source.snapshot
    k = snapshot.minimumGroupSize if isinstance(snapshot, DisclosedSnapshot) else None
    questions = []
    for question in snapshot.questions:

        def distribution(
            label: str, denominator: int | None, counts: Any
        ) -> dict[str, Any]:
            shown = shown_count(denominator)
            return {
                "label": label,
                "denominator": shown,
                "rows": [
                    {
                        "label": bucket.label,
                        "count": shown_count(bucket.count),
                        "denominator": shown,
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
        # The disclosed model has no "sum" (R3); a stored one still does.
        metrics = [
            {"label": label, "value": number(getattr(question, key, None))}
            for key, label in (
                ("sum", "Summe"),
                ("mean", "Mittelwert"),
                ("minimum", "Minimum"),
                ("maximum", "Maximum"),
                ("nps", "Net Promoter Score"),
            )
            if getattr(question, key, None) is not None
        ]
        if getattr(question, "withheldReason", None) == "unreleasedCondition":
            metrics.append({"label": "Hinweis", "value": UNRELEASED_CONDITION_NOTE})
        elif k is not None and getattr(question, "suppressed", False):
            metrics.append({"label": "Hinweis", "value": withheld_note(k)})
        hidden_rows = [
            row.label
            for row in question.matrixRows
            if getattr(row, "suppressed", False)
        ]
        if k is not None and hidden_rows:
            metrics.append(
                {
                    "label": "Hinweis",
                    "value": f"Ohne Auswertung (weniger als {k} gültige Antworten oder daraus ableitbar): "
                    + ", ".join(hidden_rows),
                }
            )
        questions.append(
            {
                "id": question.questionId,
                "title": question.title,
                "kind": question.kind,
                "relevant": shown_count(question.relevant),
                "answered": shown_count(question.answered),
                "unanswered": shown_count(question.unanswered),
                "hidden": shown_count(question.hidden),
                "invalid": shown_count(question.invalid),
                "metrics": metrics,
                "groups": groups,
                "matrixRows": [
                    {
                        "label": row.label,
                        "answered": shown_count(row.answered),
                        "unanswered": shown_count(row.unanswered),
                        "invalid": shown_count(row.invalid),
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
        "participationCount": shown_count(snapshot.participationCount),
        "statusCounts": [
            {"label": STATUSES[key], "count": shown_count(v)}
            for key, v in snapshot.statusCounts.model_dump().items()
        ],
        "lastPages": [
            {"label": p.title, "count": shown_count(p.count)}
            for p in snapshot.lastPageCounts
        ],
        "questions": questions,
        "withheldLegend": withheld_legend(k) if k else None,
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
            export_filename("analysis_pdf", source.snapshot.id),
            "application/pdf",
            RENDER_VERSION,
            content,
        )
