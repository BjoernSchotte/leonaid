from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from leonaid.application.dashboard import count_statuses, progress_basis_points

GOLDEN_ROOT = Path(__file__).parents[1] / "fixtures" / "golden" / "v1"


def golden_json(name: str) -> dict[str, object]:
    value = json.loads((GOLDEN_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_goal_progress_is_derived_from_golden_dataset() -> None:
    expected = golden_json("expected.json")
    totals = expected["activeActionTotals"]
    assert isinstance(totals, dict)

    actual = Decimal(int(totals["amountCents"])) / Decimal(100)
    target = Decimal(int(totals["goalAmountCents"])) / Decimal(100)

    assert progress_basis_points(actual, target) == int(
        totals["goalProgressBasisPoints"]
    )


def test_golden_assignment_pipeline_uses_closed_status_vocabulary() -> None:
    dataset = golden_json("dataset.json")
    assignments = dataset["assignments"]
    assert isinstance(assignments, list)

    counts = count_statuses(
        ("open" for _assignment in assignments),
        ("open", "contacted", "committed", "declined", "handed_over"),
    )

    assert counts == {
        "open": 5,
        "contacted": 0,
        "committed": 0,
        "declined": 0,
        "handed_over": 0,
    }


@pytest.mark.parametrize(
    ("actual", "target", "expected"),
    (
        ("0", None, None),
        ("10", "0", None),
        ("90", "100", 9000),
        ("125", "100", 12500),
        ("1", "3", 3333),
    ),
)
def test_goal_progress_handles_partial_and_overachieved_actions(
    actual: str,
    target: str | None,
    expected: int | None,
) -> None:
    assert (
        progress_basis_points(
            Decimal(actual),
            Decimal(target) if target is not None else None,
        )
        == expected
    )


def test_unknown_pipeline_status_fails_loudly() -> None:
    with pytest.raises(ValueError, match="Unbekannter Status"):
        count_statuses(("open", "legacy"), ("open", "contacted"))
