"""Create synthetic workbooks through the production renderer for consumer review."""

import hashlib
import json
from pathlib import Path

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
    for name in ("normal", "long-labels"):
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
        result = render_tabular(
            "analysis_xlsx",
            SurveyExportSource(
                "Rückmeldung Golf und Krapfentaxi – ÄÖÜ äöü ß € Ω", selected
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
