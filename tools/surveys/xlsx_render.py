"""Create synthetic workbooks through the production renderer for consumer review."""

import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from leonaid.application.surveys.response_selection import IndividualResponse

from leonaid.adapters.survey_tabular_exports import render_tabular
from leonaid.application.surveys.analysis_snapshot import AnalysisSnapshot
from leonaid.application.surveys.export_rendering import SurveyExportSource


def main():
    snapshot = AnalysisSnapshot.model_validate_json(
        Path("tests/fixtures/surveys/export-snapshot.json").read_text()
    )
    output = Path(".artifacts/surveys-xlsx")
    output.mkdir(parents=True, exist_ok=True)
    evidence = []
    for name in ("normal", "long-labels", "empty", "responses"):
        selected = snapshot.model_copy(deep=True)
        if name == "long-labels":
            for question in selected.questions:
                question.title = (
                    "Organisation, Erreichbarkeit und Verpflegung bei der gemeinsamen Veranstaltung "
                    * 3
                )
                for bucket in question.counts:
                    bucket.label = (
                        "Ausführliche Rückmeldung mit Umlauten äöü und einer langen Bezeichnung "
                        * 3
                    )
                for row in question.matrixRows:
                    row.label = (
                        "Organisation und Verpflegung für Mitglieder, Gäste und freiwillige Helfer "
                        * 2
                    )
                    for bucket in row.counts:
                        bucket.label = (
                            "Eine ausführliche Beschreibung der gewählten Antwortmöglichkeit "
                            * 3
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
        responses = None
        if name == "responses":
            answers = json.loads(
                Path("tests/fixtures/surveys/analysis-golden.json").read_text()
            )["responses"]
            responses = tuple(
                IndividualResponse(
                    participationId=str(uuid5(NAMESPACE_URL, f"synthetic-export/{i}")),
                    revision=1,
                    status="completed" if i == 0 else "partial",
                    answers=answer,
                    currentPage="main",
                    createdAt=selected.createdAt,
                    completedAt=selected.createdAt if i == 0 else None,
                )
                for i, answer in enumerate(answers)
            )
        result = render_tabular(
            "responses_xlsx" if name == "responses" else "analysis_xlsx",
            SurveyExportSource(
                "Rückmeldung Golf und Krapfentaxi – ÄÖÜ äöü ß € Ω", selected, responses
            ),
        )
        (output / f"{name}.xlsx").write_bytes(result.content)
        evidence.append(
            {
                "name": name,
                "sha256": hashlib.sha256(result.content).hexdigest(),
                "sizeBytes": len(result.content),
                "renderer": result.render_version,
            }
        )
    (output / "workbook-proof.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence))


main()
