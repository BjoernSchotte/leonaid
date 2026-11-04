"""Brute-force check of the minimum group size: nothing withheld is solvable.

For small groups we enumerate every multiset of answer profiles, build the
stored snapshot with a reference aggregator (conditions, pages, checkbox
sets), release it through ``disclose`` and group the candidates by their
*complete* released result. Inside a group an observer who knows the
algorithm cannot tell the candidates apart. So:

- every withheld count that stands for 1 to K - 1 people must take at least
  two values across the group (for a withheld NPS score: its segments);
- every scenario *secret* (a cross-tab cell of two answers, a co-occurrence
  of two checkbox options, the people with one exact number) that stands
  for 1 to K - 1 people must as well. Secrets are what a condition or a
  bound could give away although no released number states them.

A number that is the same in every possible answer set is known beforehand
and is skipped. The number mean is an accepted residual (Björn Schotte,
2026-11-04): scenarios on number answers leave it out of the stored input.
"""

import json
from collections import defaultdict
from collections.abc import Callable, Iterable
from itertools import combinations, combinations_with_replacement, product
from typing import Any
from uuid import UUID

import pytest

from leonaid.modules.surveys.application import disclosure
from leonaid.modules.surveys.application.disclosure import K, disclose

SURVEY = str(UUID(int=1))
VERSION = str(UUID(int=2))

# A condition: ("leaf", name, op, value) or ("and" | "or", [conditions]).
Condition = tuple[Any, ...]


def bucket(value: Any, count: int, answered: int) -> dict[str, Any]:
    return {
        "value": value,
        "label": str(value),
        "count": count,
        "percentage": count / answered * 100 if answered else None,
    }


def evaluate(condition: Condition | None, person: dict[str, Any]) -> bool:
    """visibleIf semantics of domain/validation.py, on Python values."""
    if condition is None:
        return True
    if condition[0] in {"and", "or"}:
        results = [evaluate(part, person) for part in condition[1]]
        return all(results) if condition[0] == "and" else any(results)
    _, name, op, expected = condition
    value = person.get(name)
    empty = value is None or value == ()
    if op in {"empty", "notempty"}:
        return empty if op == "empty" else not empty
    if empty:
        return op in {"!=", "notcontains"}
    if op in {"=", "!="}:
        return (value == expected) == (op == "=")
    if op in {"contains", "notcontains"}:
        return (isinstance(value, tuple) and expected in value) == (op == "contains")
    if not isinstance(value, (int, float)):
        return False
    return {
        "<": value < expected,
        "<=": value <= expected,
        ">": value > expected,
        ">=": value >= expected,
    }[op]


def leaves(condition: Condition | None) -> list[list[str]]:
    if condition is None:
        return []
    if condition[0] in {"and", "or"}:
        return [leaf for part in condition[1] for leaf in leaves(part)]
    _, name, op, expected = condition
    return [[name, op, json.dumps(expected)]]


