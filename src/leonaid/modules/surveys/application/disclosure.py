"""What an aggregate may show: the minimum group size (k = 5) for survey results.

The stored snapshot (``analysis_snapshot.AnalysisSnapshot``) keeps every
computed number. Everything that leaves the API as an aggregate passes
``disclose`` first (Björn, 2026-11-04; review rulings for Task 5.6b):

R0  A selection with 1 to K - 1 participations shows nothing, not even
    its exact size.
R1  A count of 1 to K - 1 people is withheld. Where the counts of a
    distribution add up to a known total, every cell below 2K (zeros
    included) is withheld with it, and more if those stand for fewer than
    K people, so neither subtraction nor the choice of cells pins them down.
R2  A question (or matrix row) with 1 to K - 1 valid answers shows no
    distribution and no statistics (with 0 answers there is nothing to
    hide: every count is 0).
R3  If any count of a question is withheld, so is every figure derived
    from its counts: mean, minimum, maximum, NPS score and NPS segments.
R4  A conditional question (hidden for some people) has denominators that
    are counts of its condition's answers. The snapshot records which
    answers each condition reads (visibleIf). If one of them is withheld,
    the conditional question is withheld as a whole, denominators
    included. If a condition reads an answer without a released
    distribution (number, date, text), the shown/hidden pair is protected
    like a distribution (R1), and the mean, minimum and maximum of that
    number are withheld with it (R4b).
R5  Last-page counts say where people stopped. Under page conditions they
    follow the answers those read, so they are all withheld (zeros
    included) when one of those is; under a condition on an unreleased
    answer they are protected like a distribution (with R4b).
Snapshots from before these records get the conservative variant: any
question hidden for someone counts as conditional on anything.

Outside R1, counts of 0 stay visible. tests/unit/test_survey_
disclosure_solver.py checks by brute force that no withheld number is
uniquely determined by the rest of a released result.

The public models below carry the OpenAPI names of the earlier snapshot
schema; the stored models in ``analysis`` and ``analysis_snapshot`` never
appear in a response.
"""

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from leonaid.domain.calendar import local_day, local_day_bounds
from leonaid.modules.surveys.application.analysis import AggregateModel
from leonaid.modules.surveys.application.analysis_snapshot import (
    AnalysisSnapshot as StoredSnapshot,
    ResolvedAnalysisFilter,
)

K = 5
"""Minimum group size for any shown aggregate."""


def whole_days(
    created_from: str | None, created_before: str | None, now: datetime
) -> tuple[str | None, str]:
    """The range an account without raw access may select (Björn, 2026-11-04).

    Both ends snap to whole days in the installation's zone (Europe/Berlin):
    the start to 00:00 of its day, the end to 24:00 of its day. The end is at
    most today 00:00, so a selection never reaches into the current day.
    Two selections can then differ only by whole past days, never by the
    people who answered in the last minutes. An empty result (start today or
    later) is the caller's to refuse.
    """
    start = (
        None
        if created_from is None
        else local_day_bounds(local_day(datetime.fromisoformat(created_from)))[0]
    )
    today = local_day_bounds(local_day(now))[0]
    end = today
    if created_before is not None:
        before = datetime.fromisoformat(created_before)
        day_start, day_end = local_day_bounds(local_day(before))
        end = min(before if before == day_start else day_end, today)
    return (None if start is None else start.isoformat(), end.isoformat())


# Kinds whose counts add up to the number of valid answers (one value each).
SINGLE_VALUE_KINDS = {"radiogroup", "dropdown", "rating"}
# Kinds a condition (visibleIf) can usefully test; text conditions only see
# "answered", which is shown anyway.
CONDITION_KINDS = {"radiogroup", "dropdown", "checkbox", "rating", "matrix", "number"}
# Kinds whose answers are released as a distribution of counts.
DISTRIBUTION_KINDS = {"radiogroup", "dropdown", "checkbox", "rating", "matrix"}


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
    answered: int | None = Field(ge=0)
    unanswered: int | None = Field(ge=0)
    invalid: int | None = Field(ge=0)
    counts: list[AggregateCount]
    suppressed: bool = False


class NpsSegments(AggregateModel):
    """People per NPS group (0–6, 7–8, 9–10); only when no score is withheld."""

    detractors: int = Field(ge=0)
    passives: int = Field(ge=0)
    promoters: int = Field(ge=0)


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
    # None: withheld (R4, a conditional question whose condition is withheld).
    relevant: int | None = Field(ge=0)
    answered: int | None = Field(ge=0)
    unanswered: int | None = Field(ge=0)
    hidden: int | None = Field(ge=0)
    invalid: int | None = Field(ge=0)
    counts: list[AggregateCount]
    mean: FiniteFloat | None
    minimum: FiniteFloat | None
    maximum: FiniteFloat | None
    nps: FiniteFloat | None = Field(ge=-100, le=100)
    matrixRows: list[MatrixRowAggregate]
    suppressed: bool = False
    """No distribution and no statistics (R2–R4)."""
    npsSegments: NpsSegments | None = None
    """Only for a 0–10 NPS rating with every score shown (R3)."""


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
    # None: 1 to K - 1 participations (R0).
    participationCount: int | None = Field(ge=0)
    statusCounts: ParticipationCounts
    lastPageCounts: list[LastPageCount]
    questions: list[QuestionAggregate]
    minimumGroupSize: int = Field(default=K, ge=1)
    suppressed: bool = False
    """Fewer than K participations: no results at all."""


