"""Platform use cases and ports."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from leonaid.domain.platform import PlatformIdentity

ProbeValue = str | int | bool


class ReadinessProbe(Protocol):
    """Port implemented by a concrete infrastructure dependency."""

    @property
    def name(self) -> str: ...

    async def check(self) -> dict[str, ProbeValue]: ...


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    status: str
    details: dict[str, ProbeValue]


@dataclass(frozen=True, slots=True)
class PlatformStatus:
    service: str
    status: str


@dataclass(frozen=True, slots=True)
class PlatformInformation:
    service: str
    release: str
    api_version: str


@dataclass(frozen=True, slots=True)
class ReadinessStatus:
    service: str
    status: str
    checks: dict[str, DependencyStatus]


class PlatformApplicationService:
    """Application service behind every platform HTTP endpoint."""

    def __init__(
        self,
        identity: PlatformIdentity,
        probes: tuple[ReadinessProbe, ...],
    ) -> None:
        if not probes:
            raise ValueError("Mindestens eine Readiness-Prüfung ist erforderlich.")
        names = [probe.name for probe in probes]
        if len(names) != len(set(names)):
            raise ValueError("Readiness-Prüfungen müssen eindeutige Namen besitzen.")
        self._identity = identity
        self._probes = probes

    def live(self) -> PlatformStatus:
        return PlatformStatus(service=self._identity.service, status="live")

    def information(self) -> PlatformInformation:
        return PlatformInformation(
            service=self._identity.service,
            release=self._identity.release,
            api_version=self._identity.api_version,
        )

    async def readiness(self) -> ReadinessStatus:
        results = await asyncio.gather(
            *(self._run_probe(probe) for probe in self._probes)
        )
        checks = dict(results)
        ready = all(check.status == "ready" for check in checks.values())
        return ReadinessStatus(
            service=self._identity.service,
            status="ready" if ready else "not-ready",
            checks=checks,
        )

    @staticmethod
    async def _run_probe(
        probe: ReadinessProbe,
    ) -> tuple[str, DependencyStatus]:
        try:
            details = await probe.check()
            return probe.name, DependencyStatus(status="ready", details=details)
        except Exception:
            return (
                probe.name,
                DependencyStatus(
                    status="not-ready",
                    details={"errorCode": "dependency_unavailable"},
                ),
            )
