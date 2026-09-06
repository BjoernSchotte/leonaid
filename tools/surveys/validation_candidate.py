"""Prepare host-approved fixtures and assess the isolated JS candidate honestly."""

import json
import sys
from pathlib import Path

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.surveys.validation import validate_answers, validate_definition

root = Path("tests/fixtures/surveys")
artifacts = Path(".artifacts/surveys")
inputs = artifacts / "candidate-input.json"
outputs = artifacts / "candidate-output.json"


def prepare() -> None:
    cases = json.loads((root / "validation-cases.json").read_text())
    for case in cases:
        case["definition"] = case.get("definition") or json.loads(
            (root / f"{case['fixture']}.json").read_text()
        )
    cases += json.loads((root / "condition-candidate-cases.json").read_text())
    for case in cases:
        validate_definition(case["definition"])
    assert len({case["name"] for case in cases}) == len(cases)
    artifacts.mkdir(parents=True, exist_ok=True)
    inputs.write_text(json.dumps(cases))
    print(f"Prepared {len(cases)} definitions approved by the real host validator")


def verify() -> None:
    cases = json.loads(inputs.read_text())
    rows = json.loads(outputs.read_text())
    results = {row["name"]: row for row in rows}
    assert len(results) == len(rows) == len(cases)
    assert set(results) == {case["name"] for case in cases}
    differences = []
    for case in cases:
        result = results[case["name"]]
        for key, field in [
            ("expectedComplete", "completeValid"),
            ("expectedVisible", "visible"),
            ("expectedAnswers", "answers"),
            ("expectedPartial", "partialValid"),
        ]:
            if key in case:
                assert result[field] == case[key], (case["name"], field, result[field])
        observed_modes = []
        for complete, field in [(False, "partialValid"), (True, "completeValid")]:
            try:
                clean = validate_answers(
                    case["definition"], case["answers"], complete=complete
                )
                valid = True
            except DomainInvariantError:
                clean, valid = None, False
            if valid != result[field] or valid and clean != result["answers"]:
                differences.append(
                    {
                        "case": case["name"],
                        "mode": field,
                        "pythonValid": valid,
                        "candidateValid": result[field],
                        "snapshotDifference": valid and clean != result["answers"],
                    }
                )
                observed_modes.append(field)
        assert observed_modes == case.get("expectedPythonDifferences", []), (
            case["name"],
            observed_modes,
        )
    assert differences, "Expected current Python relevance defects to remain observable"
    (artifacts / "candidate-comparison.json").write_text(
        json.dumps(differences, indent=2)
    )
    print(
        f"PASS: {len(cases)} candidate cases; {len(differences)} explicitly recorded Python mode/snapshot differences"
    )
    print(
        "This comparison alone does not prove production integration; see the live runner gate"
    )


if sys.argv[1] == "prepare":
    prepare()
elif sys.argv[1] == "verify":
    verify()
else:
    raise SystemExit("Expected prepare or verify")
