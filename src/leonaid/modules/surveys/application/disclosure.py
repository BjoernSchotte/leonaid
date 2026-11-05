"""What an aggregate may show: the minimum group size (k = 5) for survey results.

The stored snapshot (``analysis_snapshot.AnalysisSnapshot``) keeps every
computed number. Everything that leaves the API as an aggregate passes
``disclose`` first (Björn, 2026-11-04; review rulings for Task 5.6b):

R0  A selection with 1 to K - 1 participations shows nothing, not even
    its exact size.
R1  A count of 1 to K - 1 people is withheld. Where the counts of a
    distribution add up to a known total, every cell below 2K (zeros
    included) is withheld with it, then cells by position until the
    withheld ones stand for K people, so neither subtraction nor the
    choice of cells pins them down. Checkbox options (and the rows of a
    one-column matrix) are ticked independently: a cell, the people who
    did not tick it, and the extra ticks beyond one per person all count,
    because everyone who answers ticks at least one (N2).
R2  A question (or matrix row) with 1 to K - 1 valid answers shows no
    distribution and no statistics (with 0 answers there is nothing to
    hide: every count is 0). With a single option (or a one-column
    matrix) "answered" is that option's count: answered and unanswered
    are protected as a two-cell distribution of the people who saw it.
R3  If any count of a question is withheld, so is every figure derived
    from its counts: mean, minimum, maximum, NPS score and NPS segments.
R4  A conditional question (hidden for some people) has denominators that
    count the people its condition selects. The snapshot records each
    condition's structure (its comparisons, its page's included), and
    the decision depends on that structure only, never on values (N1):
    - one comparison on a released choice source with an operator whose
      count follows from that source's cells, and whose options stay
      distinct under SurveyJS's comparison (case, trimming, numbers and
      numeric strings alike; N10): released, unless the source has
      anything withheld (then withheld as a whole);
    - one comparison on an answer without a released distribution
      (number, date, text): for accounts without raw access (settled
      snapshots) withheld as a whole, with ``withheldReason`` (Björn,
      review round 3, N8). For readers a new count, protected like a distribution
      (R1, and R4b: that number's mean is withheld with it). Only one
      comparison per such answer may select (identical repeats aside);
      every later question reading it is withheld, so two thresholds
      cannot be subtracted;
    - anything else (and/or, the same source twice, a matrix, an
      unknown name): a cross-tab or co-occurrence the marginals do not
      give, so the question is withheld as a whole.
R5  Accounts without raw access (settled snapshots) never get last-page
    counts: SurveyJS hides empty pages, so they follow question conditions
    too, and pages on one checkbox give co-occurrences (Björn, review
    round 3, N7 and N9). For readers: last-page counts say where people
    stopped; for completed ones they
    follow the page conditions. They are withheld entirely when a page
    condition is not a single comparison, when page conditions read more
    than one answer (a cross-tab), when their answer is withheld, or when
    they read an unreleased answer a question already uses; on an
    unreleased answer otherwise they are protected like a distribution.
R6  A number question never shows its minimum or maximum: each is one
    person's exact value (Björn, 2026-11-04, review M2). Its mean stays.
    Accepted residual: mean plus count can determine single answers near
    the range edges; accepted by Björn Schotte on 2026-11-04. (Example: 5
    answers on 0 to 4 with mean 0.2 are four 0s and one 1.) The solver
    does not claim uniqueness-safety for the mean.
Snapshots without the recorded condition structure get the conservative
variant: every question hidden for someone is withheld as a whole, and so
are the last pages.

Outside R1, counts of 0 stay visible. tests/unit/test_survey_
disclosure_solver.py checks by brute force that no withheld group of 1 to
K - 1 people, and no cross-tab or co-occurrence of that size, is uniquely
determined by the rest of a released result.

The public models below carry the OpenAPI names of the earlier snapshot
schema; the stored models in ``analysis`` and ``analysis_snapshot`` never
appear in a response.
"""

