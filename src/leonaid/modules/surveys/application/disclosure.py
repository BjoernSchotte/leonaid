"""What an aggregate may show: the minimum group size (k = 5) for survey results.

The stored snapshot (``analysis_snapshot.AnalysisSnapshot``) keeps every
computed number. Everything that leaves the API as an aggregate passes
``disclose`` first, which applies Björn's rule (2026-11-04):

- a selection with fewer than ``K`` participations shows no results;
- a question (or matrix row) with fewer than ``K`` valid answers shows no
  distribution and no statistics;
- a count of 1 to ``K - 1`` people is withheld ("< 5"), with its share;
- where the shown counts of a distribution add up to a known total, a single
  withheld count could be worked out by subtraction, so the next smallest
  non-zero count of that distribution is withheld as well.

Counts of 0 stay visible: they reveal no one. Question denominators
(shown, answered, unanswered, hidden, invalid) say how many people saw or
answered a question, not what they answered, and stay visible.

The public models below carry the OpenAPI names of the earlier snapshot
schema; the stored models in ``analysis`` and ``analysis_snapshot`` never
appear in a response.
"""

from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from leonaid.modules.surveys.application.analysis import AggregateModel
from leonaid.modules.surveys.application.analysis_snapshot import (
    AnalysisSnapshot as StoredSnapshot,
    ResolvedAnalysisFilter,
)

K = 5
"""Minimum group size for any shown aggregate."""

MIN_RANGE = timedelta(days=1)
"""Narrowest date range an aggregate-only account may select."""


def range_too_narrow(
    created_from: str | None, created_before: str | None, now: datetime
) -> bool:
    """A start-bounded range shorter than MIN_RANGE (the end defaults to now).

    Narrow ranges would let an aggregate-only account isolate one person.
    This bounds the width only: two wide ranges that differ by a short span
    still differ by the people in it (a known limit, see the task report).
    """
    if created_from is None:
        return False
    end = datetime.fromisoformat(created_before) if created_before else now
    return end - datetime.fromisoformat(created_from) < MIN_RANGE

# Kinds whose counts add up to the number of valid answers (one value each).
SINGLE_VALUE_KINDS = {"radiogroup", "dropdown", "rating"}


class AggregateCount(AggregateModel):
    value: str | int | FiniteFloat
    label: str
    count: int | None = Field(ge=0)
    percentage: FiniteFloat | None = Field(ge=0, le=100)
    suppressed: bool = False

    @model_validator(mode="after")
    def withheld_together(self) -> Self:
        if self.suppressed != (self.count is None):
            raise ValueError("a withheld count has no value")
        if self.suppressed and self.percentage is not None:
            raise ValueError("a withheld count has no share")
        return self


class MatrixRowAggregate(AggregateModel):
    rowId: str
    label: str
    answered: int = Field(ge=0)
    unanswered: int = Field(ge=0)
    invalid: int = Field(ge=0)
    counts: list[AggregateCount]
    suppressed: bool = False


class NpsSegments(AggregateModel):
    """People per NPS group (0–6, 7–8, 9–10); None = withheld (1 to K − 1)."""

    detractors: int | None = Field(ge=0)
    passives: int | None = Field(ge=0)
    promoters: int | None = Field(ge=0)


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
    suppressed: bool = False
    """Fewer than K valid answers: no distribution, no statistics."""
    npsSegments: NpsSegments | None = None
    """Only for a 0–10 NPS rating that is shown."""


class ParticipationCounts(AggregateModel):
    in_progress: int | None = Field(ge=0)
    partial: int | None = Field(ge=0)
    completed: int | None = Field(ge=0)


class LastPageCount(AggregateModel):
    pageId: str | None
    title: str
    count: int | None = Field(ge=0)


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
    minimumGroupSize: int = Field(default=K, ge=1)
    suppressed: bool = False
    """Fewer than K participations: no results at all."""


def _withheld(count: int) -> bool:
    return 0 < count < K


def protect(counts: list[int], total: int | None) -> list[bool]:
    """Which counts to withhold. ``total`` is the known sum, if any."""
    hidden = [_withheld(count) for count in counts]
    if total is not None and sum(hidden) == 1:
        # One withheld count = total - shown counts: withhold one more.
        candidates = [
            (count, index)
            for index, count in enumerate(counts)
            if count > 0 and not hidden[index]
        ]
        if candidates:
            hidden[min(candidates)[1]] = True
    return hidden


