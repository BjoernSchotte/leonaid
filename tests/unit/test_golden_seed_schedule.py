import json
from datetime import date, datetime
from pathlib import Path

import pytest

from tools.seed.golden import action_schedule, offer_window

DATASET = json.loads(
    Path("tests/fixtures/golden/v1/dataset.json").read_text(encoding="utf-8")
)
ACTIONS = {action["id"]: action for action in DATASET["actions"]}


@pytest.mark.parametrize(
    "today", [date(2026, 11, 9), date(2026, 11, 20), date(2027, 6, 1)]
)
def test_active_action_offers_stay_orderable_on_any_seed_day(today: date) -> None:
    for offer in DATASET["offers"]:
        action = ACTIONS[offer["actionId"]]
        assert action["status"] == "ACTIVE"
        available_from, available_until = offer_window(offer, action, today=today)
        moment = datetime.combine(today, datetime.min.time(), available_from.tzinfo)
        _, _, publication_starts_at, publication_ends_at = action_schedule(
            action, today=today
        )
        assert available_from <= moment < available_until
        assert (available_from, available_until) == (
            publication_starts_at,
            publication_ends_at,
        )


def test_offer_window_keeps_dataset_values_for_inactive_actions() -> None:
    action = {**next(iter(ACTIONS.values())), "status": "ARCHIVED"}
    offer = DATASET["offers"][0]
    assert offer_window(offer, action, today=date(2030, 1, 1)) == (
        datetime.fromisoformat(offer["availableFrom"]),
        datetime.fromisoformat(offer["availableUntil"]),
    )
