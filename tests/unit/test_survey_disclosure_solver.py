"""Brute-force check of the minimum group size: nothing withheld is solvable.

For small groups we enumerate every multiset of answers, build the stored
snapshot with a reference aggregator, release it through ``disclose`` and
group the candidates by their *complete* released result. Inside a group
an observer (who knows the algorithm) cannot tell the candidates apart, so
every withheld number must take at least two values across the group.
Otherwise it would be uniquely determined by what was released.
"""

import json
from collections import defaultdict
from itertools import combinations_with_replacement, product
from typing import Any
from uuid import UUID

import pytest

from leonaid.modules.surveys.application.disclosure import K, disclose

SURVEY = str(UUID(int=1))
VERSION = str(UUID(int=2))


def bucket(value: Any, count: int, answered: int) -> dict[str, Any]:
    return {
        "value": value,
        "label": str(value),
        "count": count,
        "percentage": count / answered * 100 if answered else None,
    }


def aggregate(
    people: tuple[dict[str, Any], ...], questions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Reference aggregator: one stored snapshot from participants' answers."""
    out = []
    for q in questions:
        cond = q.get("if")
        relevant = [p for p in people if not cond or p.get(cond[0]) == cond[1]]
        given = [p[q["id"]] for p in relevant if p.get(q["id"]) is not None]
        n = len(given)
        entry: dict[str, Any] = {
            "questionId": q["id"],
            "title": q["id"],
            "kind": q["kind"],
            "relevant": len(relevant),
            "answered": n,
            "unanswered": len(relevant) - n,
            "hidden": len(people) - len(relevant),
            "invalid": 0,
            "counts": [],
            "sum": None,
            "mean": None,
            "minimum": None,
            "maximum": None,
            "nps": None,
            "matrixRows": [],
        }
        if q["kind"] == "matrix":
            for row in q["rows"]:
                cells = [a[row] for a in given]
                entry["matrixRows"].append(
                    {
                        "rowId": row,
                        "label": row,
                        "answered": len(cells),
                        "unanswered": len(relevant) - len(cells),
                        "invalid": 0,
                        "counts": [
                            bucket(o, cells.count(o), len(cells)) for o in q["options"]
                        ],
                    }
                )
        elif q["kind"] != "number":
            entry["counts"] = [bucket(o, given.count(o), n) for o in q["options"]]
        if q["kind"] in {"rating", "number"} and n:
            entry["sum"] = float(sum(given))
            entry["mean"] = sum(given) / n
            entry["minimum"] = float(min(given))
            entry["maximum"] = float(max(given))
            if q["options"] == list(range(11)):
                promoters = sum(1 for g in given if g >= 9)
                detractors = sum(1 for g in given if g <= 6)
                entry["nps"] = (promoters - detractors) / n * 100
        out.append(entry)
    # Page visibility follows the first condition, if any.
    cond = next((q["if"] for q in questions if q.get("if")), None)
    follow = sum(1 for p in people if cond and p.get(cond[0]) == cond[1])
    return {
        "id": str(UUID(int=3)),
        "surveyId": SURVEY,
        "createdAt": "2026-11-04T10:00:00+00:00",
        "filter": {
            "versionId": VERSION,
            "statuses": ["completed"],
            "isTest": False,
            "createdFrom": None,
            "createdBefore": "2026-11-03T23:00:00+00:00",
        },
        "versionNumber": 1,
        "rendererVersion": "3.0.3",
        "capabilityProfile": "initial-v1",
        "participationCount": len(people),
        "statusCounts": {"in_progress": 0, "partial": 0, "completed": len(people)},
        "lastPageCounts": [
            {"pageId": "main", "title": "main", "count": len(people) - follow}
        ]
        + (
            [{"pageId": "followup", "title": "followup", "count": follow}]
            if cond
            else []
        ),
        "questions": out,
        "dependencies": {
            "questions": {q["id"]: [q["if"][0]] for q in questions if q.get("if")},
            "pages": {"followup": [cond[0]]} if cond else {},
        },
    }


def withheld_numbers(
    stored: dict[str, Any], shown: dict[str, Any]
) -> dict[str, float | None]:
    """Every number the release withholds, keyed by its path, with its true value."""
    found: dict[str, float | None] = {}
    if shown["participationCount"] is None:
        found["participationCount"] = stored["participationCount"]
    for key, value in shown["statusCounts"].items():
        if value is None:
            found[f"status.{key}"] = stored["statusCounts"][key]
    for index, page in enumerate(shown["lastPageCounts"]):
        if page["count"] is None:
            found[f"page.{index}"] = stored["lastPageCounts"][index]["count"]
    for sq, q in zip(stored["questions"], shown["questions"], strict=True):
        qid = sq["questionId"]
        for key in ("relevant", "answered", "unanswered", "hidden", "invalid"):
            if q[key] is None:
                found[f"{qid}.{key}"] = sq[key]
        if q["counts"]:
            for sb, b in zip(sq["counts"], q["counts"], strict=True):
                if b["count"] is None:
                    found[f"{qid}.count.{sb['value']}"] = sb["count"]
        elif sq["counts"]:
            for sb in sq["counts"]:
                found[f"{qid}.count.{sb['value']}"] = sb["count"]
        rows = {r["rowId"]: r for r in q["matrixRows"]}
        for srow in sq["matrixRows"]:
            row = rows.get(srow["rowId"])
            for index, sb in enumerate(srow["counts"]):
                if (
                    row is None
                    or not row["counts"]
                    or row["counts"][index]["count"] is None
                ):
                    found[f"{qid}.{srow['rowId']}.{sb['value']}"] = sb["count"]
        if q["kind"] == "rating" and q["nps"] is None and sq["nps"] is not None:
            found[f"{qid}.nps"] = round(sq["nps"], 9)
    return found


def check(
    questions: list[dict[str, Any]],
    answers: list[dict[str, Any]],
    sizes,
    *,
    legacy: bool = False,
):
    """Enumerate, group by release, and assert nothing withheld is unique."""
    examined = withheld_total = 0
    # Across all sizes: the group size itself may be withheld (R0).
    groups: dict[str, list[dict[str, float | None]]] = defaultdict(list)
    for size in sizes:
        for people in combinations_with_replacement(range(len(answers)), size):
            stored = aggregate(tuple(answers[i] for i in people), questions)
            if legacy:  # a snapshot from before references were recorded
                del stored["dependencies"]
            shown = disclose(stored).model_dump()
            key = json.dumps(shown, sort_keys=True)
            groups[key].append(withheld_numbers(stored, shown))
            examined += 1
    # A number that is the same in every possible answer set (e.g. "hidden"
    # of an unconditional question) is known beforehand; nothing to protect.
    seen: dict[str, set[float | None]] = defaultdict(set)
    for members in groups.values():
        for m in members:
            for path, value in m.items():
                seen[path].add(value)
    for key, members in groups.items():
        for path in members[0]:
            if len(seen[path]) == 1:
                continue
            # Legacy snapshots may over-withhold derivable denominators and
            # pages (safe); their answer counts must still not be solvable.
            if legacy and ".count." not in path:
                continue
            values = {m.get(path) for m in members}
            withheld_total += 1
            assert len(values) > 1, (
                f"{path} is uniquely {values} in release {key[:600]}"
            )
    return examined, withheld_total


def options_answers(qid: str, options: list[Any]) -> list[dict[str, Any]]:
    # Each person picks one option or skips the question.
    return [{qid: o} for o in options] + [{qid: None}]


@pytest.mark.parametrize(
    ("name", "questions", "answers", "sizes"),
    [
        (
            "single choice",
            [{"id": "q", "kind": "radiogroup", "options": ["a", "b", "c"]}],
            options_answers("q", ["a", "b", "c"]),
            range(1, 15),
        ),
        (
            "rating 1-5",
            [{"id": "r", "kind": "rating", "options": [1, 2, 3, 4, 5]}],
            options_answers("r", [1, 2, 3, 4, 5]),
            range(1, 12),
        ),
        (
            "nps 0-10",
            [{"id": "n", "kind": "rating", "options": list(range(11))}],
            options_answers("n", list(range(11))),
            [1, 3, 5, 6, 7],
        ),
        (
            "matrix 2x2",
            [
                {
                    "id": "m",
                    "kind": "matrix",
                    "options": ["g", "b"],
                    "rows": ["r1", "r2"],
                }
            ],
            [{"m": {"r1": x, "r2": y}} for x, y in product(["g", "b"], repeat=2)],
            range(1, 13),
        ),
        (
            "conditional",
            [
                {"id": "gate", "kind": "radiogroup", "options": ["yes", "no"]},
                {
                    "id": "follow",
                    "kind": "radiogroup",
                    "options": ["a", "b"],
                    "if": ("gate", "yes"),
                },
            ],
            [
                {"gate": "no"},
                {"gate": "yes", "follow": "a"},
                {"gate": "yes", "follow": "b"},
                {"gate": "yes", "follow": None},
            ],
            range(1, 16),
        ),
    ],
)
def test_no_withheld_number_is_uniquely_determined(name, questions, answers, sizes):
    examined, withheld = check(questions, answers, sizes)
    print(f"{name}: {examined} answer sets, {withheld} withheld numbers checked")
    assert examined and withheld


CONDITIONAL_RATING = [
    {"id": "gate", "kind": "radiogroup", "options": ["yes", "no"]},
    {"id": "score", "kind": "rating", "options": [1, 2, 3], "if": ("gate", "yes")},
]
CONDITIONAL_RATING_ANSWERS = [
    {"gate": "no"},
    {"gate": None},
    {"gate": "yes", "score": 1},
    {"gate": "yes", "score": 2},
    {"gate": "yes", "score": 3},
]


def test_condition_on_a_number_protects_the_shown_hidden_pair():
    """A condition on a number: its distribution is never released, so the
    conditional question's shown/hidden pair is a new count (R4)."""
    questions = [
        {"id": "hours", "kind": "number", "options": [5, 15]},
        {"id": "follow", "kind": "radiogroup", "options": ["a"], "if": ("hours", 15)},
    ]
    answers = [
        {"hours": 5},
        {"hours": 15, "follow": "a"},
        {"hours": 15, "follow": None},
    ]
    examined, withheld = check(questions, answers, range(1, 16))
    print(f"condition on a number: {examined} answer sets, {withheld} withheld")
    assert examined and withheld


@pytest.mark.parametrize("legacy", [False, True])
def test_conditional_rating_with_and_without_recorded_references(legacy):
    examined, withheld = check(
        CONDITIONAL_RATING, CONDITIONAL_RATING_ANSWERS, range(1, 13), legacy=legacy
    )
    name = "conditional rating" + (" (legacy snapshot)" if legacy else "")
    print(f"{name}: {examined} answer sets, {withheld} withheld numbers checked")
    assert examined and withheld


def test_the_solver_catches_a_leak():
    """Sanity: the old rule (one extra cell only) fails the same check."""
    from leonaid.modules.surveys.application import disclosure

    def old(counts, total):
        hidden = [0 < c < K for c in counts]
        if total is not None and sum(hidden) == 1:
            rest = [(c, i) for i, c in enumerate(counts) if c > 0 and not hidden[i]]
            if rest:
                hidden[min(rest)[1]] = True
        return hidden

    original = disclosure.protect
    disclosure.protect = old
    try:
        with pytest.raises(AssertionError, match="uniquely"):
            check(
                [{"id": "q", "kind": "radiogroup", "options": ["a", "b", "c"]}],
                options_answers("q", ["a", "b", "c"]),
                range(10, 13),
            )
    finally:
        disclosure.protect = original