def aggregate(
    people: Iterable[dict[str, Any]],
    questions: list[dict[str, Any]],
    pages: list[dict[str, Any]] = (),  # type: ignore[assignment]
    *,
    mean: bool = True,
) -> dict[str, Any]:
    """Reference aggregator: one stored snapshot from completed answers."""
    people = list(people)
    page_conditions = {page["id"]: page.get("if") for page in pages}

    def relevant_for(q: dict[str, Any], p: dict[str, Any]) -> bool:
        return evaluate(page_conditions.get(q.get("page")), p) and evaluate(
            q.get("if"), p
        )

    out = []
    for q in questions:
        relevant = [p for p in people if relevant_for(q, p)]
        given = [p[q["id"]] for p in relevant if p.get(q["id"]) not in (None, ())]
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
                cells = [a[row] for a in given if a.get(row) is not None]
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
        elif q["kind"] == "checkbox":
            entry["counts"] = [
                bucket(o, sum(o in g for g in given), n) for o in q["options"]
            ]
        elif q["kind"] != "number":
            entry["counts"] = [bucket(o, given.count(o), n) for o in q["options"]]
        if q["kind"] in {"rating", "number"} and n:
            entry["sum"] = float(sum(given))
            entry["mean"] = sum(given) / n if mean or q["kind"] == "rating" else None
            entry["minimum"] = float(min(given))
            entry["maximum"] = float(max(given))
            if q["options"] == list(range(11)):
                promoters = sum(1 for g in given if g >= 9)
                detractors = sum(1 for g in given if g <= 6)
                entry["nps"] = (promoters - detractors) / n * 100
        out.append(entry)
    order = ["main", *(page["id"] for page in pages)]
    last = defaultdict(int)
    for p in people:
        # Completed participations end on their last visible page.
        last[[pid for pid in order if evaluate(page_conditions.get(pid), p)][-1]] += 1
    question_leaves = {}
    for q in questions:
        found = [*leaves(page_conditions.get(q.get("page"))), *leaves(q.get("if"))]
        if found:
            question_leaves[q["id"]] = found
    page_leaves = {
        page["id"]: leaves(page.get("if")) for page in pages if page.get("if")
    }
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
            {"pageId": pid, "title": pid, "count": last[pid]} for pid in order
        ],
        "questions": out,
        "dependencies": {
            "questions": {
                qid: sorted({leaf[0] for leaf in found})
                for qid, found in question_leaves.items()
            },
            "pages": {
                pid: sorted({leaf[0] for leaf in found})
                for pid, found in page_leaves.items()
            },
            "questionLeaves": question_leaves,
            "pageLeaves": page_leaves,
        },
    }


def withheld_numbers(stored: dict[str, Any], shown: dict[str, Any]) -> dict[str, Any]:
    """Every number the release withholds, keyed by its path, with its true value."""
    found: dict[str, Any] = {}
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
        else:
            for sb in sq["counts"]:
                found[f"{qid}.count.{sb['value']}"] = sb["count"]
        rows = {r["rowId"]: r for r in q["matrixRows"]}
        for srow in sq["matrixRows"]:
            row = rows.get(srow["rowId"])
            for key in ("answered", "unanswered"):
                if row is None or row[key] is None:
                    found[f"{qid}.{srow['rowId']}.{key}"] = srow[key]
            for index, sb in enumerate(srow["counts"]):
                if (
                    row is None
                    or not row["counts"]
                    or row["counts"][index]["count"] is None
                ):
                    found[f"{qid}.{srow['rowId']}.{sb['value']}"] = sb["count"]
        if q["kind"] == "rating" and q["nps"] is None and sq["nps"] is not None:
            # A withheld score is a function of the segment sizes; those are
            # the people to protect.
            scores = [(float(b["value"]), b["count"]) for b in sq["counts"]]
            found[f"{qid}.segment.detractors"] = sum(c for v, c in scores if v <= 6)
            found[f"{qid}.segment.passives"] = sum(c for v, c in scores if 6 < v <= 8)
            found[f"{qid}.segment.promoters"] = sum(c for v, c in scores if v > 8)
    return found


def small(path: str, value: Any) -> bool:
    """A value that must not be pinned: a group of 1 to K - 1 people."""
    return isinstance(value, int) and 0 < value < K


