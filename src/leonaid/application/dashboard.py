"""Role-aware dashboard reads without frontend-owned business calculations."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol, TypeVar
from uuid import UUID

from leonaid.application.policies import concealed_resource
from leonaid.domain.identity import ActionRole, IdentityPrincipal

StatusValue = TypeVar("StatusValue", bound=str)


@dataclass(frozen=True, slots=True)
class PipelineCounts:
    open: int = 0
    contacted: int = 0
    committed: int = 0
    declined: int = 0
    handed_over: int = 0

    @property
    def total(self) -> int:
        return (
            self.open
            + self.contacted
            + self.committed
            + self.declined
            + self.handed_over
        )


@dataclass(frozen=True, slots=True)
class ReminderCounts:
    overdue: int = 0
    today: int = 0
    upcoming: int = 0
    unscheduled: int = 0

    @property
    def total(self) -> int:
        return self.overdue + self.today + self.upcoming + self.unscheduled


@dataclass(frozen=True, slots=True)
class CommitmentCounts:
    draft: int = 0
    review_ready: int = 0
    confirmed: int = 0
    invoiced: int = 0
    cancelled: int = 0
    active_total_minor: int = 0
    total_boxes: int = 0
    total_pieces: int = 0

    @property
    def total(self) -> int:
        return (
            self.draft
            + self.review_ready
            + self.confirmed
            + self.invoiced
            + self.cancelled
        )

    @property
    def active_total(self) -> int:
        return self.total - self.cancelled


@dataclass(frozen=True, slots=True)
class InvoiceCounts:
    issued: int = 0
    sent: int = 0
    paid: int = 0
    cancelled: int = 0
    invoiced_amount_minor: int = 0
    open_amount_minor: int = 0

    @property
    def open(self) -> int:
        return self.issued + self.sent

    @property
    def total(self) -> int:
        return self.open + self.paid + self.cancelled


@dataclass(frozen=True, slots=True)
class GoalProgress:
    actual_value: Decimal
    target_value: Decimal | None
    unit: str | None
    currency: str
    progress_basis_points: int | None

    @property
    def configured(self) -> bool:
        return self.target_value is not None and self.unit is not None


@dataclass(frozen=True, slots=True)
class AcquirerDashboard:
    pipeline: PipelineCounts
    reminders: ReminderCounts
    activity_count: int


@dataclass(frozen=True, slots=True)
class CharityAdminDashboard:
    pipeline: PipelineCounts
    commitments: CommitmentCounts
    invoices: InvoiceCounts


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    action_id: UUID
    action_name: str
    goal: GoalProgress
    currency: str
    acquirer: AcquirerDashboard | None
    charity_admin: CharityAdminDashboard | None
    generated_at: datetime


class DashboardRepository(Protocol):
    async def snapshot(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        include_acquirer: bool,
        include_charity_admin: bool,
        evaluated_at: datetime,
    ) -> DashboardSnapshot | None: ...


def progress_basis_points(
    actual_value: Decimal,
    target_value: Decimal | None,
) -> int | None:
    """Return hundredths of a percent, preserving values above 100 percent."""

    if target_value is None or target_value <= 0:
        return None
    return int(
        (actual_value * Decimal(10_000) / target_value).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def count_statuses(
    values: Iterable[StatusValue],
    allowed: tuple[StatusValue, ...],
) -> dict[StatusValue, int]:
    """Count a closed status vocabulary and reject silent data drift."""

    counts = {status: 0 for status in allowed}
    for value in values:
        if value not in counts:
            raise ValueError(f"Unbekannter Status in Dashboard-Kennzahl: {value}")
        counts[value] += 1
    return counts


class DashboardService:
    def __init__(
        self,
        repository: DashboardRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def get(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
    ) -> DashboardSnapshot:
        roles = actor.roles_for(action_id)
        include_acquirer = ActionRole.ACQUIRER in roles
        include_charity_admin = ActionRole.CHARITY_ADMIN in roles
        if not include_acquirer and not include_charity_admin:
            raise concealed_resource()

        evaluated_at = self._clock()
        snapshot = await self._repository.snapshot(
            action_id=action_id,
            actor_user_id=actor.account.id,
            include_acquirer=include_acquirer,
            include_charity_admin=include_charity_admin,
            evaluated_at=evaluated_at,
        )
        if snapshot is None:
            raise concealed_resource()
        return snapshot
