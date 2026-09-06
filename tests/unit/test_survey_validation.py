import copy
import json
from pathlib import Path

import pytest

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.surveys.validation import validate_answers, validate_definition

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "surveys"


def fixture(name="krapfentaxi"):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_partial_and_complete_differ_and_hidden_answers_are_removed():
    definition = fixture()
    assert validate_answers(definition, {}, complete=False) == {}
    with pytest.raises(DomainInvariantError):
        validate_answers(definition, {}, complete=True)
    assert validate_answers(
        definition,
        {"delivery_rating": 5, "delivery_feedback": "obsolete"},
        complete=False,
    ) == {"delivery_rating": 5}


@pytest.mark.parametrize(
    "answers",
    [
        {"delivery_rating": True},
        {"delivery_rating": 1.5},
        {"freshness": {}},
        {"unknown": 1},
        {"nps": float("nan")},
    ],
)
def test_forged_values_are_rejected(answers):
    with pytest.raises(DomainInvariantError):
        validate_answers(fixture(), answers, complete=False)


@pytest.mark.parametrize(
    "patch",
    [
        {"type": []},
        {"maxLength": "lots"},
        {"visibleIf": "__import__('os')"},
        {"visibleIf": "(" * 100 + "{freshness} = 1" + ")" * 100},
        {"choices": [{"value": "x", "text": {"html": "bad"}}], "type": "dropdown"},
    ],
)
def test_malformed_definitions_fail_closed(patch):
    definition = copy.deepcopy(fixture())
    definition["pages"][0]["elements"][0].update(patch)
    with pytest.raises(DomainInvariantError):
        validate_definition(definition)


def test_matrix_and_multiselect_cannot_smuggle_types():
    definition = fixture("golf")
    for answers in [
        {"event_rating": {"organization": True}},
        {"improvements": ["food", "food"]},
        {"event_rating": {"unknown": 1}},
    ]:
        with pytest.raises(DomainInvariantError):
            validate_answers(definition, answers, complete=False)


def test_empty_multiselect_with_minimum_is_partial_only():
    definition = {
        "pages": [
            {
                "name": "page",
                "elements": [
                    {
                        "type": "checkbox",
                        "name": "choices",
                        "choices": ["a", "b"],
                        "minSelectedChoices": 2,
                    }
                ],
            }
        ]
    }
    assert validate_answers(definition, {"choices": []}, complete=False) == {}
    with pytest.raises(DomainInvariantError):
        validate_answers(definition, {"choices": []}, complete=True)