def check(
    questions: list[dict[str, Any]],
    answers: list[dict[str, Any]],
    sizes: Iterable[int],
    *,
    pages: list[dict[str, Any]] = (),  # type: ignore[assignment]
    legacy: bool = False,
    secrets: Callable[[list[dict[str, Any]]], dict[str, int]] | None = None,
    mean: bool = True,
) -> tuple[int, int]:
    """Enumerate, group by release, and assert nothing small is pinned."""
    examined = checked = 0
    # Across all sizes: the group size itself may be withheld (R0).
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for size in sizes:
        for chosen in combinations_with_replacement(range(len(answers)), size):
            people = [answers[i] for i in chosen]
            stored = aggregate(people, questions, pages, mean=mean)
            if legacy:  # a snapshot from before the condition structure
                del stored["dependencies"]
            shown = disclose(stored).model_dump()
            truth = withheld_numbers(stored, shown)
            if secrets:
                truth.update({f"secret.{k}": v for k, v in secrets(people).items()})
            groups[json.dumps(shown, sort_keys=True)].append(truth)
            examined += 1
    seen: dict[str, set[Any]] = defaultdict(set)
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
            if legacy and ".count." not in path and not path.startswith("secret."):
                continue
            values = {m.get(path) for m in members}
            if len(values) == 1 and small(path, next(iter(values))):
                raise AssertionError(
                    f"{path} is uniquely {values} in release {key[:600]}"
                )
            checked += 1
    return examined, checked


def options_answers(qid: str, options: list[Any]) -> list[dict[str, Any]]:
    # Each person picks one option or skips the question.
    return [{qid: o} for o in options] + [{qid: None}]


def joint(a: str, b: str) -> Callable[[list[dict[str, Any]]], dict[str, int]]:
    """Cross-tab cells of two answers (people who answered both)."""

    def cells(people: list[dict[str, Any]]) -> dict[str, int]:
        result: dict[str, int] = defaultdict(int)
        for p in people:
            if p.get(a) is not None and p.get(b) is not None:
                result[f"{a}={p[a]}&{b}={p[b]}"] += 1
        return result

    return cells


def co_occurrence(qid: str, options: list[str]):
    """People who ticked both of two options."""

    def cells(people: list[dict[str, Any]]) -> dict[str, int]:
        return {
            f"{x}&{y}": sum(
                1 for p in people if x in (p.get(qid) or ()) and y in p[qid]
            )
            for x, y in combinations(options, 2)
        }

    return cells


def exact(qid: str, values: list[Any]):
    """People with each exact value of an unreleased answer."""

    def cells(people: list[dict[str, Any]]) -> dict[str, int]:
        return {f"{qid}={v}": sum(1 for p in people if p.get(qid) == v) for v in values}

    return cells


def subsets(options: list[str], low: int, high: int) -> list[tuple[str, ...]]:
    return [
        combo for size in range(low, high + 1) for combo in combinations(options, size)
    ]


GATES = [{"g1": x, "g2": y} for x, y in product(["yes", "no"], repeat=2)]


def gated(condition: Condition) -> list[dict[str, Any]]:
    return [
        {"id": "g1", "kind": "radiogroup", "options": ["yes", "no"]},
        {"id": "g2", "kind": "radiogroup", "options": ["yes", "no"]},
        {"id": "f", "kind": "radiogroup", "options": ["a"], "if": condition},
    ]


def gated_answers(condition: Condition) -> list[dict[str, Any]]:
    result = []
    for gates in GATES:
        if evaluate(condition, gates):
            result.append({**gates, "f": "a"})
        else:
            result.append(dict(gates))
    return result


BOTH = ("and", [("leaf", "g1", "=", "yes"), ("leaf", "g2", "=", "yes")])
EITHER = ("or", [("leaf", "g1", "=", "yes"), ("leaf", "g2", "=", "yes")])
CHECKS = ["A", "B", "C"]
TICK_BOTH = ("and", [("leaf", "c", "contains", "A"), ("leaf", "c", "contains", "B")])
TICK_EITHER = ("or", [("leaf", "c", "contains", "A"), ("leaf", "c", "contains", "B")])


def ticked(condition: Condition, options: list[str], high: int) -> list[dict[str, Any]]:
    result = []
    for combo in subsets(options, 1, high):
        person = {"c": combo}
        if evaluate(condition, person):
            person["f"] = "a"
        result.append(person)
    return result


def ticked_questions(condition: Condition) -> list[dict[str, Any]]:
    return [
        {"id": "c", "kind": "checkbox", "options": CHECKS},
        {"id": "f", "kind": "radiogroup", "options": ["a"], "if": condition},
    ]