import json
import math
import re
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
    withheldReason: Literal["unreleasedCondition"] | None = None
    """Why a question is withheld as a whole, when the screen should say it:
    its condition reads a number, date or text answer (R4, settled)."""


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
    withheld. So once anything is withheld, every cell below 2K is withheld,
    zeros included. If those stand for fewer than K people, the first other
    cell by position follows (never the smallest: choosing by value would
    tell that it is at most the shown ones, review round 2).
    """
    hidden = [_withheld(count) for count in counts]
    if total is None or not any(hidden):
        return hidden
    return _complete([count < 2 * K for count in counts], counts)


def _complete(hidden: list[bool], counts: list[int]) -> list[bool]:
    """Add cells by position until the withheld ones stand for K people."""
    hidden = list(hidden)
    for index in range(len(counts)):
        if sum(c for c, h in zip(counts, hidden, strict=True) if h) >= K:
            break
        hidden[index] = True
    return hidden


def protect_choices(counts: list[int], answered: int) -> list[bool]:
    """R1 for cells people tick independently (checkbox options, the rows
    of a one-column matrix), among ``answered`` people (N2).

    Each cell splits the answering people in two: those who ticked it and
    those who did not, so both sides must be 0 or at least K. Everyone who
    answers ticks at least one cell, so the extra ticks (all ticks minus
    the answering people) say how many ticked more than one; with two
    options in use they are exactly the people who ticked both. Once one of
    these is 1 to K - 1, every cell with either side below 2K is withheld,
    then cells by position until the withheld ones stand for K people.
    """
    extra = sum(counts) - answered
    if not (
        _withheld(extra)
        or any(_withheld(count) or _withheld(answered - count) for count in counts)
    ):
        return [False for _ in counts]
    return _complete(
        [count < 2 * K or answered - count < 2 * K for count in counts], counts
    )


def _counts(
    buckets: list[dict[str, Any]], total: int | None, *, choices: bool = False
) -> list[AggregateCount]:
    values = [bucket["count"] for bucket in buckets]
    hidden = (
        protect_choices(values, total)
        if choices and total is not None
        else protect(values, total)
    )
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
    one_column = bool(question["matrixRows"]) and all(
        len(row["counts"]) == 1 for row in question["matrixRows"]
    )
    one_option = (
        len(question["counts"]) == 1 and not question["matrixRows"]
    ) or one_column
    if one_option and any(
        protect([question["answered"], question["unanswered"]], question["relevant"])
    ):
        # One option: "answered" is its count and "unanswered" the rest, a
        # two-cell distribution of the people who saw it (e.g. a lone "I
        # agree"); withheld together, also as 0 when "relevant" is small.
        return _withheld_question(question, denominators=False).model_copy(
            update={"answered": None, "unanswered": None}
        )
    if 0 < question["answered"] < K:
        return _withheld_question(question, denominators=False)
    single = question["kind"] in SINGLE_VALUE_KINDS
    rows = []
    # N3: in a one-column matrix a row's "answered" is its column's count,
    # and everyone who answers fills at least one row. The rows are then
    # cells bounded by "answered", protected like a checkbox's.
    rows_hidden = (
        protect_choices(
            [row["answered"] for row in question["matrixRows"]], question["answered"]
        )
        if one_column
        else [0 < row["answered"] < K for row in question["matrixRows"]]
    )
    for row, row_hidden in zip(question["matrixRows"], rows_hidden, strict=True):
        row_base = {
            key: row[key]
            for key in ("rowId", "label", "answered", "unanswered", "invalid")
        }
        if row_hidden or 0 < row["answered"] < K:
            if one_column:
                row_base.update(answered=None, unanswered=None)
            rows.append(MatrixRowAggregate(**row_base, counts=[], suppressed=True))
        else:
            rows.append(
                MatrixRowAggregate(
                    **row_base, counts=_counts(row["counts"], row["answered"])
                )
            )
    # N2: a checkbox's cells are bounded by what people must tick (at least
    # one each, at most maxSelectedChoices): protect_choices.
    choices = question["kind"] == "checkbox"
    counts = _counts(
        question["counts"],
        question["answered"] if single or choices else None,
        choices=choices,
    )
    # R3: a figure computed from the counts would give withheld ones back.
    linked = any(bucket.suppressed for bucket in counts)
    # R6: the extremes of a number are single people's values.
    extremes = linked or question["kind"] == "number"
    return QuestionAggregate(
        **{
            key: question[key]
            for key in ("questionId", "title", "kind", *_DENOMINATORS)
        },
        counts=counts,
        mean=None if linked else question["mean"],
        minimum=None if extremes else question["minimum"],
        maximum=None if extremes else question["maximum"],
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


# Operators a single comparison on a released source may use: the people
# it selects are a sum of that source's released cells (or the total minus
# one), so its count adds nothing new.
DERIVED_OPERATORS = {
    "radiogroup": {"=", "!=", "<>", "<", "<=", ">", ">=", "empty", "notempty"},
    "dropdown": {"=", "!=", "<>", "<", "<=", ">", ">=", "empty", "notempty"},
    "rating": {"=", "!=", "<>", "<", "<=", ">", ">=", "empty", "notempty"},
    "checkbox": {"contains", "notcontains", "empty", "notempty"},
}
# Sources without a released distribution: a comparison on them selects a
# new count (R4).
UNRELEASED_KINDS = {"number", "date", "text", "comment"}

Leaf = tuple[str, str, str]


# JavaScript's whitespace and line terminators (String.prototype.trim and
# ToNumber strip these, Python's str.strip differs).
JS_WHITESPACE = (
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
    "\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)
CANONICAL_DECIMAL = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?")
JS_NUMBER = re.compile(
    r"[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
    r"|0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+"
)


class AmbiguousOption(ValueError):
    """An option SurveyJS may compare as a number although it is not a
    plain decimal (hex, exponent, blank, padded): disclose fails closed."""


def _surveyjs_key(value: Any) -> tuple[str, Any]:
    """How SurveyJS compares a value in a condition (N10, N11, N14).

    A whitelist: only strings and finite numbers are modelled. SurveyJS
    compares case-insensitively and trimmed, and numbers with strings by
    JavaScript's loose equality (ToNumber); true equals 1 and "true".
    Only plain decimals (optional sign, digits, optional fraction) count
    as numbers here. Booleans, null, other types, non-finite numbers and
    any other string ToNumber would read as a number (0x10, 0b1, 0o7, 1e1,
    Infinity, blank or whitespace only, padded decimals) raise
    ``AmbiguousOption``; every other string is text.
    tests/fixtures/surveys/surveyjs-equality.json checks this against
    SurveyJS's own condition evaluation.
    """
    if isinstance(value, bool) or value is None:
        raise AmbiguousOption(repr(value))
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise AmbiguousOption(repr(value))
        return ("number", float(value))
    if not isinstance(value, str):
        raise AmbiguousOption(repr(value))
    text = value
    if CANONICAL_DECIMAL.fullmatch(text):
        return ("number", float(text))
    stripped = text.strip(JS_WHITESPACE)
    if (
        not stripped
        or JS_NUMBER.fullmatch(stripped)
        # SurveyJS also reads a decimal comma as a number ("1,5" = 1.5)
        # and "true"/"false" as booleans (= 1/0); null-like words likewise.
        or JS_NUMBER.fullmatch(stripped.replace(",", "."))
        or stripped.lower() in {"true", "false", "null", "undefined"}
    ):
        raise AmbiguousOption(text)
    return ("text", stripped.lower())


def _literal_key(literal: str) -> tuple[str, Any]:
    """The key of a recorded condition literal: a quoted string or a JSON
    number; anything else (true, false, null, ...) is not modelled (N14)."""
    if re.fullmatch(r"'[^'\\]*'", literal):
        return _surveyjs_key(literal[1:-1])
    try:
        value = json.loads(literal)
    except ValueError:
        raise AmbiguousOption(literal) from None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise AmbiguousOption(literal)
    return _surveyjs_key(value)


def _option_keys(source: dict[str, Any]) -> list[tuple[str, Any]] | None:
    """The options' keys, or None if any cannot be modelled or two collide."""
    try:
        keys = [_surveyjs_key(bucket["value"]) for bucket in source["counts"]]
    except AmbiguousOption:
        return None
    return keys if len(set(keys)) == len(keys) else None


