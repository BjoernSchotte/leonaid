"""Measure production renderers on synthetic fixtures, excluding database/storage I/O."""

import json
import statistics
from pathlib import Path
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5
from typing import Any

from leonaid.modules.surveys.adapters.survey_tabular_exports import render_tabular
from leonaid.modules.surveys.adapters.typst.survey_renderer import TypstSurveyRenderer
from leonaid.modules.surveys.application.analysis_snapshot import AnalysisSnapshot
from leonaid.modules.surveys.application.export_rendering import (
    SurveyExportSource,
    ExportProduct,
)
from leonaid.modules.surveys.application.response_selection import IndividualResponse


def main() -> None:
    snapshot = AnalysisSnapshot.model_validate_json(
        Path("tests/fixtures/surveys/export-snapshot.json").read_text()
    )
    answers = json.loads(
        Path("tests/fixtures/surveys/analysis-golden.json").read_text()
    )["responses"]
    # Repeat the five-response fixture 1000 times, scaling its aggregate counts.
    assert snapshot.participationCount == len(answers) == 5
    count_fields = {
        "participationCount",
        "in_progress",
        "partial",
        "completed",
        "count",
        "relevant",
        "answered",
        "unanswered",
        "hidden",
        "invalid",
        "sum",
    }

    def scaled(value: Any) -> Any:
        if isinstance(value, list):
            return [scaled(item) for item in value]
        if isinstance(value, dict):
            return {
                key: item * 1000
                if key in count_fields and isinstance(item, (int, float))
                else scaled(item)
                for key, item in value.items()
            }
        return value

    snapshot = AnalysisSnapshot.model_validate(scaled(snapshot.model_dump()))
    responses = tuple(
        IndividualResponse(
            participationId=str(uuid5(NAMESPACE_URL, f"benchmark/{i}")),
            revision=1,
            status="completed" if i % len(answers) == 0 else "partial",
            currentPage="main",
            createdAt=snapshot.createdAt,
            completedAt=snapshot.createdAt,
            answers=answers[i % len(answers)],
        )
        for i in range(5000)
    )
    results = []
    products: tuple[ExportProduct, ...] = (
        "analysis_pdf",
        "analysis_xlsx",
        "responses_csv",
        "responses_xlsx",
    )
    for product in products:
        source = SurveyExportSource(
            "Synthetic runtime measurement",
            snapshot,
            responses if product.startswith("responses_") else None,
        )
        durations = []
        sizes = []
        for _ in range(3):
            started = perf_counter()
            artifact = (
                TypstSurveyRenderer().render(source)
                if product == "analysis_pdf"
                else render_tabular(product, source)
            )
            durations.append(round(perf_counter() - started, 4))
            sizes.append(len(artifact.content))
        assert min(sizes) > 0
        results.append(
            {
                "product": product,
                "rows": len(responses) if source.responses else None,
                "seconds": durations,
                "medianSeconds": statistics.median(durations),
                "sizeBytes": sizes,
            }
        )
    print(
        json.dumps(
            {
                "scope": "renderer only; no database or storage I/O",
                "measurements": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