def _counts(buckets: list[dict], total: int | None) -> list[AggregateCount]:
    hidden = protect([bucket["count"] for bucket in buckets], total)
    return [
        AggregateCount(
            value=bucket["value"],
            label=bucket["label"],
            count=None if hide else bucket["count"],
            percentage=None if hide else bucket["percentage"],
            suppressed=hide,
        )
        for bucket, hide in zip(buckets, hidden, strict=True)
    ]


def _question(question: dict, everything_hidden: bool) -> QuestionAggregate:
    base = {
        key: question[key]
        for key in (
            "questionId",
            "title",
            "kind",
            "relevant",
            "answered",
            "unanswered",
            "hidden",
            "invalid",
        )
    }
    if everything_hidden or question["answered"] < K:
        return QuestionAggregate(
            **base,
            counts=[],
            sum=None,
            mean=None,
            minimum=None,
            maximum=None,
            nps=None,
            matrixRows=[],
            suppressed=True,
        )
    single = question["kind"] in SINGLE_VALUE_KINDS
    rows = []
    for row in question["matrixRows"]:
        row_base = {
            key: row[key]
            for key in ("rowId", "label", "answered", "unanswered", "invalid")
        }
        if row["answered"] < K:
            rows.append(MatrixRowAggregate(**row_base, counts=[], suppressed=True))
        else:
            rows.append(
                MatrixRowAggregate(
                    **row_base, counts=_counts(row["counts"], row["answered"])
                )
            )
    return QuestionAggregate(
        **base,
        npsSegments=_nps_segments(question),
        counts=_counts(question["counts"], question["answered"] if single else None),
        sum=question["sum"],
        mean=question["mean"],
        minimum=question["minimum"],
        maximum=question["maximum"],
        nps=question["nps"],
        matrixRows=rows,
    )


def _nps_segments(question: dict) -> NpsSegments | None:
    if question["kind"] != "rating" or question["nps"] is None:
        return None
    groups = [0, 0, 0]
    for bucket in question["counts"]:
        score = float(bucket["value"])
        groups[0 if score <= 6 else 1 if score <= 8 else 2] += bucket["count"]
    hidden = protect(groups, question["answered"])
    detractors, passives, promoters = (
        None if hide else count for count, hide in zip(groups, hidden, strict=True)
    )
    return NpsSegments(
        detractors=detractors, passives=passives, promoters=promoters
    )


def disclose(snapshot: StoredSnapshot | dict) -> AnalysisSnapshot:
    """The shown form of a stored snapshot (pure; the stored one is unchanged)."""
    stored = (
        snapshot
        if isinstance(snapshot, StoredSnapshot)
        else StoredSnapshot.model_validate(snapshot)
    ).model_dump()
    everything_hidden = stored["participationCount"] < K
    selected = stored["filter"]["statuses"]
    status_keys = ["in_progress", "partial", "completed"]
    # The selected statuses add up to the participation count.
    status_hidden = dict(
        zip(
            selected,
            protect(
                [stored["statusCounts"][key] for key in selected],
                stored["participationCount"],
            ),
            strict=True,
        )
    )
    other = [key for key in status_keys if key not in selected]
    status_hidden.update(
        zip(
            other,
            protect([stored["statusCounts"][key] for key in other], None),
            strict=True,
        )
    )
    pages = stored["lastPageCounts"]
    page_hidden = protect(
        [page["count"] for page in pages], stored["participationCount"]
    )
    return AnalysisSnapshot(
        **{
            key: stored[key]
            for key in (
                "id",
                "surveyId",
                "createdAt",
                "filter",
                "versionNumber",
                "rendererVersion",
                "capabilityProfile",
                "participationCount",
            )
        },
        statusCounts=ParticipationCounts(
            **{
                key: None if status_hidden[key] else stored["statusCounts"][key]
                for key in status_keys
            }
        ),
        lastPageCounts=[
            LastPageCount(
                pageId=page["pageId"],
                title=page["title"],
                count=None if hide else page["count"],
            )
            for page, hide in zip(pages, page_hidden, strict=True)
        ],
        questions=[_question(q, everything_hidden) for q in stored["questions"]],
        minimumGroupSize=K,
        suppressed=everything_hidden,
    )
