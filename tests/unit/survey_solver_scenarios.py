"""Scenarios for the disclosure solver, as real SurveyJS definitions.

Each scenario is a survey definition plus the answer profiles one person
can give. SurveyJS itself (the runner's survey-core) decides, per profile,
which questions and pages are visible, which answers survive hidden-value
clearing, the counts ``aggregateApprovedSurvey`` records and the last page
a completed person ends on. ``tools/surveys/solver-profiles.ts`` runs it
once per profile and stores the results in
``tests/fixtures/surveys/solver-profiles.json``; the solver sums them per
candidate group. Aggregation is additive per person, so this equals
running SurveyJS on every candidate.

Regenerate after changing a scenario (in the locked toolchains):

    uv run python tests/unit/survey_solver_scenarios.py \\
        > .artifacts/surveys/solver-scenarios.json
    bun tools/surveys/solver-profiles.ts write \\
        .artifacts/surveys/solver-scenarios.json \\
        tests/fixtures/surveys/solver-profiles.json

``test-surveys-core`` checks the stored results against SurveyJS
(``solver-profiles.ts check``); the solver test checks that the fixture
holds exactly these scenarios.
"""

import json
from itertools import combinations, product
from typing import Any

YES_NO = ["yes", "no"]
CHECKS = ["A", "B", "C"]


def radio(name: str, choices: list[Any], visible: str | None = None) -> dict:
    element: dict[str, Any] = {"type": "radiogroup", "name": name, "choices": choices}
    if visible:
        element["visibleIf"] = visible
    return element


def checkbox(name: str, choices: list[Any], **limits: int) -> dict:
    return {"type": "checkbox", "name": name, "choices": choices, **limits}


def rating(name: str, low: int, high: int, visible: str | None = None) -> dict:
    element: dict[str, Any] = {
        "type": "rating",
        "name": name,
        "rateMin": low,
        "rateMax": high,
        "rateStep": 1,
    }
    if visible:
        element["visibleIf"] = visible
    return element


def number(name: str) -> dict:
    return {"type": "text", "name": name, "inputType": "number"}


def text(name: str) -> dict:
    return {"type": "text", "name": name}


def matrix(name: str, rows: list[str], columns: list[str]) -> dict:
    return {"type": "matrix", "name": name, "rows": rows, "columns": columns}


def page(name: str, *elements: dict, visible: str | None = None) -> dict:
    result: dict[str, Any] = {"name": name, "elements": list(elements)}
    if visible:
        result["visibleIf"] = visible
    return result


def survey(*pages: dict) -> dict:
    return {"pages": list(pages)}


def profiles(**options: list[Any]) -> list[dict[str, Any]]:
    """Every combination; None leaves the question unanswered."""
    names = list(options)
    return [
        {
            name: value
            for name, value in zip(names, values, strict=True)
            if value is not None
        }
        for values in product(*(options[name] for name in names))
    ]


def subsets(options: list[str], low: int, high: int) -> list[list[str]]:
    return [
        list(combo)
        for size in range(low, high + 1)
        for combo in combinations(options, size)
    ]


def gated(condition: str) -> dict[str, Any]:
    return {
        "definition": survey(
            page(
                "main",
                radio("g1", YES_NO),
                radio("g2", YES_NO),
                radio("f", ["a"], condition),
            )
        ),
        "profiles": profiles(g1=YES_NO, g2=YES_NO, f=["a"]),
        "sizes": [1, 15],
        "secrets": ["joint", "g1", "g2"],
    }


def ticked(condition: str) -> dict[str, Any]:
    return {
        "definition": survey(
            page("main", checkbox("c", CHECKS), radio("f", ["a"], condition))
        ),
        "profiles": profiles(c=subsets(CHECKS, 1, 3), f=["a"]),
        "sizes": [1, 11],
        "secrets": ["co", "c", CHECKS],
    }


def on_number(condition: str) -> dict[str, Any]:
    """An optional number and one question selected by it (N8)."""
    return {
        "definition": survey(page("main", number("n"), radio("f", ["a"], condition))),
        # The reviewer's values: two answers and "unanswered".
        "profiles": profiles(n=[5, 15, None], f=["a"]),
        "sizes": [1, 19],
        "secrets": ["exact", "n", [5, 15]],
        "mean": False,
    }