def _withheld(count: int) -> bool:
    return 0 < count < K


def protect(counts: list[int], total: int | None) -> list[bool]:
    """Which counts to withhold (R1). ``total`` is their known sum, if any.

    Primary: every count of 1 to K - 1. With a known total the withheld
    cells can be worked out together (total minus the shown ones), and an
    observer who knows this rule also learns from *which* cells are
    withheld. So once anything is withheld, the choice depends on values
    only, never on the other cells: every cell below 2K is withheld, zeros
    included. If those still stand for fewer than K people, the smallest
    remaining cells follow until they do.
    """
    hidden = [_withheld(count) for count in counts]
    if total is None or not any(hidden):
        return hidden
    hidden = [count < 2 * K for count in counts]
    while sum(c for c, h in zip(counts, hidden, strict=True) if h) < K:
        candidates = [
            (count, index) for index, count in enumerate(counts) if not hidden[index]
        ]
        if not candidates:
            break
        hidden[min(candidates)[1]] = True
    return hidden


def _counts(buckets: list[dict[str, Any]], total: int | None) -> list[AggregateCount]:
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


_DENOMINATORS = ("relevant", "answered", "unanswered", "hidden", "invalid")


def _withheld_question(
    question: dict[str, Any], *, denominators: bool
) -> QuestionAggregate:
    """No distribution, no statistics; denominators too if asked (R4)."""
    return QuestionAggregate(
        questionId=question["questionId"],
        title=question["title"],
        kind=question["kind"],
        **{key: None if denominators else question[key] for key in _DENOMINATORS},
        counts=[],
        mean=None,
        minimum=None,
        maximum=None,
        nps=None,
        matrixRows=[],
        suppressed=True,
    )


def _question(question: dict[str, Any]) -> QuestionAggregate:
    """R2 and R3 for one question (conditions are handled in ``disclose``)."""
    if 0 < question["answered"] < K:
        withheld = _withheld_question(question, denominators=False)
        if len(question["counts"]) == 1 and not question["matrixRows"]:
            # One option: its count *is* "answered" (e.g. a lone "I agree").
            return withheld.model_copy(update={"answered": None, "unanswered": None})
        return withheld
    single = question["kind"] in SINGLE_VALUE_KINDS
    rows = []
    for row in question["matrixRows"]:
        row_base = {
            key: row[key]
            for key in ("rowId", "label", "answered", "unanswered", "invalid")
        }
        if 0 < row["answered"] < K:
            rows.append(MatrixRowAggregate(**row_base, counts=[], suppressed=True))
        else:
            rows.append(
                MatrixRowAggregate(
                    **row_base, counts=_counts(row["counts"], row["answered"])
                )
            )
    counts = _counts(question["counts"], question["answered"] if single else None)
    # R3: a figure computed from the counts would give withheld ones back.
    linked = any(bucket.suppressed for bucket in counts)
    return QuestionAggregate(
        **{
            key: question[key]
            for key in ("questionId", "title", "kind", *_DENOMINATORS)
        },
        counts=counts,
        mean=None if linked else question["mean"],
        minimum=None if linked else question["minimum"],
        maximum=None if linked else question["maximum"],
        nps=None if linked else question["nps"],
        npsSegments=None if linked else _nps_segments(question),
        matrixRows=rows,
    )


def _nps_segments(question: dict[str, Any]) -> NpsSegments | None:
    if question["kind"] != "rating" or question["nps"] is None:
        return None
    groups = [0, 0, 0]
    for bucket in question["counts"]:
        score = float(bucket["value"])
        groups[0 if score <= 6 else 1 if score <= 8 else 2] += bucket["count"]
    return NpsSegments(detractors=groups[0], passives=groups[1], promoters=groups[2])


def _has_withheld(question: QuestionAggregate) -> bool:
    return (
        question.suppressed
        or any(bucket.suppressed for bucket in question.counts)
        or any(
            row.suppressed or any(bucket.suppressed for bucket in row.counts)
            for row in question.matrixRows
        )
    )


