"""Compare actual SurveyJS results to the Python candidate, without claiming full parity."""

import json
import sys
from pathlib import Path
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.surveys.validation import (
    validate_answers,
    validate_definition,
    condition,
)

fixtures = Path("tests/fixtures/surveys")
client_rows = json.loads(Path(sys.argv[1]).read_text())
client_results = {row["name"]: row for row in client_rows}
assert len(client_results) == len(client_rows), "Duplicate client result"
failures = []
cases = json.loads((fixtures / "validation-cases.json").read_text())
assert len({case["name"] for case in cases}) == len(cases), "Duplicate fixture name"
assert set(client_results) == {case["name"] for case in cases}, (
    "Missing or stale client results"
)
for case in cases:
    definition = case.get("definition") or json.loads(
        (fixtures / f"{case['fixture']}.json").read_text()
    )
    validate_definition(definition)
    try:
        validate_answers(definition, case["answers"], complete=True)
        valid = True
    except DomainInvariantError:
        valid = False
    if "expectedComplete" in case:
        assert valid == case["expectedComplete"], f"{case['name']}: expected completion"
    if valid != client_results[case["name"]]["completeValid"]:
        failures.append(
            f"{case['name']}: server={valid}, client={client_results[case['name']]['completeValid']}"
        )
    try:
        clean = validate_answers(definition, case["answers"], complete=False)
    except DomainInvariantError:
        # Invalid supplied values cannot enter persistence. Their visibility is
        # diagnostic only; valid states use the actual server-cleaned snapshot.
        clean = case["answers"]
    if "expectedAnswers" in case:
        assert clean == case["expectedAnswers"], f"{case['name']}: server cleanup"
        assert client_results[case["name"]]["answers"] == case["expectedAnswers"], (
            f"{case['name']}: client cleanup"
        )
    if "expectedVisible" in case:
        assert client_results[case["name"]]["visible"] == case["expectedVisible"], (
            f"{case['name']}: expected relevance"
        )
    visible, preceding = [], set()
    for page in definition["pages"]:
        page_visible = "visibleIf" not in page or condition(
            page["visibleIf"], clean, preceding
        )
        for question in page["elements"]:
            if page_visible and (
                "visibleIf" not in question
                or condition(question["visibleIf"], clean, preceding)
            ):
                visible.append(question["name"])
            preceding.add(question["name"])
    if visible != client_results[case["name"]]["visible"]:
        failures.append(
            f"{case['name']}: visibility server={visible}, client={client_results[case['name']]['visible']}"
        )
assert not failures, "\n".join(failures)
print(
    f"PASS: {len(client_results)} actual SurveyJS/Python validation and relevance comparisons"
)
