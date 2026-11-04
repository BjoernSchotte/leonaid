"""Survey-specific rendering boundary, independent of invoice document models."""

import hashlib
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from leonaid.modules.surveys.application.analysis_snapshot import AnalysisSnapshot
from leonaid.modules.surveys.application.disclosure import (
    K,
    AnalysisSnapshot as DisclosedSnapshot,
)
from leonaid.modules.surveys.application.response_selection import IndividualResponse

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


AGGREGATE_PRODUCTS: frozenset[str] = frozenset({"analysis_xlsx", "analysis_pdf"})
"""Report exports: rendered from the disclosed snapshot (k = 5), like the UI."""


def shown_count(value: int | None) -> int | str:
    """A count as a report shows it: a withheld one (None) reads "< 5"."""
    return f"< {K}" if value is None else value


@dataclass(frozen=True)
class SurveyExportSource:
    title: str
    # Raw exports get the stored snapshot; report exports the disclosed one.
    snapshot: AnalysisSnapshot | DisclosedSnapshot
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
