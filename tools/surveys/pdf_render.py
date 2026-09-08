"""Render real Typst reports, verify values and retain synthetic visual fixtures."""

import io
import json
from pathlib import Path

from pypdf import PdfReader

from leonaid.adapters.typst.survey_renderer import TypstSurveyRenderer, render_payload
from leonaid.application.surveys.analysis_snapshot import AnalysisSnapshot
from leonaid.application.surveys.export_rendering import (
    SurveyExportSource,
    SurveyExportRenderError,
)
from leonaid.application.surveys.response_selection import IndividualResponse


def main():
    snapshot = AnalysisSnapshot.model_validate_json(
        Path("tests/fixtures/surveys/export-snapshot.json").read_text()
    )
    output = Path(".artifacts/surveys-pdf")
    output.mkdir(parents=True, exist_ok=True)
    renderer = TypstSurveyRenderer()
    result = []
    for name in ("normal", "long-labels", "empty"):
        selected = snapshot.model_copy(deep=True)
        title = "Rückmeldung: Golf & Krapfentaxi - ÄÖÜ äöü ß € Ω"
        if name == "long-labels":
            title = (
                "Gemeinsame Auswertung der Krapfentaxi-Charity-Aktion und des Lions Open Golf Turniers "
                * 2
            ).strip()
            for question in selected.questions:
                question.title = (
                    "Organisation, Erreichbarkeit und Verpflegung bei der gemeinsamen Veranstaltung "
                    * 3
                ).strip()
                for bucket in question.counts:
                    bucket.label = (
                        "Ausführliche Rückmeldung mit Umlauten äöü und einer langen Bezeichnung "
                        * 5
                    ).strip()
                for row in question.matrixRows:
                    row.label = (
                        "Organisation und Verpflegung für Mitglieder, Gäste und freiwillige Helfer "
                        * 3
                    )
                    for bucket in row.counts:
                        bucket.label = (
                            "Eine ausführliche Beschreibung der gewählten Antwortmöglichkeit "
                            * 4
                        )
        if name == "empty":
            selected.participationCount = 0
            selected.lastPageCounts = []
            selected.statusCounts.in_progress = 0
            selected.statusCounts.partial = 0
            selected.statusCounts.completed = 0
            for question in selected.questions:
                for key in ("relevant", "answered", "unanswered", "hidden", "invalid"):
                    setattr(question, key, 0)
                for key in ("sum", "mean", "minimum", "maximum", "nps"):
                    setattr(question, key, None)
                for bucket in question.counts:
                    bucket.count, bucket.percentage = 0, None
                for row in question.matrixRows:
                    row.answered = row.unanswered = row.invalid = 0
                    for bucket in row.counts:
                        bucket.count, bucket.percentage = 0, None
        source = SurveyExportSource(title, selected)
        payload = render_payload(source)
        assert "SENSITIVE_" not in json.dumps(payload)
        first = renderer.render(source)
        second = renderer.render(source)
        assert first.content == second.content and first.sha256 == second.sha256
        private = IndividualResponse(
            participationId="b936908d-ad8e-4a23-a7b6-0117e1d9ed12",
            revision=1,
            status="completed",
            currentPage="main",
            createdAt=selected.createdAt,
            completedAt=selected.createdAt,
            answers={"text": "SENSITIVE_MUST_NEVER_ENTER_PDF"},
        )
        assert (
            renderer.render(SurveyExportSource(title, selected, (private,))).content
            == first.content
        )
        reader = PdfReader(io.BytesIO(first.content))
        texts = [page.extract_text() for page in reader.pages]
        text = "\n".join(texts)
        assert (
            selected.id in text
            and selected.surveyId in text
            and selected.filter.versionId in text
        )
        if name == "empty":
            assert "Nicht verfügbar" in text and "Net Promoter Score" not in text
        else:
            assert "33,33" in text and "Mittelwert" in text and "15" in text
        assert "SENSITIVE_" not in text
        assert len(reader.pages) >= 2
        assert all(not page.get("/Annots") for page in reader.pages)
        for index, page in enumerate(texts, 1):
            assert f"Seite {index}" in page
        (output / f"{name}.pdf").write_bytes(first.content)
        result.append(
            {
                "name": name,
                "pages": len(reader.pages),
                "sizeBytes": len(first.content),
                "sha256": first.sha256,
                "deterministic": True,
                "aggregateOnly": True,
            }
        )
    literal = '#panic("should not execute") <script> Unicode äöü'
    artifact = renderer.render(SurveyExportSource(literal, snapshot))
    text = "\n".join(
        page.extract_text() for page in PdfReader(io.BytesIO(artifact.content)).pages
    )
    assert "panic" in text and "should not execute" in text and "<script>" in text
    for failing in (
        TypstSurveyRenderer(executable="/bin/false"),
        TypstSurveyRenderer(template=Path("/missing-survey-template.typ")),
    ):
        try:
            failing.render(SurveyExportSource(literal, snapshot))
            raise AssertionError("Expected a stable renderer failure")
        except SurveyExportRenderError as error:
            assert str(error) in {"typst_version_mismatch", "typst_report_failed"}
            assert "should not execute" not in str(error)
    try:
        renderer.render(SurveyExportSource("日本語", snapshot))
        raise AssertionError("Missing glyphs must not produce a deliverable report")
    except SurveyExportRenderError as error:
        assert str(error) == "typst_font_glyph_missing"
    (output / "render-proof.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


main()
