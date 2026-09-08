"""Version-explicit analysis filters and immutable public snapshot contracts."""

from datetime import datetime, timezone
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from leonaid.application.surveys.analysis import AggregateModel, QuestionAggregate

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
