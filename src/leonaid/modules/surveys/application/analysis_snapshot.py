"""Version-explicit analysis filters and immutable public snapshot contracts."""

from datetime import datetime, timezone
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from leonaid.modules.surveys.application.analysis import (
    AggregateModel,
    QuestionAggregate,
)

ResponseStatus = Literal["in_progress", "partial", "completed"]


def default_statuses() -> list[ResponseStatus]:
    return ["partial", "completed"]


class AnalysisFilter(AggregateModel):
    versionId: str = Field(min_length=36, max_length=36)
    statuses: list[ResponseStatus] = Field(
        default_factory=default_statuses, min_length=1, max_length=3
    )
    isTest: bool = False
    createdFrom: str | None = Field(default=None, max_length=40)
    createdBefore: str | None = Field(default=None, max_length=40)

    @field_validator("versionId")
    @classmethod
    def version_uuid(cls, value: str) -> str:
        return str(UUID(value))

    @field_validator("statuses")
    @classmethod
    def canonical_statuses(cls, values: list[ResponseStatus]) -> list[ResponseStatus]:
        if len(set(values)) != len(values):
            raise ValueError("Duplicate response status")
        order: list[ResponseStatus] = ["in_progress", "partial", "completed"]
        return [status for status in order if status in values]

    @field_validator("createdFrom", "createdBefore")
    @classmethod
    def aware_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        if "T" not in value or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Analysis dates need an explicit time zone")
        return parsed.astimezone(timezone.utc).isoformat()

    @model_validator(mode="after")
    def ordered_dates(self) -> Self:
        if (
            self.createdFrom
            and self.createdBefore
            and datetime.fromisoformat(self.createdFrom)
            >= datetime.fromisoformat(self.createdBefore)
        ):
            raise ValueError("The exclusive end must follow the inclusive start")
        return self


class CreateAnalysisSnapshot(AggregateModel):
    operationId: str = Field(min_length=1, max_length=128)
    filter: AnalysisFilter


class ResolvedAnalysisFilter(AnalysisFilter):
    statuses: list[ResponseStatus] = Field(min_length=1, max_length=3)
    isTest: bool
    createdFrom: str | None = Field(max_length=40)
    createdBefore: str | None = Field(max_length=40)


class ParticipationCounts(AggregateModel):
    in_progress: int = Field(ge=0)
    partial: int = Field(ge=0)
    completed: int = Field(ge=0)


class LastPageCount(AggregateModel):
    pageId: str | None
    title: str
    count: int = Field(ge=0)


ConditionLeaf = Annotated[list[str], Field(min_length=3, max_length=3)]
"""[name, operator, literal] of one visibleIf comparison."""


class SnapshotDependencies(AggregateModel):
    """visibleIf references from the frozen version (Task 5.6b, R4/R5).

    ``questions``: question id -> names its own or its page's condition
    reads. ``pages``: page name -> names its condition reads.
    """

    questions: dict[str, list[str]]
    pages: dict[str, list[str]]
    # The leaves ([name, operator, literal]) of each condition; a question's
    # list holds its page's leaves too. None: recorded before the leaves
    # (review 5.6b round 2), which disclose treats conservatively.
    questionLeaves: dict[str, list[ConditionLeaf]] | None = None
    pageLeaves: dict[str, list[ConditionLeaf]] | None = None


class AnalysisSnapshot(AggregateModel):
    id: str
    surveyId: str
    createdAt: str
    filter: ResolvedAnalysisFilter
    versionNumber: int = Field(ge=1)
    rendererVersion: str
    capabilityProfile: str
    participationCount: int = Field(ge=0)
    statusCounts: ParticipationCounts
    lastPageCounts: list[LastPageCount]
    questions: list[QuestionAggregate]
    # Absent on snapshots from before Task 5.6b: disclose() is conservative.
    dependencies: SnapshotDependencies | None = None
    # "settled": created for an account without raw access (whole days,
    # completed before the end). Only those may be read by such accounts.
    disclosurePolicy: Literal["reader", "settled"] = "reader"

    @model_validator(mode="after")
    def consistent_selection(self) -> Self:
        counts = self.statusCounts.model_dump()
        if (
            sum(counts[status] for status in self.filter.statuses)
            != self.participationCount
        ):
            raise ValueError("Selected status counts disagree with participation count")
        if sum(page.count for page in self.lastPageCounts) != self.participationCount:
            raise ValueError("Last-page counts disagree with participation count")
        if any(
            q.relevant + q.hidden != self.participationCount for q in self.questions
        ):
            raise ValueError("Question denominators disagree with participation count")
        return self


class AnalysisVersion(AggregateModel):
    id: str
    number: int
    publishedAt: str


class AnalysisVersions(AggregateModel):
    items: list[AnalysisVersion]
