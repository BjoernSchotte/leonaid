"""Brute-force check of the minimum group size: nothing withheld is solvable.

Scenarios are real SurveyJS definitions (``survey_solver_scenarios.py``).
SurveyJS decides per answer profile what one person contributes: visible
questions and pages (empty pages included), the answers left after hidden-
value clearing, the recorded counts and the last page
(``tests/fixtures/surveys/solver-profiles.json``). For small groups we
enumerate every multiset of profiles, build the stored snapshot with the
server's own code (``merge_aggregates``, ``finish_aggregates``,
``last_page_counts``, ``dependencies``), release it through ``disclose``
and group the candidates by their *complete* released result. Inside a
group an observer who knows the algorithm cannot tell the candidates
apart, so:

- every withheld count that stands for 1 to K - 1 people must take at least
  two values across the group (for a withheld NPS score: its segments);
- every scenario *secret* (a cross-tab cell of two answers, a co-occurrence
  of two checkbox options, the people with one exact number) that stands
  for 1 to K - 1 people must as well. Secrets are what a condition or a
  page could give away although no released number states them.

A number that is the same in every possible answer set is known beforehand
and is skipped. The number mean is an accepted residual (Björn Schotte,
2026-11-04): scenarios on number answers leave it out of the stored input.
Snapshots are settled ones (accounts without raw access), the policy the
rules are written for.
"""

import json
from collections import defaultdict
from collections.abc import Callable
from itertools import combinations, combinations_with_replacement
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from leonaid.modules.surveys.adapters.postgres.survey_analysis import (
    dependencies,
    finish_aggregates,
    last_page_counts,
    merge_aggregates,
)
from leonaid.modules.surveys.application import disclosure
from leonaid.modules.surveys.application.analysis import QuestionAggregate
from leonaid.modules.surveys.application.disclosure import K

from tests.unit.survey_solver_scenarios import SCENARIOS, surveyjs_input

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures/surveys/solver-profiles.json").read_text()
)


def profiles(name: str) -> list[dict[str, Any]]:
    """One SurveyJS result per distinct contribution of a person."""
    seen: dict[str, dict[str, Any]] = {}
    for result in FIXTURE["results"][name]:
        key = json.dumps([result["questions"], result["lastPage"]], sort_keys=True)
        seen.setdefault(key, result)
    return list(seen.values())


