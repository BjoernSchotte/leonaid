"""Ports and response values for operational administration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ApiMetricSnapshot:
    requests: int
    errors: int
    average_latency_ms: float


@dataclass(frozen=True, slots=True)
class DependencySignal:
    dependency: str
    status: str
    latency_ms: float
    request_id: str
    error_code: str | None


@dataclass(frozen=True, slots=True)
class FailedJob:
    id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    attempts: int
    last_error_code: str
    failed_at: datetime
    manual_retry_count: int


@dataclass(frozen=True, slots=True)
class OperationalCheck:
    key: Literal["backup", "disk", "tls"]
    status: Literal["ready", "critical"]
    value: float


@dataclass(frozen=True, slots=True)
class OperationalAlert:
    name: str
    severity: Literal["P0", "P1", "P2"]
    category: str
    summary: str
    runbook_url: str


@dataclass(frozen=True, slots=True)
class MonitoringSnapshot:
    status: Literal["inactive", "ready", "attention", "unavailable"]
    checks: tuple[OperationalCheck, ...]
    active_alerts: tuple[OperationalAlert, ...]


@dataclass(frozen=True, slots=True)
class OperationsSnapshot:
    generated_at: datetime
    request_id: str
    api: ApiMetricSnapshot
    dependencies: tuple[DependencySignal, ...]
    outbox: dict[str, int]
    mail: dict[str, int]
    login: dict[str, int]
    failed_jobs: tuple[FailedJob, ...]
    monitoring: MonitoringSnapshot


@dataclass(frozen=True, slots=True)
class PilotDailyDependencyCoverage:
    ready: int
    total: int
    unavailable: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PilotDailyMonitoringCoverage:
    status: Literal["inactive", "ready", "attention", "unavailable"]
    backup_status: Literal["ready", "critical", "unavailable"]
    backup_age_seconds: float | None
    disk_status: Literal["ready", "critical", "unavailable"]
    disk_free_ratio: float | None
    tls_status: Literal["ready", "critical", "unavailable"]
    tls_remaining_seconds: float | None
    active_p0: int
    active_p1: int
    active_p2: int


@dataclass(frozen=True, slots=True)
class PilotDailyReport:
    generated_at: datetime
    release: str
    technical_status: Literal["ready", "attention", "blocked"]
    dependencies: PilotDailyDependencyCoverage
    monitoring: PilotDailyMonitoringCoverage
    outbox: dict[str, int]
    api: ApiMetricSnapshot
    stop_reasons: tuple[str, ...]
    next_step: str


def build_pilot_daily_report(
    snapshot: OperationsSnapshot,
    *,
    release: str,
) -> PilotDailyReport:
    """Derive a payload-free, technical-only daily pilot decision aid."""

    unavailable = tuple(
        sorted(
            dependency.dependency
            for dependency in snapshot.dependencies
            if dependency.status != "ready"
        )
    )
    checks = {check.key: check for check in snapshot.monitoring.checks}
    blocker_reasons: list[str] = [
        f"dependency_{dependency}_unavailable" for dependency in unavailable
    ]
    attention_reasons: list[str] = []

    if snapshot.monitoring.status in {"inactive", "unavailable"}:
        blocker_reasons.append(f"monitoring_{snapshot.monitoring.status}")

    for key in ("backup", "disk", "tls"):
        check = checks.get(key)
        if check is None:
            blocker_reasons.append(f"{key}_unavailable")
        elif check.status == "critical":
            blocker_reasons.append(f"{key}_critical")

    alert_counts = {
        severity: sum(
            1
            for alert in snapshot.monitoring.active_alerts
            if alert.severity == severity
        )
        for severity in ("P0", "P1", "P2")
    }
    if alert_counts["P0"] > 0:
        blocker_reasons.append("active_p0_alert")
    if alert_counts["P1"] > 0:
        blocker_reasons.append("active_p1_alert")
    if alert_counts["P2"] > 0:
        attention_reasons.append("active_p2_alert")
    if snapshot.outbox.get("deadLetter", 0) > 0:
        blocker_reasons.append("outbox_dead_letter")
    if snapshot.api.errors > 0:
        attention_reasons.append("api_errors_observed")

    stop_reasons = tuple(dict.fromkeys((*blocker_reasons, *attention_reasons)))
    if blocker_reasons:
        technical_status: Literal["ready", "attention", "blocked"] = "blocked"
        next_step = (
            "Pilot nicht starten oder kontrolliert stoppen. Bearbeite zuerst "
            "alle genannten Stopgründe anhand der verlinkten Runbooks."
        )
    elif attention_reasons:
        technical_status = "attention"
        next_step = (
            "Befunde prüfen und dokumentieren. Der Report allein erteilt keine "
            "fachliche oder rechtliche Pilotfreigabe."
        )
    else:
        technical_status = "ready"
        next_step = (
            "Technische Tagesprüfung dokumentieren. Reale Fach-, Datenschutz- "
            "und Betreiberfreigaben bleiben separat erforderlich."
        )

    def check_status(
        key: Literal["backup", "disk", "tls"],
    ) -> Literal["ready", "critical", "unavailable"]:
        check = checks.get(key)
        return check.status if check is not None else "unavailable"

    def check_value(key: Literal["backup", "disk", "tls"]) -> float | None:
        check = checks.get(key)
        return check.value if check is not None else None

    return PilotDailyReport(
        generated_at=snapshot.generated_at,
        release=release,
        technical_status=technical_status,
        dependencies=PilotDailyDependencyCoverage(
            ready=len(snapshot.dependencies) - len(unavailable),
            total=len(snapshot.dependencies),
            unavailable=unavailable,
        ),
        monitoring=PilotDailyMonitoringCoverage(
            status=snapshot.monitoring.status,
            backup_status=check_status("backup"),
            backup_age_seconds=check_value("backup"),
            disk_status=check_status("disk"),
            disk_free_ratio=check_value("disk"),
            tls_status=check_status("tls"),
            tls_remaining_seconds=check_value("tls"),
            active_p0=alert_counts["P0"],
            active_p1=alert_counts["P1"],
            active_p2=alert_counts["P2"],
        ),
        outbox=dict(snapshot.outbox),
        api=snapshot.api,
        stop_reasons=stop_reasons,
        next_step=next_step,
    )


@dataclass(frozen=True, slots=True)
class RequestDiagnostic:
    """A deliberately payload-free trace of one recent HTTP request."""

    request_id: str
    occurred_at: datetime
    method: str
    route: str
    status_code: int
    error_code: str | None
    release: str


class RequestDiagnostics(Protocol):
    def find(self, request_id: str) -> RequestDiagnostic | None: ...


class OperationsService(Protocol):
    async def snapshot(self, *, request_id: str) -> OperationsSnapshot: ...

    async def daily_report(self, *, request_id: str) -> PilotDailyReport: ...

    async def retry(
        self,
        *,
        event_id: UUID,
        operator_user_id: UUID,
        request_id: str,
    ) -> FailedJob: ...
