from __future__ import annotations

import pytest

from leonaid.domain.document_series import (
    DocumentSeries,
    DocumentSeriesKind,
    format_document_number,
    series_of_number,
)
from leonaid.domain.errors import DomainInvariantError


def series(**changes: object) -> DocumentSeries:
    values: dict[str, object] = {
        "kind": DocumentSeriesKind.INVOICE,
        "prefix": "KT26-",
        "next_number": 42,
        "width": 4,
    }
    values.update(changes)
    return DocumentSeries(**values)  # type: ignore[arg-type]


def test_next_number_is_prefix_and_padded_serial() -> None:
    assert series().next_document_number == "KT26-0042"
    # A serial wider than the width is not cut.
    assert format_document_number("KT26-", 12_345, 4) == "KT26-12345"


def test_advancing_moves_one_step_and_keeps_the_series() -> None:
    advanced = series().advanced()

    assert advanced.next_number == 43
    assert (advanced.kind, advanced.prefix, advanced.width) == (
        DocumentSeriesKind.INVOICE,
        "KT26-",
        4,
    )


def test_every_document_kind_of_the_bundle_has_a_series() -> None:
    # Cancellation invoices share the invoice series (ADR-0015, D-C1).
    assert {kind.value for kind in DocumentSeriesKind} == {
        "invoice",
        "donation",
        "donation_receipt",
    }


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"prefix": "kt26-"}, "document_series_prefix_invalid"),
        ({"prefix": ""}, "document_series_prefix_invalid"),
        ({"next_number": 0}, "document_series_sequence_invalid"),
        ({"next_number": True}, "document_series_sequence_invalid"),
        ({"width": 2}, "document_series_sequence_invalid"),
        ({"width": 9}, "document_series_sequence_invalid"),
    ],
)
def test_invalid_series_is_rejected(changes: dict[str, object], code: str) -> None:
    with pytest.raises(DomainInvariantError) as error:
        series(**changes)

    assert error.value.code == code


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("KT26-0017", ("KT26-", 4)),
        # The width stays inside the allowed range.
        ("RE-7", ("RE-", 3)),
        ("RE-123456789", ("RE-", 8)),
        # No serial at the end: a series of its own, so a cancellation
        # invoice can always be numbered.
        ("OC1234ABCD-PUBLIC-INVOICED", ("OC1234ABCD-PUBLIC-INVOI-", 3)),
        ("2026", ("2026-", 3)),
    ],
)
def test_series_of_a_document_number(number: str, expected: tuple[str, int]) -> None:
    assert series_of_number(number) == expected
