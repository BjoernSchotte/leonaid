"""Platform identity as a framework-independent domain value."""

from __future__ import annotations

import re
from dataclasses import dataclass

from leonaid.domain.errors import DomainInvariantError

SEMVER = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
API_VERSION = re.compile(r"v[1-9][0-9]*\Z")
SERVICE_NAME = re.compile(r"[a-z][a-z0-9-]{2,62}\Z")


@dataclass(frozen=True, slots=True)
class PlatformIdentity:
    service: str
    release: str
    api_version: str

    def __post_init__(self) -> None:
        if SERVICE_NAME.fullmatch(self.service) is None:
            raise DomainInvariantError(
                "service_name_invalid",
                "Der technische Dienstname ist ungültig.",
            )
        if SEMVER.fullmatch(self.release) is None:
            raise DomainInvariantError(
                "release_version_invalid",
                "Die Release-Version muss SemVer entsprechen.",
            )
        if API_VERSION.fullmatch(self.api_version) is None:
            raise DomainInvariantError(
                "api_version_invalid",
                "Die API-Version muss dem Format vN entsprechen.",
            )
