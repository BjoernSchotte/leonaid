from __future__ import annotations

import pytest

from leonaid.domain.actions import RESERVED_PUBLIC_ALIASES, PublicActionAlias
from leonaid.domain.errors import DomainInvariantError


@pytest.mark.parametrize("alias", sorted(RESERVED_PUBLIC_ALIASES))
def test_service_namespaces_cannot_be_claimed_as_campaign_aliases(alias: str) -> None:
    with pytest.raises(DomainInvariantError):
        PublicActionAlias(alias)


@pytest.mark.parametrize(
    "alias",
    [
        "https://example.org",
        "//example.org",
        "/krapfentaxi",
        "a/b",
        "a\\b",
        "a%2fb",
        "a%252fb",
        "a%5cb",
        ".",
        "..",
        "a?target=b",
        "a#b",
        "Krapfentaxi",
        " krapfentaxi ",
        "krapfentaxi\n",
        "",
    ],
)
def test_alias_value_requires_a_normalized_local_segment(alias: str) -> None:
    with pytest.raises(DomainInvariantError):
        PublicActionAlias(alias)


def test_campaign_names_remain_valid_outside_exact_reserved_roots() -> None:
    for alias in ("krapfentaxi", "krapfentaxi-2026", "campaigns-benefiz", "health-day"):
        assert PublicActionAlias(alias).value == alias