def _distinct_options(source: dict[str, Any]) -> bool:
    """N10: options that SurveyJS treats as equal turn one comparison into a
    union of cells, which is not a released number. An option whose
    comparison cannot be modelled exactly counts as a collision (N11)."""
    try:
        keys = [_surveyjs_key(bucket["value"]) for bucket in source["counts"]]
    except AmbiguousOption:
        return False
    return len(set(keys)) == len(keys)


def _classify(
    leaves: list[Leaf], questions: dict[str, dict[str, Any]]
) -> tuple[Literal["none", "derived", "new", "opaque"], str | None]:
    """The structure of a condition, decided from the definition only (N1).

    ``derived``: one comparison on a released choice source with an operator
    whose count follows from that source's released cells. ``new``: one
    comparison on a source without a released distribution. ``opaque``:
    anything else (and/or, the same source twice, a matrix, an unknown
    name, an operator outside the lists); its count is a cross-tab or a
    co-occurrence that the released marginals do not give.
    """
    if not leaves:
        return "none", None
    if len(leaves) != 1:
        return "opaque", None
    name, op, literal = leaves[0]
    source = questions.get(name)
    if source is None:
        return "opaque", None
    if source["kind"] in DERIVED_OPERATORS:
        # An invalid answer could match a literal outside the options.
        if op not in DERIVED_OPERATORS[source["kind"]] or source["invalid"] != 0:
            return "opaque", None
        keys = _option_keys(source)
        if keys is None:
            return "opaque", None
        if op in {"empty", "notempty"}:
            return "derived", name
        # Whitelist (N14): the literal is a string or a finite number that
        # SurveyJS equates with exactly one option.
        try:
            key = _literal_key(literal)
        except AmbiguousOption:
            return "opaque", None
        return ("derived", name) if keys.count(key) == 1 else ("opaque", None)
    if source["kind"] in UNRELEASED_KINDS:
        return "new", name
    return "opaque", None