def _with_dependencies(
    stored: dict[str, Any], total: int
) -> tuple[list[QuestionAggregate], list[bool]]:
    """R4/R5 from the recorded visibleIf references (definition order).

    A conditional question is withheld as a whole if a question its
    condition reads is withheld, or if its condition reads an answer
    without a released distribution and its shown/hidden pair would be.
    Page counts are withheld if a question a page condition reads is.
    """
    deps = stored["dependencies"]
    known = {q["questionId"] for q in stored["questions"]}
    shown: dict[str, QuestionAggregate] = {}
    withheld: set[str] = set()

    def blocked(names: list[str]) -> bool:
        # An unknown or later reference counts as withheld (conservative).
        return any(n in withheld or n not in known or n not in shown for n in names)

    def strip(names: list[str]) -> None:
        """R4b: mean, minimum and maximum of a number a protected condition
        reads would narrow the protected count (e.g. how many are >= 10)."""
        for n in names:
            if n in shown:
                shown[n] = shown[n].model_copy(
                    update={"mean": None, "minimum": None, "maximum": None}
                )
                withheld.add(n)

    kinds = {q["questionId"]: q["kind"] for q in stored["questions"]}
    for q in stored["questions"]:
        qid = q["questionId"]
        refs = deps["questions"].get(qid, [])
        # The shown/hidden pair follows from the referenced answers. If all
        # of those are released (choice distributions), it adds nothing;
        # if a reference has no released distribution (number, date, text),
        # the pair is a new count and is protected like a distribution.
        unreleased = [n for n in refs if kinds.get(n) not in DISTRIBUTION_KINDS]
        pair_protected = bool(unreleased) and any(
            protect([q["relevant"], q["hidden"]], total)
        )
        if refs and (blocked(refs) or pair_protected):
            shown[qid] = _withheld_question(q, denominators=True)
            withheld.add(qid)
            if pair_protected:
                strip(unreleased)
            continue
        disclosed = _question(q)
        shown[qid] = disclosed
        if _has_withheld(disclosed):
            withheld.add(qid)
    pages = stored["lastPageCounts"]
    page_refs = sorted({n for refs in deps["pages"].values() for n in refs})
    # Last pages say where people stopped (no answer content), like the
    # denominators; under page conditions they also follow the referenced
    # answers, so they are withheld exactly when one of those is.
    unreleased_pages = [n for n in page_refs if kinds.get(n) not in DISTRIBUTION_KINDS]
    if page_refs and blocked(page_refs):
        pages_hidden = [True for _ in pages]
    elif unreleased_pages and len(pages) > 1:
        # Page counts are then new counts of the unreleased answers.
        pages_hidden = protect([page["count"] for page in pages], total)
        if any(pages_hidden):
            strip(unreleased_pages)
    else:
        pages_hidden = [False for _ in pages]
    return [shown[q["questionId"]] for q in stored["questions"]], pages_hidden


def _conservative(
    stored: dict[str, Any], total: int
) -> tuple[list[QuestionAggregate], list[bool]]:
    """R4/R5 without recorded references (snapshots before Task 5.6b):
    any question hidden for someone counts as conditional on anything."""
    plain = [q for q in stored["questions"] if q["hidden"] == 0]
    conditional = [q for q in stored["questions"] if q["hidden"] > 0]
    shown = {q["questionId"]: _question(q) for q in plain}
    withheld = any(
        _has_withheld(shown[q["questionId"]])
        for q in plain
        if q["kind"] in CONDITION_KINDS
    )
    if not withheld:
        for q in conditional:
            provisional = _question(q)
            if any(protect([q["relevant"], q["hidden"]], total)) or (
                q["kind"] in CONDITION_KINDS and _has_withheld(provisional)
            ):
                withheld = True
                break
            shown[q["questionId"]] = provisional
    for q in conditional:
        if withheld:
            shown[q["questionId"]] = _withheld_question(q, denominators=True)
    questions = [shown[q["questionId"]] for q in stored["questions"]]
    anything = withheld or any(_has_withheld(q) for q in questions)
    pages = stored["lastPageCounts"]
    hide_pages = anything and len(pages) > 1
    pages_hidden = [hide_pages for _ in pages]
    return questions, pages_hidden


def disclose(snapshot: StoredSnapshot | dict[str, Any]) -> AnalysisSnapshot:
    """The shown form of a stored snapshot (pure; the stored one is unchanged)."""
    stored = (
        snapshot
        if isinstance(snapshot, StoredSnapshot)
        else StoredSnapshot.model_validate(snapshot)
    ).model_dump()
    total = stored["participationCount"]
    status_keys = ["in_progress", "partial", "completed"]
    everything_hidden = 0 < total < K  # R0 (0: nothing to hide)

    questions: list[QuestionAggregate] = []
    if everything_hidden:
        questions = [
            _withheld_question(q, denominators=True) for q in stored["questions"]
        ]
        pages_hidden = [True for _ in stored["lastPageCounts"]]
    elif stored.get("dependencies") is not None:
        questions, pages_hidden = _with_dependencies(stored, total)
    else:
        questions, pages_hidden = _conservative(stored, total)

    selected = stored["filter"]["statuses"]
    status_hidden = dict(
        zip(
            selected,
            protect([stored["statusCounts"][key] for key in selected], total)
            if not everything_hidden
            else [True for _ in selected],
            strict=True,
        )
    )
    other = [key for key in status_keys if key not in selected]
    status_hidden.update(
        zip(
            other,
            protect([stored["statusCounts"][key] for key in other], None)
            if not everything_hidden
            else [True for _ in other],
            strict=True,
        )
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
            )
        },
        participationCount=None if _withheld(total) else total,
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
            for page, hide in zip(stored["lastPageCounts"], pages_hidden, strict=True)
        ],
        questions=questions,
        minimumGroupSize=K,
        suppressed=everything_hidden,
    )
