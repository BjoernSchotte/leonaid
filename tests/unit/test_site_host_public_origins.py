"""Active campaign hosts as public origins (specs/multi-domain §6.3, D7)."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from leonaid.adapters.postgres.site_directory import (
    AsyncpgSiteDirectory,
    SiteHostPublicOrigins,
)


class Directory:
    def __init__(self) -> None:
        self.lookups: list[str] = []

    async def is_active(self, hostname: str) -> bool:
        self.lookups.append(hostname)
        return hostname == "lionsopen.de"


def origins(*, production: bool) -> tuple[SiteHostPublicOrigins, Directory]:
    directory = Directory()
    return (
        SiteHostPublicOrigins(
            ("https://example.org",),
            cast(AsyncpgSiteDirectory, cast(Any, directory)),
            production=production,
        ),
        directory,
    )


def allows(target: SiteHostPublicOrigins, origin: str) -> bool:
    return asyncio.run(target.allows(origin, origin.split("://", 1)[1]))


def test_production_accepts_only_the_default_port() -> None:
    target, _ = origins(production=True)
    assert allows(target, "https://lionsopen.de")
    assert allows(target, "https://lionsopen.de:443")
    assert not allows(target, "https://lionsopen.de:8443")
    assert not allows(target, "http://lionsopen.de")


def test_development_accepts_other_ports() -> None:
    target, _ = origins(production=False)
    assert allows(target, "https://lionsopen.de:8443")
    assert not allows(target, "https://other.de:8443")


def test_lookups_are_cached() -> None:
    target, directory = origins(production=True)
    for _ in range(5):
        allows(target, "https://other.de")
    assert directory.lookups == ["other.de"]
    assert allows(target, "https://example.org")
