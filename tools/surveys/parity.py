"""Compare actual SurveyJS results to the Python candidate, without claiming full parity."""

import json
import sys
from pathlib import Path
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.surveys.validation import validate_answers, condition

fixtures = Path("tests/fixtures/surveys")
client_results = {row["name"]: row for row in json.loads(Path(sys.argv[1]).read_text())}
failures = []
for case in json.loads((fixtures / "validation-cases.json").read_text()):
    definition = case.get("definition") or json.loads(
        (fixtures / f"{case['fixture']}.json").read_text()
    )
    try:
        validate_answers(definition, case["answers"], complete=True)
        valid = True
    except DomainInvariantError:
        valid = False
    if valid != client_results[case["name"]]["completeValid"]:
        failures.append(
            f"{case['name']}: server={valid}, client={client_results[case['name']]['completeValid']}"
        )
    visible, preceding = [], set()
    for page in definition["pages"]:
        page_visible = "visibleIf" not in page or condition(
            page["visibleIf"], case["answers"], preceding
        )
        for question in page["elements"]:
            if page_visible and (
                "visibleIf" not in question
                or condition(question["visibleIf"], case["answers"], preceding)
            ):
                visible.append(question["name"])
            preceding.add(question["name"])
    assert visible == client_results[case["name"]]["visible"], case["name"]
assert not failures, "\n".join(failures)
print(
    f"PASS: {len(client_results)} actual SurveyJS/Python validation and relevance comparisons"
)