def build(scenario: dict[str, Any], people: list[dict[str, Any]]) -> dict[str, Any]:
    """The stored snapshot of these completed participations."""
    definition = scenario["definition"]
    total = [QuestionAggregate.model_validate(q) for q in people[0]["questions"]]
    for person in people[1:]:
        merge_aggregates(
            total, [QuestionAggregate.model_validate(q) for q in person["questions"]]
        )
    questions = [q.model_dump() for q in finish_aggregates(definition, total)]
    if scenario.get("mean", True) is False:
        for q in questions:
            if q["kind"] == "number":
                q["mean"] = None
    recorded = dependencies(definition)
    if scenario.get("legacy"):
        recorded = None
    return {
        "id": str(UUID(int=3)),
        "surveyId": str(UUID(int=1)),
        "createdAt": "2026-11-04T10:00:00+00:00",
        "filter": {
            "versionId": str(UUID(int=2)),
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
        "lastPageCounts": last_page_counts(
            definition, [person["lastPage"] for person in people]
        ),
        "questions": questions,
        "dependencies": recorded,
        "disclosurePolicy": "settled",
    }


def withheld_numbers(stored: dict[str, Any], shown: dict[str, Any]) -> dict[str, Any]:
    """Every number the release withholds, keyed by its path, with its true value."""
    found: dict[str, Any] = {}
    if shown["participationCount"] is None:
        found["participationCount"] = stored["participationCount"]
    for key, value in shown["statusCounts"].items():
        if value is None:
            found[f"status.{key}"] = stored["statusCounts"][key]
    released = {page["pageId"]: page["count"] for page in shown["lastPageCounts"]}
    for page in stored["lastPageCounts"]:
        if released.get(page["pageId"]) is None:
            found[f"page.{page['pageId']}"] = page["count"]
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


def secrets(spec: list[Any] | None) -> Callable[[list[dict[str, Any]]], dict[str, int]]:
    """Counts no release may pin down, from the answers SurveyJS kept."""
    if spec is None:
        return lambda people: {}
    kind, name, extra = spec
    if kind == "joint":  # cross-tab cells of two answers

        def joint(people: list[dict[str, Any]]) -> dict[str, int]:
            result: dict[str, int] = defaultdict(int)
            for p in people:
                values = p["values"]
                if name in values and extra in values:
                    result[f"{name}={values[name]}&{extra}={values[extra]}"] += 1
            return result

        return joint
    if kind == "co":  # people who ticked both of two options

        def co(people: list[dict[str, Any]]) -> dict[str, int]:
            return {
                f"{x}&{y}": sum(
                    1
                    for p in people
                    if x in p["values"].get(name, []) and y in p["values"].get(name, [])
                )
                for x, y in combinations(extra, 2)
            }

        return co

    def exact(people: list[dict[str, Any]]) -> dict[str, int]:
        return {
            f"{name}={v}": sum(1 for p in people if p["values"].get(name) == v)
            for v in extra
        }

    return exact


def small(value: Any) -> bool:
    """A value that must not be pinned: a group of 1 to K - 1 people."""
    return isinstance(value, int) and 0 < value < K


def check(name: str, *, disclose: Callable[[dict[str, Any]], Any] | None = None):
    """Enumerate, group by release, and assert nothing small is pinned."""
    disclose = disclose or disclosure.disclose
    scenario = SCENARIOS[name]
    people_set = profiles(name)
    secret = secrets(scenario.get("secrets"))
    low, high = scenario["sizes"]
    examined = checked = 0
    # Across all sizes: the group size itself may be withheld (R0).
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for size in range(low, high + 1):
        for chosen in combinations_with_replacement(range(len(people_set)), size):
            people = [people_set[i] for i in chosen]
            stored = build(scenario, people)
            shown = disclose(stored).model_dump()
            truth = withheld_numbers(stored, shown)
            truth.update({f"secret.{k}": v for k, v in secret(people).items()})
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
            legacy = scenario.get("legacy")
            if legacy and ".count." not in path and not path.startswith("secret."):
                continue
            values = {m.get(path) for m in members}
            if len(values) == 1 and small(next(iter(values))):
                raise AssertionError(
                    f"{path} is uniquely {values} in release {key[:600]}"
                )
            checked += 1
    return examined, checked


def test_the_fixture_holds_these_scenarios():
    """The stored SurveyJS results belong to the scenarios below (rerun
    solver-profiles.ts after a change; test-surveys-core checks the results
    against SurveyJS itself)."""
    assert FIXTURE["scenarios"] == json.loads(json.dumps(surveyjs_input()))


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_no_withheld_number_is_uniquely_determined(name):
    examined, checked = check(name)
    print(f"{name}: {examined} answer sets, {checked} withheld numbers checked")
    assert examined and checked


def test_a_number_never_releases_its_extremes():
    """R6: a number's minimum and maximum stay withheld for every answer set.
    The mean is an accepted residual (Björn Schotte, 2026-11-04): mean plus
    count can determine single answers near the range edges, so it is not
    checked for uniqueness."""
    for name in ("condition on a number", "two conditions on one number"):
        scenario = {**SCENARIOS[name], "mean": True}
        people_set = profiles(name)
        released = 0
        for size in range(1, 12):
            for chosen in combinations_with_replacement(range(len(people_set)), size):
                shown = disclosure.disclose(
                    build(scenario, [people_set[i] for i in chosen])
                )
                for q in shown.questions:
                    if q.kind == "number":
                        assert (q.minimum, q.maximum) == (None, None)
                        released += q.mean is not None
        assert released  # the mean is shown from k answers on


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
            check("single choice")
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
            check("compound and on two answers")
    finally:
        disclosure._classify = original