def thresholds() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    questions = [
        {"id": "h", "kind": "number", "options": [5, 10, 15]},
        {
            "id": "f1",
            "kind": "radiogroup",
            "options": ["a"],
            "if": ("leaf", "h", ">=", 10),
        },
        {
            "id": "f2",
            "kind": "radiogroup",
            "options": ["a"],
            "if": ("leaf", "h", ">=", 11),
        },
    ]
    answers = []
    for h in [5, 10, 15]:
        person: dict[str, Any] = {"h": h}
        if h >= 10:
            person["f1"] = "a"
        if h >= 11:
            person["f2"] = "a"
        answers.append(person)
    return questions, answers


NPS_ANSWERS = [0, 7, 9, 10]
"""A reduced NPS answer set, so groups up to 26 stay enumerable while cells
reach 2K and segments are partly released."""

SCENARIOS: dict[str, dict[str, Any]] = {
    "single choice": {
        "questions": [{"id": "q", "kind": "radiogroup", "options": ["a", "b", "c"]}],
        "answers": options_answers("q", ["a", "b", "c"]),
        "sizes": range(1, 15),
    },
    "single choice, sizes 20 to 26": {
        "questions": [{"id": "q", "kind": "radiogroup", "options": ["a", "b", "c"]}],
        "answers": options_answers("q", ["a", "b", "c"]),
        "sizes": range(20, 27),
        "new": True,
    },
    "rating 1-5": {
        "questions": [{"id": "r", "kind": "rating", "options": [1, 2, 3, 4, 5]}],
        "answers": options_answers("r", [1, 2, 3, 4, 5]),
        "sizes": range(1, 12),
    },
    "nps 0-10, sizes to 7": {
        "questions": [{"id": "n", "kind": "rating", "options": list(range(11))}],
        "answers": options_answers("n", list(range(11))),
        "sizes": [1, 3, 5, 6, 7],
    },
    "nps 0-10, four scores used, sizes to 26": {
        "questions": [{"id": "n", "kind": "rating", "options": list(range(11))}],
        "answers": [{"n": v} for v in NPS_ANSWERS],
        "sizes": range(1, 27),
        "new": True,
    },
    "matrix 2x2": {
        "questions": [
            {"id": "m", "kind": "matrix", "options": ["g", "b"], "rows": ["r1", "r2"]}
        ],
        "answers": [
            {"m": {"r1": x, "r2": y}} for x, y in product(["g", "b"], repeat=2)
        ],
        "sizes": range(1, 13),
    },
    "matrix with one column": {
        "questions": [
            {"id": "m", "kind": "matrix", "options": ["x"], "rows": ["r1", "r2"]}
        ],
        "answers": [
            {"m": {"r1": "x", "r2": "x"}},
            {"m": {"r1": "x"}},
            {"m": {"r2": "x"}},
            {"m": None},
        ],
        "sizes": range(1, 13),
        "new": True,
    },
    "conditional": {
        "questions": [
            {"id": "gate", "kind": "radiogroup", "options": ["yes", "no"]},
            {
                "id": "follow",
                "kind": "radiogroup",
                "options": ["a", "b"],
                "if": ("leaf", "gate", "=", "yes"),
            },
        ],
        "answers": [
            {"gate": "no"},
            {"gate": "yes", "follow": "a"},
            {"gate": "yes", "follow": "b"},
            {"gate": "yes", "follow": None},
        ],
        "sizes": range(1, 16),
    },
    "conditional page": {
        "questions": [
            {"id": "gate", "kind": "radiogroup", "options": ["yes", "no"]},
            {"id": "follow", "kind": "radiogroup", "options": ["a", "b"], "page": "p2"},
        ],
        "pages": [{"id": "p2", "if": ("leaf", "gate", "=", "yes")}],
        "answers": [
            {"gate": "no"},
            {"gate": "yes", "follow": "a"},
            {"gate": "yes", "follow": "b"},
        ],
        "sizes": range(1, 16),
    },
    "compound and on two answers": {
        "questions": gated(BOTH),
        "answers": gated_answers(BOTH),
        "sizes": range(1, 16),
        "secrets": joint("g1", "g2"),
        "new": True,
    },
    "compound or on two answers": {
        "questions": gated(EITHER),
        "answers": gated_answers(EITHER),
        "sizes": range(1, 16),
        "secrets": joint("g1", "g2"),
        "new": True,
    },
    "two pages on two answers": {
        "questions": [
            {"id": "g1", "kind": "radiogroup", "options": ["yes", "no"]},
            {"id": "g2", "kind": "radiogroup", "options": ["yes", "no"]},
        ],
        "pages": [
            {"id": "p2", "if": ("leaf", "g1", "=", "yes")},
            {"id": "p3", "if": ("leaf", "g2", "=", "yes")},
        ],
        "answers": GATES,
        "sizes": range(1, 16),
        "secrets": joint("g1", "g2"),
        "new": True,
    },
    "checkbox contains A and contains B": {
        "questions": ticked_questions(TICK_BOTH),
        "answers": ticked(TICK_BOTH, CHECKS, 3),
        "sizes": range(1, 12),
        "secrets": co_occurrence("c", CHECKS),
        "new": True,
    },
    "checkbox contains A or contains B": {
        "questions": ticked_questions(TICK_EITHER),
        "answers": ticked(TICK_EITHER, CHECKS, 3),
        "sizes": range(1, 12),
        "secrets": co_occurrence("c", CHECKS),
        "new": True,
    },
    "checkbox, no maximum": {
        "questions": [{"id": "c", "kind": "checkbox", "options": CHECKS}],
        "answers": [{"c": s} for s in subsets(CHECKS, 1, 3)] + [{"c": None}],
        "sizes": range(1, 12),
        "secrets": co_occurrence("c", CHECKS),
        "new": True,
    },
    "checkbox, maxSelectedChoices 1": {
        "questions": [{"id": "c", "kind": "checkbox", "options": CHECKS}],
        "answers": [{"c": s} for s in subsets(CHECKS, 1, 1)] + [{"c": None}],
        "sizes": range(1, 15),
        "new": True,
    },
    "checkbox, at most 2": {
        "questions": [{"id": "c", "kind": "checkbox", "options": CHECKS}],
        "answers": [{"c": s} for s in subsets(CHECKS, 1, 2)] + [{"c": None}],
        "sizes": range(1, 14),
        "secrets": co_occurrence("c", CHECKS),
        "new": True,
    },
    "checkbox, exactly 2": {
        "questions": [{"id": "c", "kind": "checkbox", "options": CHECKS}],
        "answers": [{"c": s} for s in subsets(CHECKS, 2, 2)] + [{"c": None}],
        "sizes": range(1, 15),
        "new": True,
    },
    "two conditions on one released answer": {
        "questions": [
            {"id": "g", "kind": "radiogroup", "options": ["a", "b", "c"]},
            {
                "id": "f1",
                "kind": "radiogroup",
                "options": ["x"],
                "if": ("leaf", "g", "=", "a"),
            },
            {
                "id": "f2",
                "kind": "radiogroup",
                "options": ["x"],
                "if": ("leaf", "g", "!=", "b"),
            },
        ],
        "answers": [
            {"g": "a", "f1": "x", "f2": "x"},
            {"g": "a", "f1": "x"},
            {"g": "a", "f2": "x"},
            {"g": "a"},
            {"g": "b"},
            {"g": "c", "f2": "x"},
            {"g": "c"},
            {"f2": "x"},
            {},
        ],
        "sizes": range(1, 11),
        "new": True,
    },
    "two conditions on one number": {
        "questions": thresholds()[0],
        "answers": thresholds()[1],
        "sizes": range(1, 20),
        "secrets": exact("h", [5, 10, 15]),
        "mean": False,
        "new": True,
    },
}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_no_withheld_number_is_uniquely_determined(name):
    scenario = SCENARIOS[name]
    examined, checked = check(
        scenario["questions"],
        scenario["answers"],
        scenario["sizes"],
        pages=scenario.get("pages", []),
        secrets=scenario.get("secrets"),
        mean=scenario.get("mean", True),
    )
    print(f"{name}: {examined} answer sets, {checked} withheld numbers checked")
    assert examined and checked