def _with_dependencies(
    stored: dict[str, Any], total: int
) -> tuple[list[QuestionAggregate], list[bool]]:
    """R4/R5 from the recorded conditions (definition order).

    Settled snapshots (no raw access): a "new" question is withheld as a
    whole with ``withheldReason``, and ``disclose`` drops every last page;
    the page rules below apply to readers only (review round 3).

    A question is withheld as a whole (denominators included) when its
    condition, its own and its page's together, is opaque; when it is
    derived from a source with anything withheld; or when it is new and
    either its shown/hidden pair is protected or the source already serves
    another condition (two thresholds on one answer can be subtracted).
    Last pages follow the page conditions: with completed participations
    they are a function of the answers those read, so they are withheld
    when any page condition is opaque, when page conditions read more than
    one source (a cross-tab), or when they read an unreleased answer that a
    question condition already uses.
    """
    deps = stored["dependencies"]
    settled = stored.get("disclosurePolicy") == "settled"
    by_id = {q["questionId"]: q for q in stored["questions"]}
    shown: dict[str, QuestionAggregate] = {}
    withheld: set[str] = set()
    # Unreleased source -> the one comparison allowed to select from it.
    used: dict[str, Leaf] = {}

    def blocked(name: str) -> bool:
        # Unknown or later sources count as withheld (conservative).
        return name in withheld or name not in shown

    def strip(name: str) -> None:
        """R4b: mean, minimum and maximum of a number a protected condition
        reads would narrow the protected count (e.g. how many are >= 10)."""
        if name in shown:
            shown[name] = shown[name].model_copy(
                update={"mean": None, "minimum": None, "maximum": None}
            )
            withheld.add(name)

    def withhold(q: dict[str, Any]) -> None:
        shown[q["questionId"]] = _withheld_question(q, denominators=True)
        withheld.add(q["questionId"])

    for q in stored["questions"]:
        qid = q["questionId"]
        leaves = [tuple(leaf) for leaf in deps["questionLeaves"].get(qid, [])]
        shape, source = _classify(leaves, by_id)
        if shape == "opaque" or (source is not None and blocked(source)):
            withhold(q)
            continue
        if shape == "new" and settled:
            # Without raw access (Björn, review round 3): never a count
            # selected by a number, date or text answer.
            withhold(q)
            shown[qid] = shown[qid].model_copy(
                update={"withheldReason": "unreleasedCondition"}
            )
            continue
        if shape == "new":
            assert source is not None
            leaf: Leaf = leaves[0]
            if used.get(source, leaf) != leaf:
                withhold(q)
                continue
            used[source] = leaf
            if any(protect([q["relevant"], q["hidden"]], total)):
                withhold(q)
                strip(source)
                continue
        disclosed = _question(q)
        shown[qid] = disclosed
        if _has_withheld(disclosed):
            withheld.add(qid)

    pages = stored["lastPageCounts"]
    page_leaves = [
        [tuple(leaf) for leaf in leaves] for leaves in deps["pageLeaves"].values()
    ]
    shapes = [_classify(leaves, by_id) for leaves in page_leaves]
    sources = {source for _, source in shapes if source is not None}
    if len(pages) <= 1 or not shapes:
        pages_hidden = [False for _ in pages]
    elif any(shape == "opaque" for shape, _ in shapes) or len(sources) > 1:
        pages_hidden = [True for _ in pages]
    else:
        (source,) = sources
        shape = shapes[0][0]
        if blocked(source):
            pages_hidden = [True for _ in pages]
        elif shape == "new":
            if (
                source in used
                or len({leaf for leaves in page_leaves for leaf in leaves}) > 1
            ):
                pages_hidden = [True for _ in pages]
            else:
                # Page counts are then new counts of the unreleased answer.
                pages_hidden = protect([page["count"] for page in pages], total)
                if any(pages_hidden):
                    strip(source)
        else:
            pages_hidden = [False for _ in pages]
    return [shown[q["questionId"]] for q in stored["questions"]], pages_hidden


