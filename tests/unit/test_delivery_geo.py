"""Geocoding rules: address hash, acceptance, retry and pending (spec §8.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from leonaid.domain.delivery_geo import (
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
    query_house_number,
    retry_due,
    start_geocode_query,
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


def test_accept_takes_an_exact_house_hit_regardless_of_importance() -> None:
    # Nominatim's importance of an exact hit is about 6e-5; it is not looked at.
    assert accept("80331", "1", 30, QUERY)
    assert accept(" 80331 ", " 1 ", 30, QUERY)
    # A house number alone, or a rank alone (street query without number), is enough.
    assert accept("80331", "1", None, QUERY)
    street = GeocodeQuery("Marienplatz", "80331", "München", "DE")
    assert accept("80331", None, 26, street)


def test_accept_rejects_other_postcode_or_missing_postcode() -> None:
    assert not accept("80333", "1", 30, QUERY)
    assert not accept(None, "1", 30, QUERY)


def test_accept_rejects_other_house_number() -> None:
    assert not accept("80331", "2", 30, QUERY)
    assert not accept("80331", "11", 30, QUERY)
    assert not accept("80331", "1a", 30, QUERY)


def test_accept_rejects_street_level_hit_when_query_has_a_number() -> None:
    assert not accept("80331", None, 26, QUERY)
    assert not accept("80331", "", 22, QUERY)


def test_accept_rejects_coarse_hit_without_house_number() -> None:
    street = GeocodeQuery("Marienplatz", "80331", "München", "DE")
    assert not accept("80331", None, 25, street)
    assert not accept("80331", None, None, street)


def test_accept_house_number_ignores_case_and_spacing() -> None:
    query = GeocodeQuery("Ludwigstraße 25a", "83646", "Bad Tölz", "DE")
    assert accept("83646", "25 a", 30, query)
    assert accept("83646", "25A", 30, query)
    spaced = GeocodeQuery("Ludwigstraße 25 A", "83646", "Bad Tölz", "DE")
    assert accept("83646", "25a", 30, spaced)
    assert not accept("83646", "25", 30, query)
    assert not accept("83646", "25b", 30, query)


def test_accept_house_number_ranges_and_lists() -> None:
    query = GeocodeQuery("Hauptstraße 5-7", "83646", "Bad Tölz", "DE")
    assert accept("83646", "5-7", 30, query)
    assert accept("83646", "5-7;9", 30, query)
    assert not accept("83646", "5", 30, query)
    single = GeocodeQuery("Hauptstraße 5", "83646", "Bad Tölz", "DE")
    assert accept("83646", "5;7", 30, single)


def test_query_house_number_only_from_the_end_of_the_street_line() -> None:
    assert query_house_number(QUERY) == "1"
    assert query_house_number(GeocodeQuery("Straße 17. Juni", "1", "x", "DE")) is None
    assert (
        query_house_number(GeocodeQuery("Straße des 17. Juni 5", "1", "x", "DE")) == "5"
    )
    assert query_house_number(GeocodeQuery("Am Hang 12 a", "1", "x", "DE")) == "12a"


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
    assert Found(point).outcome is GeoOutcome.FOUND
    assert NotFound().outcome is GeoOutcome.NOT_FOUND
    assert Failed("timeout").outcome is GeoOutcome.FAILED
    with pytest.raises(DomainInvariantError):
        Failed("Marienplatz 1 failed")


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        (
            "Marktstraße 50, 83646 Bad Tölz",
            GeocodeQuery("Marktstraße 50", "83646", "Bad Tölz", "DE"),
        ),
        (
            "  Marktstraße 50 ,83646   Bad Tölz ",
            GeocodeQuery("Marktstraße 50", "83646", "Bad Tölz", "DE"),
        ),
        (
            "Getreidegasse 9, 5020 Salzburg, AT",
            GeocodeQuery("Getreidegasse 9", "5020", "Salzburg", "AT"),
        ),
        ("Marktstraße 50 Bad Tölz", None),
        ("Marktstraße 50, Bad Tölz", None),
        ("Marktstraße 50, 83646", None),
    ],
)
def test_start_address_is_parsed_into_a_structured_query(
    address: str, expected: GeocodeQuery | None
) -> None:
    assert start_geocode_query(address) == expected