CONDITIONAL_RATING = [
    {"id": "gate", "kind": "radiogroup", "options": ["yes", "no"]},
    {
        "id": "score",
        "kind": "rating",
        "options": [1, 2, 3],
        "if": ("leaf", "gate", "=", "yes"),
    },
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
        {
            "id": "follow",
            "kind": "radiogroup",
            "options": ["a"],
            "if": ("leaf", "hours", "=", 15),
        },
    ]
    answers = [
        {"hours": 5},
        {"hours": 15, "follow": "a"},
        {"hours": 15, "follow": None},
    ]
    examined, checked = check(
        questions, answers, range(1, 16), secrets=exact("hours", [5, 15]), mean=False
    )
    print(f"condition on a number: {examined} answer sets, {checked} checked")
    assert examined and checked


@pytest.mark.parametrize("legacy", [False, True])
def test_conditional_rating_with_and_without_recorded_conditions(legacy):
    examined, checked = check(
        CONDITIONAL_RATING, CONDITIONAL_RATING_ANSWERS, range(1, 13), legacy=legacy
    )
    name = "conditional rating" + (" (legacy snapshot)" if legacy else "")
    print(f"{name}: {examined} answer sets, {checked} withheld numbers checked")
    assert examined and checked


def test_legacy_snapshots_withhold_compound_conditions():
    """Without the recorded structure every conditional question may sit
    under a compound condition, so the cross-tab must stay unsolvable."""
    examined, checked = check(
        gated(BOTH),
        gated_answers(BOTH),
        range(1, 16),
        legacy=True,
        secrets=joint("g1", "g2"),
    )
    print(f"compound and (legacy snapshot): {examined} answer sets, {checked} checked")
    assert examined and checked


