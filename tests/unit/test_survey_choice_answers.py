"""fields=choice: option labels only, never free text."""

from leonaid.modules.surveys.adapters.postgres.survey_responses import choice_answers

LABELS = {
    "role": {
        "matrix": False,
        "choices": {'"pack"': "Packen", '"drive"': "Fahrdienst"},
        "rows": {},
    },
    "multi": {
        "matrix": False,
        "choices": {'"a"': "Alpha", '"b"': "Beta"},
        "rows": {},
    },
    "rating": {"matrix": False, "choices": {"4": "4", "5": "5"}, "rows": {}},
    "grid": {
        "matrix": True,
        "choices": {'"good"': "Gut", '"bad"': "Verbesserungsbedarf"},
        "rows": {"r1": "Organisation", "r2": "Verpflegung"},
    },
}


def test_labels_of_defined_options_only():
    answers = {
        "role": "drive",
        "multi": ["b", "other", "a"],
        "rating": 5,
        "grid": {"r1": "good", "r2": "<script>", "r3": "good"},
        "text": "Freitext darf nie erscheinen",
        "role-Comment": "Sonstiges: Freitext",
    }
    assert choice_answers(answers, LABELS) == {
        "role": ["Fahrdienst"],
        "multi": ["Beta", "Alpha"],
        "rating": ["5"],
        "grid": ["Organisation: Gut"],
    }


def test_free_text_in_place_of_an_option_is_dropped():
    answers = {"role": "Ich war beim Packen und beim Fahren", "multi": "a b"}
    assert choice_answers(answers, LABELS) == {}
