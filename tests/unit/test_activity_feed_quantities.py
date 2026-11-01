from __future__ import annotations

import pytest

from leonaid.application.activity_feed import ActivityFeedService
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import UnitQuantity


def test_feed_reads_per_unit_quantities() -> None:
    assert ActivityFeedService._payload_quantities(
        {
            "totalBoxes": 0,
            "quantities": [
                {"unit": "piece", "quantity": 4},
                {"unit": "package", "quantity": 1},
            ],
        }
    ) == (
        UnitQuantity(OfferingUnit.PIECE, 4),
        UnitQuantity(OfferingUnit.PACKAGE, 1),
    )


def test_feed_derives_quantities_from_legacy_box_events() -> None:
    assert ActivityFeedService._payload_quantities({"totalBoxes": 3}) == (
        UnitQuantity(OfferingUnit.BOX, 3),
    )
    assert ActivityFeedService._payload_quantities({"totalBoxes": 0}) == ()


def test_feed_rejects_unknown_units() -> None:
    with pytest.raises(RuntimeError):
        ActivityFeedService._payload_quantities(
            {"quantities": [{"unit": "tree", "quantity": 1}]}
        )