def test_a_number_never_releases_its_extremes():
    """R6: over every answer set, a number's minimum and maximum stay
    withheld, and its other withheld numbers are not solvable. The mean is
    an accepted residual (Björn Schotte, 2026-11-04): mean plus count can
    determine single answers near the range edges, so it is not checked
    for uniqueness here."""
    questions = [{"id": "hours", "kind": "number", "options": [0, 5, 15, 30]}]
    answers = [{"hours": v} for v in [0, 5, 15, 30]] + [{"hours": None}]
    released = 0
    for size in range(1, 12):
        for people in combinations_with_replacement(range(len(answers)), size):
            stored = aggregate([answers[i] for i in people], questions)
            shown = disclose(stored).questions[0]
            assert (shown.minimum, shown.maximum) == (None, None)
            released += shown.mean is not None
    assert released  # the mean is shown from k answers on
    examined, checked = check(questions, answers, range(1, 12))
    print(f"number: {examined} answer sets, {checked} withheld numbers checked")
    assert examined and checked


def test_the_solver_catches_a_leak():
    """Sanity: the old one-extra-cell rule fails the same check (R1)."""

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


def test_the_solver_catches_a_released_cross_tab():
    """Sanity: treating every condition as simple (round 1) releases the
    relevant count of a compound condition, and the solver finds it (R4)."""
    original = disclosure._classify

    def lenient(leaves, questions):
        shape, source = original(leaves[:1], questions)
        return ("derived", source) if shape == "derived" else (shape, source)

    disclosure._classify = lenient
    try:
        with pytest.raises(AssertionError, match="uniquely"):
            check(
                gated(BOTH),
                gated_answers(BOTH),
                range(1, 12),
                secrets=joint("g1", "g2"),
            )
    finally:
        disclosure._classify = original
