"""Survey-specific rendering boundary, independent of invoice document models."""

import hashlib
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from leonaid.application.surveys.analysis_snapshot import AnalysisSnapshot
from leonaid.application.surveys.response_selection import IndividualResponse

ExportProduct = Literal[
    "responses_csv", "responses_xlsx", "analysis_xlsx", "analysis_pdf"
]


def export_filename(product: ExportProduct, snapshot_id: str) -> str:
    """Stable storage identity, also usable without reading revoked answers."""
    suffix = {
        "responses_csv": "responses.csv",
        "responses_xlsx": "responses_xlsx.xlsx",
        "analysis_xlsx": "analysis_xlsx.xlsx",
        "analysis_pdf": "analysis.pdf",
    }[product]
    return f"survey-{UUID(snapshot_id)}-{suffix}"


class SurveyExportRenderError(RuntimeError):
    """Stable failure code only; never include respondent data in diagnostics."""


@dataclass(frozen=True)
class SurveyExportSource:
    title: str
    snapshot: AnalysisSnapshot
    responses: tuple[IndividualResponse, ...] | None = None


@dataclass(frozen=True)
class SurveyExportArtifact:
    filename: str
    media_type: str
    render_version: str
    content: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()