def _conservative(
    stored: dict[str, Any], total: int
) -> tuple[list[QuestionAggregate], list[bool]]:
    """R4/R5 without recorded condition structure (snapshots from before
    review round 2): any question hidden for someone may be under a
    compound condition, so it is withheld as a whole, and so are the last
    pages whenever any question is."""
    questions = [
        _question(q) if q["hidden"] == 0 else _withheld_question(q, denominators=True)
        for q in stored["questions"]
    ]
    pages = stored["lastPageCounts"]
    conditional = any(q["hidden"] > 0 for q in stored["questions"])
    hide_pages = len(pages) > 1 and (
        conditional or any(_has_withheld(q) for q in questions)
    )
    return questions, [hide_pages for _ in pages]


# Changing what disclose() releases? Bump RENDER_VERSION of both report
# renderers and DISCLOSED_SINCE (export_rendering.py), so stored reports
# rendered under the old rules are never delivered again.
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
    elif total == 0:
        # Nobody in the selection: every count is 0, nothing to hide.
        questions = [_question(q) for q in stored["questions"]]
        pages_hidden = [False for _ in stored["lastPageCounts"]]
    elif (stored.get("dependencies") or {}).get("questionLeaves") is not None:
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
        # Without raw access last pages are never released (Björn, review
        # round 3): they follow every condition, empty pages included.
        lastPageCounts=[]
        if stored.get("disclosurePolicy") == "settled"
        else [
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
