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


RAW_PRODUCTS: frozenset[str] = frozenset({"responses_csv", "responses_xlsx"})
"""Raw exports (export_raw): the stored snapshot. Every other product, now
and in future, renders from the disclosed snapshot (fails closed, M3)."""


WITHHELD = "–"
"""How reports show a withheld count: one neutral marker, since some are
1 to K - 1 people and others are withheld because they would reveal those
(review 5.6b, option A). The UI uses the same marker."""


def shown_count(value: int | None) -> int | str:
    """A count as a report shows it: a withheld one (None) reads WITHHELD."""
    return WITHHELD if value is None else value


def withheld_note(k: int) -> str:
    return f"Weniger als {k} gültige Antworten oder daraus ableitbar: nicht ausgewertet, damit niemand erkennbar wird."


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