SCENARIOS: dict[str, dict[str, Any]] = {
    "single choice": {
        "definition": survey(page("main", radio("q", ["a", "b", "c"]))),
        "profiles": profiles(q=["a", "b", "c", None]),
        "sizes": [1, 14],
    },
    "single choice, sizes 20 to 26": {
        "definition": survey(page("main", radio("q", ["a", "b", "c"]))),
        "profiles": profiles(q=["a", "b", "c", None]),
        "sizes": [20, 26],
    },
    "rating 1-5": {
        "definition": survey(page("main", rating("r", 1, 5))),
        "profiles": profiles(r=[1, 2, 3, 4, 5, None]),
        "sizes": [1, 11],
    },
    "nps 0-10, sizes to 7": {
        "definition": survey(page("main", rating("n", 0, 10))),
        "profiles": profiles(n=[*range(11), None]),
        "sizes": [1, 7],
    },
    "nps 0-10, four scores used, sizes to 26": {
        "definition": survey(page("main", rating("n", 0, 10))),
        "profiles": profiles(n=[0, 7, 9, 10]),
        "sizes": [1, 26],
    },
    "matrix 2x2": {
        "definition": survey(page("main", matrix("m", ["r1", "r2"], ["g", "b"]))),
        "profiles": [
            {"m": {"r1": x, "r2": y}} for x, y in product(["g", "b"], repeat=2)
        ],
        "sizes": [1, 12],
    },
    "matrix with one column": {
        "definition": survey(page("main", matrix("m", ["r1", "r2"], ["x"]))),
        "profiles": [
            {"m": {"r1": "x", "r2": "x"}},
            {"m": {"r1": "x"}},
            {"m": {"r2": "x"}},
            {},
        ],
        "sizes": [1, 12],
    },
    "conditional": {
        "definition": survey(
            page(
                "main",
                radio("gate", YES_NO),
                radio("follow", ["a", "b"], "{gate} = 'yes'"),
            )
        ),
        "profiles": profiles(gate=[*YES_NO, None], follow=["a", "b", None]),
        "sizes": [1, 15],
    },
    "conditional page": {
        "definition": survey(
            page("main", radio("gate", YES_NO)),
            page("p2", radio("follow", ["a", "b"]), visible="{gate} = 'yes'"),
        ),
        "profiles": profiles(gate=YES_NO, follow=["a", "b"]),
        "sizes": [1, 15],
    },
    "compound and on two answers": gated("{g1} = 'yes' and {g2} = 'yes'"),
    "compound or on two answers": gated("{g1} = 'yes' or {g2} = 'yes'"),
    "two pages on two answers": {
        "definition": survey(
            page("main", radio("g1", YES_NO), radio("g2", YES_NO)),
            page("p2", text("t2"), visible="{g1} = 'yes'"),
            page("p3", text("t3"), visible="{g2} = 'yes'"),
        ),
        "profiles": profiles(g1=YES_NO, g2=YES_NO),
        "sizes": [1, 15],
        "secrets": ["joint", "g1", "g2"],
    },
    "checkbox contains A and contains B": ticked(
        "{c} contains 'A' and {c} contains 'B'"
    ),
    "checkbox contains A or contains B": ticked("{c} contains 'A' or {c} contains 'B'"),
    "checkbox, no maximum": {
        "definition": survey(page("main", checkbox("c", CHECKS))),
        "profiles": profiles(c=[*subsets(CHECKS, 1, 3), None]),
        "sizes": [1, 11],
        "secrets": ["co", "c", CHECKS],
    },
    "checkbox, maxSelectedChoices 1": {
        "definition": survey(page("main", checkbox("c", CHECKS, maxSelectedChoices=1))),
        "profiles": profiles(c=[*subsets(CHECKS, 1, 1), None]),
        "sizes": [1, 14],
    },
    "checkbox, at most 2": {
        "definition": survey(page("main", checkbox("c", CHECKS, maxSelectedChoices=2))),
        "profiles": profiles(c=[*subsets(CHECKS, 1, 2), None]),
        "sizes": [1, 13],
        "secrets": ["co", "c", CHECKS],
    },
    "checkbox, exactly 2": {
        "definition": survey(
            page(
                "main",
                checkbox("c", CHECKS, minSelectedChoices=2, maxSelectedChoices=2),
            )
        ),
        "profiles": profiles(c=[*subsets(CHECKS, 2, 2), None]),
        "sizes": [1, 14],
    },
    "two conditions on one released answer": {
        "definition": survey(
            page(
                "main",
                radio("g", ["a", "b", "c"]),
                radio("f1", ["x"], "{g} = 'a'"),
                radio("f2", ["x"], "{g} != 'b'"),
            )
        ),
        "profiles": profiles(g=["a", "b", "c", None], f1=["x", None], f2=["x", None]),
        "sizes": [1, 10],
    },
    "two conditions on one number": {
        "definition": survey(
            page(
                "main",
                number("h"),
                radio("f1", ["a"], "{h} >= 10"),
                radio("f2", ["a"], "{h} >= 11"),
            )
        ),
        "profiles": profiles(h=[5, 10, 15, None], f1=["a"], f2=["a"]),
        "sizes": [1, 19],
        "secrets": ["exact", "h", [5, 10, 15]],
        "mean": False,
    },
    "condition on a number": {
        "definition": survey(
            page("main", number("hours"), radio("follow", ["a"], "{hours} = 15"))
        ),
        "profiles": profiles(hours=[5, 15, None], follow=["a", None]),
        "sizes": [1, 15],
        "secrets": ["exact", "hours", [5, 15]],
        "mean": False,
    },
    "conditional rating": {
        "definition": survey(
            page(
                "main",
                radio("gate", YES_NO),
                rating("score", 1, 3, "{gate} = 'yes'"),
            )
        ),
        "profiles": profiles(gate=[*YES_NO, None], score=[1, 2, 3]),
        "sizes": [1, 12],
    },
    "conditional rating (legacy snapshot)": {
        "definition": survey(
            page(
                "main",
                radio("gate", YES_NO),
                rating("score", 1, 3, "{gate} = 'yes'"),
            )
        ),
        "profiles": profiles(gate=[*YES_NO, None], score=[1, 2, 3]),
        "sizes": [1, 12],
        "legacy": True,
    },
    "compound and (legacy snapshot)": {
        **gated("{g1} = 'yes' and {g2} = 'yes'"),
        "legacy": True,
    },
    # The reviewer's probes (re-review 2).
    "probe N7a: last pages through empty pages (cross-tab)": {
        "definition": survey(
            page("main", radio("g1", YES_NO), radio("g2", YES_NO)),
            page("p2", radio("f1", ["a"], "{g1} = 'yes'")),
            page("p3", radio("f2", ["a"], "{g2} = 'yes'")),
        ),
        "profiles": profiles(g1=YES_NO, g2=YES_NO, f1=["a"], f2=["a"]),
        "sizes": [1, 15],
        "secrets": ["joint", "g1", "g2"],
    },
    "probe N7b: a page holding one conditional question": {
        "definition": survey(
            page("main", number("n")),
            page("p2", radio("f", ["a"], "{n} >= 10")),
        ),
        "profiles": profiles(n=[5, 10, 15, None], f=["a"]),
        "sizes": [1, 19],
        "secrets": ["exact", "n", [5, 10, 15]],
        "mean": False,
    },
    "probe N8: optional number, >=": on_number("{n} >= 10"),
    "probe N8: optional number, !=": on_number("{n} != 5"),
    "probe N8: optional number, <": on_number("{n} < 10"),
    "probe N9: pages on one checkbox": {
        "definition": survey(
            page("main", checkbox("c", CHECKS)),
            page("p2", text("t2"), visible="{c} contains 'A'"),
            page("p3", text("t3"), visible="{c} contains 'B'"),
        ),
        "profiles": profiles(c=subsets(CHECKS, 1, 3)),
        "sizes": [1, 11],
        "secrets": ["co", "c", CHECKS],
    },
    "probe N10: options equal under SurveyJS comparison": {
        "definition": survey(
            page(
                "main",
                checkbox("c", ["a", "A", "b"]),
                radio("f", ["x"], "{c} contains 'a'"),
            )
        ),
        "profiles": profiles(c=subsets(["a", "A", "b"], 1, 3), f=["x"]),
        "sizes": [1, 11],
        "secrets": ["co", "c", ["a", "A", "b"]],
    },
    "probe N11: options equal under JavaScript number conversion": {
        "definition": survey(
            page(
                "main",
                checkbox("c", ["0x10", "16", "x"]),
                radio("f", ["y"], "{c} contains 16"),
            )
        ),
        "profiles": profiles(c=subsets(["0x10", "16", "x"], 1, 3), f=["y"]),
        "sizes": [1, 11],
        "secrets": ["co", "c", ["0x10", "16", "x"]],
    },
    'probe N14: a boolean literal equals 1 and "true"': {
        "definition": survey(
            page(
                "main",
                checkbox("c", [1, "true", "x"]),
                radio("f", ["y"], "{c} contains true"),
            )
        ),
        "profiles": profiles(c=subsets([1, "true", "x"], 1, 3), f=["y"]),
        "sizes": [1, 11],
        "secrets": ["co", "c", [1, "true", "x"]],
    },
}


def surveyjs_input() -> dict[str, Any]:
    """What solver-profiles.ts evaluates: definitions and profiles only."""
    return {
        name: {"definition": s["definition"], "profiles": s["profiles"]}
        for name, s in SCENARIOS.items()
    }


if __name__ == "__main__":
    print(json.dumps(surveyjs_input(), indent=1, sort_keys=True))
