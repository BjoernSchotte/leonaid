"""Geocoding rules: address hash, acceptance, retry and pending (spec §8.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from leonaid.domain.delivery_geo import (
    MIN_IMPORTANCE,
    Failed,
    Found,
    GeocodeQuery,
    GeoOutcome,
    GeoPoint,
    NotFound,
    StoredGeo,
    accept,
    address_hash,
    is_pending,
    retry_due,
)
from leonaid.domain.errors import DomainInvariantError

NOW = datetime(2026, 12, 5, 12, tzinfo=UTC)
QUERY = GeocodeQuery("Marienplatz 1", "80331", "München", "DE")


def test_address_hash_ignores_case_and_spacing_only() -> None:
    same = GeocodeQuery("  marienplatz   1 ", "80331", "MÜNCHEN", "de")
    assert address_hash(same) == address_hash(QUERY)
    assert len(address_hash(QUERY)) == 64
    for changed in (
        GeocodeQuery("Marienplatz 2", "80331", "München", "DE"),
        GeocodeQuery("Marienplatz 1", "80333", "München", "DE"),
        GeocodeQuery("Marienplatz 1", "80331", "Muenchen", "DE"),
        GeocodeQuery("Marienplatz 1", "80331", "München", "AT"),
        # Fields cannot shift into each other.
        GeocodeQuery("Marienplatz", "1 80331", "München", "DE"),
    ):
        assert address_hash(changed) != address_hash(QUERY)


def test_accept_requires_matching_postcode_and_importance() -> None:
    assert MIN_IMPORTANCE == 0.05
    assert accept("80331", 0.05, QUERY)
    assert accept(" 80331 ", 0.4, QUERY)
    assert not accept("80333", 0.9, QUERY)
    assert not accept(None, 0.9, QUERY)
    assert not accept("80331", 0.049, QUERY)
    assert not accept("80331", None, QUERY)


def test_retry_due_only_for_failed_under_three_attempts() -> None:
    old = NOW - timedelta(hours=1)
    fresh = NOW - timedelta(minutes=59)
    assert retry_due(GeoOutcome.FAILED, 1, old, NOW)
    assert retry_due(GeoOutcome.FAILED, 2, old, NOW)
    assert not retry_due(GeoOutcome.FAILED, 3, old, NOW)
    assert not retry_due(GeoOutcome.FAILED, 1, fresh, NOW)
    assert not retry_due(GeoOutcome.NOT_FOUND, 1, NOW - timedelta(days=30), NOW)
    assert not retry_due(GeoOutcome.FOUND, 1, NOW - timedelta(days=30), NOW)


def test_pending_on_new_changed_or_retry_due_rows() -> None:
    current = address_hash(QUERY)

    def stored(outcome: GeoOutcome, digest: str = current, **kw: object) -> StoredGeo:
        values: dict[str, object] = {
            "outcome": outcome,
            "address_hash": digest,
            "attempts": 1,
            "geocoded_at": NOW,
            "manual": False,
        }
        values.update(kw)
        return StoredGeo(**values)  # type: ignore[arg-type]

    assert is_pending(None, current, NOW)
    assert not is_pending(stored(GeoOutcome.FOUND), current, NOW)
    assert not is_pending(stored(GeoOutcome.NOT_FOUND), current, NOW)
    assert is_pending(stored(GeoOutcome.NOT_FOUND, "0" * 64), current, NOW)
    # A manual pin survives only while the address hash matches.
    assert not is_pending(stored(GeoOutcome.FOUND, manual=True), current, NOW)
    assert is_pending(stored(GeoOutcome.FOUND, "0" * 64, manual=True), current, NOW)
    assert is_pending(
        stored(GeoOutcome.FAILED, geocoded_at=NOW - timedelta(hours=2)),
        current,
        NOW,
    )


def test_geo_point_is_validated_and_quantised() -> None:
    point = GeoPoint(Decimal("48.13715049"), Decimal("11.5754"))
    assert point.lat == Decimal("48.137150")
    assert point.lon == Decimal("11.575400")
    assert GeoPoint.parse("-90", "180") == GeoPoint(Decimal(-90), Decimal(180))
    for lat, lon in (("90.1", "0"), ("0", "-180.5"), ("nan", "0"), ("x", "1")):
        with pytest.raises(DomainInvariantError):
            GeoPoint.parse(lat, lon)


def test_outcomes_name_their_stored_value() -> None:
    point = GeoPoint(Decimal(1), Decimal(2))
    assert Found(point, 0.5).outcome is GeoOutcome.FOUND
    assert NotFound().outcome is GeoOutcome.NOT_FOUND
    assert Failed("timeout").outcome is GeoOutcome.FAILED
    with pytest.raises(DomainInvariantError):
        Failed("Marienplatz 1 failed")
