"""Strict, transport-independent aggregate contracts; no raw response fields."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class AggregateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AggregateCount(AggregateModel):
    value: str | int | FiniteFloat
    label: str
    count: int = Field(ge=0)
    percentage: FiniteFloat | None = Field(ge=0, le=100)


class MatrixRowAggregate(AggregateModel):
    rowId: str
    label: str
    answered: int = Field(ge=0)
    unanswered: int = Field(ge=0)
    invalid: int = Field(ge=0)
    counts: list[AggregateCount]


class QuestionAggregate(AggregateModel):
    questionId: str
    title: str
    kind: Literal[
        "text",
        "comment",
        "date",
        "number",
        "radiogroup",
        "dropdown",
        "checkbox",
        "rating",
        "matrix",
    ]
    relevant: int = Field(ge=0)
    answered: int = Field(ge=0)
    unanswered: int = Field(ge=0)
    hidden: int = Field(ge=0)
    invalid: int = Field(ge=0)
    counts: list[AggregateCount]
    sum: FiniteFloat | None
    mean: FiniteFloat | None
    minimum: FiniteFloat | None
    maximum: FiniteFloat | None
    nps: FiniteFloat | None = Field(ge=-100, le=100)
    matrixRows: list[MatrixRowAggregate]

    @model_validator(mode="after")
    def consistent_denominators(self) -> Self:
        if self.answered + self.unanswered + self.invalid != self.relevant:
            raise ValueError("inconsistent question denominators")
        if any(item.count > self.answered for item in self.counts):
            raise ValueError("count exceeds answered denominator")
        for row in self.matrixRows:
            if row.answered + row.unanswered + row.invalid != self.relevant:
                raise ValueError("inconsistent matrix denominators")
            if sum(item.count for item in row.counts) != row.answered:
                raise ValueError("inconsistent matrix distribution")
        if self.kind in {"text", "comment", "date", "number"} and self.counts:
            raise ValueError("respondent values are not aggregate buckets")
        return self


class AggregateBatch(AggregateModel):
    profile: Literal["initial-v1"]
    renderer: Literal["3.0.3"]
    questions: list[QuestionAggregate]
