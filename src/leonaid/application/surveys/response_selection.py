"""Separate, explicitly authorized raw-response selection contracts."""

from typing import Any

from pydantic import Field

from leonaid.application.surveys.analysis import AggregateModel
from leonaid.application.surveys.analysis_snapshot import (
    ResolvedAnalysisFilter,
    ResponseStatus,
)


class ResponseChoice(AggregateModel):
    value: str | int | float | bool | None
    label: str


class ResponseQuestion(AggregateModel):
    id: str
    title: str
    kind: str
    choices: list[ResponseChoice]
    rows: list[ResponseChoice]


class ResponseSelection(AggregateModel):
    id: str
    surveyId: str
    createdAt: str
    versionNumber: int
    filter: ResolvedAnalysisFilter
    total: int = Field(ge=0)
    questions: list[ResponseQuestion]


class ResponseItem(AggregateModel):
    participationId: str
    revision: int
    status: ResponseStatus
    currentPage: str | None
    createdAt: str
    completedAt: str | None


class ResponseItems(AggregateModel):
    snapshotId: str
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    items: list[ResponseItem]


class IndividualResponse(ResponseItem):
    answers: dict[str, Any]


class FreeTextItem(AggregateModel):
    participationId: str
    status: ResponseStatus
    text: str


class FreeTextItems(AggregateModel):
    snapshotId: str
    questionId: str
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    items: list[FreeTextItem]
