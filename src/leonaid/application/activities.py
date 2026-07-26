"""Append-only acquisition activities and prioritized reminders."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from leonaid.application.crm import CrmGateway
from leonaid.application.errors import Conflict, PermissionDenied
from leonaid.application.policies import concealed_resource
from leonaid.domain.acquisition import (
    AcquisitionAssignment,
    ActivityCapture,
    ActivityChannel,
    ActivityOutcome,
    AssignmentPartyKind,
    ReminderUrgency,
    reminder_urgency,
)
from leonaid.domain.identity import ActionRole, IdentityPrincipal


@dataclass(frozen=True, slots=True)
class RecordedAcquisitionActivity:
    id: UUID
    action_id: UUID
    assignment_id: UUID
    party_kind: AssignmentPartyKind
    party_id: UUID
    actor_user_id: UUID
    actor_display_name: str
    channel: ActivityChannel
    outcome: ActivityOutcome
    note: str | None
    next_action: str | None
    due_at: datetime | None
    assignment_revision: int
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AcquisitionWorkItem:
    assignment: AcquisitionAssignment
    party_display_name: str
    postal_code: str | None
    city: str | None
    email: str | None
    urgency: ReminderUrgency


@dataclass(frozen=True, slots=True)
class AcquisitionActivityItem:
    activity: RecordedAcquisitionActivity
    party_display_name: str


@dataclass(frozen=True, slots=True)
class AcquisitionActivityBoard:
    action_id: UUID
    generated_at: datetime
    work_items: tuple[AcquisitionWorkItem, ...]
    activities: tuple[AcquisitionActivityItem, ...]


@dataclass(frozen=True, slots=True)
class ActivityRecordingResult:
    assignment: AcquisitionAssignment
    activity: RecordedAcquisitionActivity


class AcquisitionActivityRepository(Protocol):
    async def active_assignments_for_actor(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        evaluated_at: datetime,
    ) -> tuple[AcquisitionAssignment, ...]: ...

    async def active_assignment_for_actor(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        party_kind: AssignmentPartyKind,
        party_id: UUID,
        evaluated_at: datetime,
    ) -> AcquisitionAssignment | None: ...

    async def activity_timeline_for_actor(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        evaluated_at: datetime,
        limit: int,
    ) -> tuple[RecordedAcquisitionActivity, ...]: ...

    async def record_activity(
        self,
        previous: AcquisitionAssignment,
        changed: AcquisitionAssignment,
        capture: ActivityCapture,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> ActivityRecordingResult | None: ...


class AcquisitionActivityService:
    def __init__(
        self,
        repository: AcquisitionActivityRepository,
        crm: CrmGateway,
        *,
        local_timezone: ZoneInfo | None = None,
    ) -> None:
        self._repository = repository
        self._crm = crm
        self._local_timezone = local_timezone or ZoneInfo("Europe/Berlin")

    async def board(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        limit: int = 50,
    ) -> AcquisitionActivityBoard:
        self._require_acquirer(actor, action_id)
        if not 1 <= limit <= 100:
            raise ValueError("Aktivitätslimit muss zwischen 1 und 100 liegen.")
        generated_at = datetime.now(timezone.utc)
        assignments, activities = await asyncio.gather(
            self._repository.active_assignments_for_actor(
                action_id=action_id,
                actor_user_id=actor.account.id,
                evaluated_at=generated_at,
            ),
            self._repository.activity_timeline_for_actor(
                action_id=action_id,
                actor_user_id=actor.account.id,
                evaluated_at=generated_at,
                limit=limit,
            ),
        )
        party_keys = {
            (assignment.party_kind, assignment.party_id) for assignment in assignments
        } | {(activity.party_kind, activity.party_id) for activity in activities}
        party_details = await self._party_details(
            party_keys,
            correlation_prefix=f"activity-board:{action_id}",
        )
        work_items = tuple(
            sorted(
                (
                    AcquisitionWorkItem(
                        assignment=assignment,
                        party_display_name=party_details[
                            (assignment.party_kind, assignment.party_id)
                        ][0],
                        postal_code=party_details[
                            (assignment.party_kind, assignment.party_id)
                        ][1],
                        city=party_details[
                            (assignment.party_kind, assignment.party_id)
                        ][2],
                        email=party_details[
                            (assignment.party_kind, assignment.party_id)
                        ][3],
                        urgency=reminder_urgency(
                            assignment.state.due_at,
                            evaluated_at=generated_at,
                            local_timezone=self._local_timezone,
                        ),
                    )
                    for assignment in assignments
                ),
                key=self._work_sort_key,
            )
        )
        activity_items = tuple(
            AcquisitionActivityItem(
                activity=activity,
                party_display_name=party_details[
                    (activity.party_kind, activity.party_id)
                ][0],
            )
            for activity in activities
        )
        return AcquisitionActivityBoard(
            action_id=action_id,
            generated_at=generated_at,
            work_items=work_items,
            activities=activity_items,
        )

    async def record(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        party_kind: AssignmentPartyKind,
        party_id: UUID,
        expected_revision: int,
        channel: ActivityChannel,
        outcome: ActivityOutcome,
        note: str | None,
        next_action: str | None,
        due_on: date | None,
        request_id: str,
    ) -> tuple[ActivityRecordingResult, AcquisitionActivityItem]:
        self._require_acquirer(actor, action_id)
        occurred_at = datetime.now(timezone.utc)
        previous = await self._repository.active_assignment_for_actor(
            action_id=action_id,
            actor_user_id=actor.account.id,
            party_kind=party_kind,
            party_id=party_id,
            evaluated_at=occurred_at,
        )
        if previous is None:
            raise concealed_resource()
        if previous.revision != expected_revision:
            raise Conflict(
                "assignment_revision_conflict",
                "Die Zuordnung wurde zwischenzeitlich geändert. Bitte lade sie neu.",
            )
        due_at = (
            datetime.combine(
                due_on,
                time(hour=9),
                tzinfo=self._local_timezone,
            ).astimezone(timezone.utc)
            if due_on is not None
            else None
        )
        capture = ActivityCapture.create(
            channel=channel,
            outcome=outcome,
            note=note,
            next_action=next_action,
            due_at=due_at,
        )
        changed = previous.record_activity(capture, occurred_at=occurred_at)
        result = await self._repository.record_activity(
            previous,
            changed,
            capture,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=occurred_at,
        )
        if result is None:
            raise concealed_resource()
        details = await self._party_details(
            {(party_kind, party_id)},
            correlation_prefix=f"{request_id}:activity-party",
        )
        item = AcquisitionActivityItem(
            activity=result.activity,
            party_display_name=details[(party_kind, party_id)][0],
        )
        return result, item

    async def _party_details(
        self,
        keys: set[tuple[AssignmentPartyKind, UUID]],
        *,
        correlation_prefix: str,
    ) -> dict[
        tuple[AssignmentPartyKind, UUID],
        tuple[str, str | None, str | None, str | None],
    ]:
        ordered = sorted(keys, key=lambda item: (item[0].value, str(item[1])))

        async def load(
            party_kind: AssignmentPartyKind,
            party_id: UUID,
        ) -> tuple[
            tuple[AssignmentPartyKind, UUID],
            tuple[str, str | None, str | None, str | None],
        ]:
            if party_kind is AssignmentPartyKind.COMPANY:
                company = await self._crm.get_company(
                    party_id,
                    correlation_id=f"{correlation_prefix}:company:{party_id}",
                )
                if company is None:
                    raise concealed_resource()
                return (
                    (party_kind, party_id),
                    (
                        company.data.name,
                        company.data.address.postal_code,
                        company.data.address.city,
                        None,
                    ),
                )
            person = await self._crm.get_person(
                party_id,
                correlation_id=f"{correlation_prefix}:person:{party_id}",
            )
            if person is None:
                raise concealed_resource()
            return (
                (party_kind, party_id),
                (
                    f"{person.data.given_name} {person.data.family_name}",
                    None,
                    None,
                    person.data.email,
                ),
            )

        return dict(
            await asyncio.gather(
                *(load(party_kind, party_id) for party_kind, party_id in ordered)
            )
        )

    @staticmethod
    def _require_acquirer(actor: IdentityPrincipal, action_id: UUID) -> None:
        if actor.account.can_authenticate and ActionRole.ACQUIRER in actor.roles_for(
            action_id
        ):
            return
        raise PermissionDenied(
            "acquirer_required",
            "Aktivitäten dürfen nur aktive Akquisiteure dieser Charity-Aktion erfassen.",
        )

    @staticmethod
    def _work_sort_key(item: AcquisitionWorkItem) -> tuple[object, ...]:
        due_at = item.assignment.state.due_at
        return (
            item.urgency.rank,
            due_at or datetime.max.replace(tzinfo=timezone.utc),
            -item.assignment.state.priority,
            item.party_display_name.casefold(),
            str(item.assignment.id),
        )
