"""Append-only acquisition activities and prioritized reminders."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from leonaid.application.crm import (
    CompanyRecord,
    CrmGateway,
    CrmPartyKind,
    PersonRecord,
)
from leonaid.application.errors import Conflict, PermissionDenied
from leonaid.application.policies import concealed_resource
from leonaid.application.privacy import PrivacyService
from leonaid.application.sponsor_matching import AssignedAcquirer
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
from leonaid.domain.privacy import (
    ContactChannel,
    PrivacyPurpose,
    normalize_recipient,
)


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
class PartyDetails:
    display_name: str
    postal_code: str | None
    city: str | None
    contact_name: str | None
    email: str | None
    phone: str | None


@dataclass(frozen=True, slots=True)
class AcquisitionWorkItem:
    assignment: AcquisitionAssignment
    party_display_name: str
    postal_code: str | None
    city: str | None
    contact_name: str | None
    email: str | None
    phone: str | None
    suppressed_channels: tuple[ContactChannel, ...]
    assigned_acquirers: tuple[AssignedAcquirer, ...]
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
    async def assigned_acquirers(
        self,
        action_id: UUID,
        party_kind: CrmPartyKind,
        party_ids: tuple[UUID, ...],
        *,
        evaluated_at: datetime,
    ) -> dict[UUID, tuple[AssignedAcquirer, ...]]: ...

    async def active_assignments_for_actor(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        evaluated_at: datetime,
    ) -> tuple[AcquisitionAssignment, ...]: ...

    async def active_assignments_for_action(
        self,
        *,
        action_id: UUID,
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

    async def activity_timeline_for_action(
        self,
        *,
        action_id: UUID,
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
        privacy: PrivacyService,
        *,
        local_timezone: ZoneInfo | None = None,
    ) -> None:
        self._repository = repository
        self._crm = crm
        self._privacy = privacy
        self._local_timezone = local_timezone or ZoneInfo("Europe/Berlin")

    async def board(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        action_wide: bool = False,
        limit: int = 50,
    ) -> AcquisitionActivityBoard:
        if action_wide:
            self._require_charity_admin(actor, action_id)
        else:
            self._require_acquirer(actor, action_id)
        if not 1 <= limit <= 100:
            raise ValueError("Aktivitätslimit muss zwischen 1 und 100 liegen.")
        generated_at = datetime.now(timezone.utc)
        if action_wide:
            assignments, activities = await asyncio.gather(
                self._repository.active_assignments_for_action(
                    action_id=action_id,
                ),
                self._repository.activity_timeline_for_action(
                    action_id=action_id,
                    limit=limit,
                ),
            )
        else:
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
        assigned_acquirers = await self._assigned_acquirers(
            action_id,
            party_keys,
            evaluated_at=generated_at,
        )
        suppressed = await self._privacy.suppressed_channels(
            tuple(
                (
                    value,
                    channel,
                )
                for details in party_details.values()
                for value, channel in (
                    (details.email, ContactChannel.EMAIL),
                    (details.phone, ContactChannel.PHONE),
                )
                if value is not None
            ),
            purpose=PrivacyPurpose.ACQUISITION,
        )
        work_items = tuple(
            sorted(
                (
                    AcquisitionWorkItem(
                        assignment=assignment,
                        party_display_name=party_details[
                            (assignment.party_kind, assignment.party_id)
                        ].display_name,
                        postal_code=party_details[
                            (assignment.party_kind, assignment.party_id)
                        ].postal_code,
                        city=party_details[
                            (assignment.party_kind, assignment.party_id)
                        ].city,
                        contact_name=party_details[
                            (assignment.party_kind, assignment.party_id)
                        ].contact_name,
                        email=party_details[
                            (assignment.party_kind, assignment.party_id)
                        ].email,
                        phone=party_details[
                            (assignment.party_kind, assignment.party_id)
                        ].phone,
                        suppressed_channels=tuple(
                            channel
                            for value, channel in (
                                (
                                    party_details[
                                        (
                                            assignment.party_kind,
                                            assignment.party_id,
                                        )
                                    ].email,
                                    ContactChannel.EMAIL,
                                ),
                                (
                                    party_details[
                                        (
                                            assignment.party_kind,
                                            assignment.party_id,
                                        )
                                    ].phone,
                                    ContactChannel.PHONE,
                                ),
                            )
                            if value is not None
                            and (
                                normalize_recipient(value, channel),
                                channel,
                            )
                            in suppressed
                        ),
                        assigned_acquirers=assigned_acquirers.get(
                            (assignment.party_kind, assignment.party_id),
                            (),
                        ),
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
                ].display_name,
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
        if channel in (ActivityChannel.EMAIL, ActivityChannel.PHONE):
            details = await self._party_details(
                {(party_kind, party_id)},
                correlation_prefix=f"{request_id}:suppression-party",
            )
            contact_channel = (
                ContactChannel.EMAIL
                if channel is ActivityChannel.EMAIL
                else ContactChannel.PHONE
            )
            contact_value = (
                details[(party_kind, party_id)].email
                if contact_channel is ContactChannel.EMAIL
                else details[(party_kind, party_id)].phone
            )
            if contact_value is not None:
                suppressed = await self._privacy.suppressed_channels(
                    ((contact_value, contact_channel),),
                    purpose=PrivacyPurpose.ACQUISITION,
                )
                if suppressed:
                    raise Conflict(
                        "contact_suppressed",
                        "Dieser Kontakt ist für diesen Kommunikationskanal gesperrt.",
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
            party_display_name=details[(party_kind, party_id)].display_name,
        )
        return result, item

    async def _assigned_acquirers(
        self,
        action_id: UUID,
        keys: set[tuple[AssignmentPartyKind, UUID]],
        *,
        evaluated_at: datetime,
    ) -> dict[tuple[AssignmentPartyKind, UUID], tuple[AssignedAcquirer, ...]]:
        by_kind = {
            kind: tuple(
                sorted(
                    (party_id for party_kind, party_id in keys if party_kind is kind),
                    key=str,
                )
            )
            for kind in AssignmentPartyKind
        }
        results = await asyncio.gather(
            *(
                self._repository.assigned_acquirers(
                    action_id,
                    CrmPartyKind(kind.value),
                    party_ids,
                    evaluated_at=evaluated_at,
                )
                for kind, party_ids in by_kind.items()
                if party_ids
            )
        )
        assigned: dict[
            tuple[AssignmentPartyKind, UUID], tuple[AssignedAcquirer, ...]
        ] = {}
        result_index = 0
        for kind, party_ids in by_kind.items():
            if not party_ids:
                continue
            values = results[result_index]
            result_index += 1
            assigned.update(
                ((kind, party_id), values.get(party_id, ())) for party_id in party_ids
            )
        return assigned

    async def _party_details(
        self,
        keys: set[tuple[AssignmentPartyKind, UUID]],
        *,
        correlation_prefix: str,
    ) -> dict[
        tuple[AssignmentPartyKind, UUID],
        PartyDetails,
    ]:
        ordered = sorted(keys, key=lambda item: (item[0].value, str(item[1])))
        if not ordered:
            return {}
        has_companies = any(kind is AssignmentPartyKind.COMPANY for kind, _ in ordered)
        if has_companies:
            companies_result, people = await asyncio.gather(
                self._crm.list_companies(
                    correlation_id=f"{correlation_prefix}:companies",
                ),
                self._crm.list_people(
                    correlation_id=f"{correlation_prefix}:people",
                ),
            )
            companies: tuple[CompanyRecord, ...] = companies_result
        else:
            companies = ()
            people = await self._crm.list_people(
                correlation_id=f"{correlation_prefix}:people",
            )
        companies_by_id = {company.twenty_id: company for company in companies}
        people_by_id = {person.twenty_id: person for person in people}
        company_contacts: dict[UUID, tuple[PersonRecord, ...]] = {}
        for person in people:
            company_id = person.data.company_twenty_id
            if company_id is not None:
                company_contacts[company_id] = (
                    *company_contacts.get(company_id, ()),
                    person,
                )

        def load(
            party_kind: AssignmentPartyKind,
            party_id: UUID,
        ) -> tuple[
            tuple[AssignmentPartyKind, UUID],
            PartyDetails,
        ]:
            if party_kind is AssignmentPartyKind.COMPANY:
                company = companies_by_id.get(party_id)
                if company is None:
                    raise concealed_resource()
                contacts = sorted(
                    company_contacts.get(party_id, ()),
                    key=lambda person: (
                        person.data.family_name.casefold(),
                        person.data.given_name.casefold(),
                        str(person.twenty_id),
                    ),
                )
                contact = next(
                    (
                        person
                        for person in contacts
                        if person.data.email is not None
                        or person.data.phone is not None
                    ),
                    None,
                )
                return (
                    (party_kind, party_id),
                    PartyDetails(
                        display_name=company.data.name,
                        postal_code=company.data.address.postal_code,
                        city=company.data.address.city,
                        contact_name=(
                            f"{contact.data.given_name} {contact.data.family_name}"
                            if contact is not None
                            else None
                        ),
                        email=contact.data.email if contact is not None else None,
                        phone=contact.data.phone if contact is not None else None,
                    ),
                )
            person = people_by_id.get(party_id)
            if person is None:
                raise concealed_resource()
            return (
                (party_kind, party_id),
                PartyDetails(
                    display_name=f"{person.data.given_name} {person.data.family_name}",
                    postal_code=None,
                    city=None,
                    contact_name=None,
                    email=person.data.email,
                    phone=person.data.phone,
                ),
            )

        return dict(load(party_kind, party_id) for party_kind, party_id in ordered)

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
    def _require_charity_admin(actor: IdentityPrincipal, action_id: UUID) -> None:
        if (
            actor.account.can_authenticate
            and ActionRole.CHARITY_ADMIN in actor.roles_for(action_id)
        ):
            return
        raise PermissionDenied(
            "charity_admin_required",
            "Die aktionsweite Pipeline ist nur für Charity-Admins sichtbar.",
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
