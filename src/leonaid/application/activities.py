"""Append-only acquisition activities and prioritized reminders."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from leonaid.application.crm import (
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
from leonaid.domain.calendar import INSTALLATION_TIME_ZONE
from leonaid.domain.captures import bounded_captured_at
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import ActionRole, IdentityPrincipal
from leonaid.domain.policies import may_manage_action
from leonaid.domain.privacy import (
    ContactChannel,
    PrivacyPurpose,
    normalize_recipient,
)

# The format every Core command key follows (application/commitments.py);
# the PWA queue sends ``pwa-q:<entryId>``. Repeated here so the activity use
# case does not depend on the ordering module.
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
ACTIVITY_COMMAND_TYPE = "acquisition.activity.record"


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
    # False when a queued capture met a moved assignment (PLAN §11.4, D1):
    # the contact is recorded, status and follow-up stay as they are.
    assignment_updated: bool = True
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ActivityCommand:
    """The idempotency receipt of one activity send (``Idempotency-Key``)."""

    idempotency_key: str
    request_hash: str


def activity_request_hash(
    *,
    action_id: UUID,
    actor_user_id: UUID,
    party_kind: AssignmentPartyKind,
    party_id: UUID,
    expected_revision: int,
    channel: ActivityChannel,
    outcome: ActivityOutcome,
    note: str | None,
    next_action: str | None,
    due_on: date | None,
    captured_at: datetime | None,
) -> str:
    """SHA-256 over the request as sent; actor and action bind the key."""

    payload = {
        "actionId": str(action_id),
        "actorUserId": str(actor_user_id),
        "partyKind": party_kind.value,
        "partyId": str(party_id),
        "revision": expected_revision,
        "channel": channel.value,
        "outcome": outcome.value,
        "note": note,
        "nextAction": next_action,
        "dueOn": due_on.isoformat() if due_on is not None else None,
        "capturedAt": (
            captured_at.astimezone(timezone.utc).isoformat()
            if captured_at is not None
            else None
        ),
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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

    async def replayed_activity(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        command: ActivityCommand,
        evaluated_at: datetime,
    ) -> ActivityRecordingResult | None:
        """The stored result of ``command``, or None when the key is new.

        Raises ``idempotency_conflict`` for a key used with other content and
        conceals the result when the actor no longer holds the assignment.
        """
        ...

    async def record_activity(
        self,
        previous: AcquisitionAssignment,
        changed: AcquisitionAssignment,
        capture: ActivityCapture,
        *,
        expected_revision: int,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
        received_at: datetime,
        command: ActivityCommand | None = None,
        keep_contact_on_moved_assignment: bool = False,
    ) -> ActivityRecordingResult | None:
        """Persist the activity and, unless the assignment moved, the change.

        ``previous`` is the assignment as read, ``changed`` is built from it
        and ``expected_revision`` is the revision the capture was based on.
        The change is applied only when ``expected_revision`` equals the read
        revision and the row still has it; otherwise the assignment moved.
        ``occurred_at`` is when the contact happened (``capturedAt`` or the
        receive time); ``received_at`` is Core's time and drives membership
        checks, ``updated_at``, the history and the audit event. With
        ``keep_contact_on_moved_assignment`` a revision mismatch records the
        activity without changing the assignment instead of a conflict. With
        ``command`` the receipt is stored in the same transaction, and a
        concurrent send of the same key returns that send's result.
        """
        ...


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
        self._local_timezone = local_timezone or INSTALLATION_TIME_ZONE

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
        captured_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[ActivityRecordingResult, AcquisitionActivityItem]:
        self._require_acquirer(actor, action_id)
        received_at = datetime.now(timezone.utc)
        # The key is optional for one release so that an older cached PWA
        # keeps working (PLAN §11.1, risk R3).
        command: ActivityCommand | None = None
        if idempotency_key is not None:
            if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
                raise DomainInvariantError(
                    "activity_idempotency_key_invalid",
                    "Die Vorgangs-ID besitzt ein ungültiges Format.",
                )
            command = ActivityCommand(
                idempotency_key=idempotency_key,
                request_hash=activity_request_hash(
                    action_id=action_id,
                    actor_user_id=actor.account.id,
                    party_kind=party_kind,
                    party_id=party_id,
                    expected_revision=expected_revision,
                    channel=channel,
                    outcome=outcome,
                    note=note,
                    next_action=next_action,
                    due_on=due_on,
                    captured_at=captured_at,
                ),
            )
            # A resend after a lost answer carries the revision the first
            # send already moved on, and may arrive after the capture-time
            # window closed: the receipt is read before any check.
            replayed = await self._replay(
                action_id=action_id,
                actor_user_id=actor.account.id,
                command=command,
                received_at=received_at,
                request_id=request_id,
            )
            if replayed is not None:
                return replayed
        # Only a new write is bound to the window (PLAN §11.2, D5).
        occurred_at = (
            bounded_captured_at(captured_at, received_at=received_at)
            if captured_at is not None
            else received_at
        )
        previous = await self._repository.active_assignment_for_actor(
            action_id=action_id,
            actor_user_id=actor.account.id,
            party_kind=party_kind,
            party_id=party_id,
            evaluated_at=received_at,
        )
        if previous is None:
            raise concealed_resource()
        # A queued capture (capturedAt) keeps the contact when the assignment
        # moved meanwhile (D1); an online capture is refused as before, and
        # before any CRM lookup.
        keep_contact = captured_at is not None
        if previous.revision != expected_revision and not keep_contact:
            if command is not None:
                # A revision moved by a concurrent send of this very key is
                # committed together with its receipt: replay it.
                replayed = await self._replay(
                    action_id=action_id,
                    actor_user_id=actor.account.id,
                    command=command,
                    received_at=received_at,
                    request_id=request_id,
                )
                if replayed is not None:
                    return replayed
            raise Conflict(
                "assignment_revision_conflict",
                "Die Zuordnung wurde zwischenzeitlich geändert. Bitte neu laden.",
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
        # due_on stays a calendar date from the device: 09:00 club time.
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
        # ``changed`` is built from the state read at ``previous.revision``;
        # the repository applies it only when the capture was based on that
        # very revision and the row still has it.
        changed = previous.record_activity(capture, occurred_at=received_at)
        result = await self._repository.record_activity(
            previous,
            changed,
            capture,
            expected_revision=expected_revision,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=occurred_at,
            received_at=received_at,
            command=command,
            keep_contact_on_moved_assignment=keep_contact,
        )
        if result is None:
            raise concealed_resource()
        return result, await self._activity_item(result, request_id=request_id)

    async def _replay(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        command: ActivityCommand,
        received_at: datetime,
        request_id: str,
    ) -> tuple[ActivityRecordingResult, AcquisitionActivityItem] | None:
        replayed = await self._repository.replayed_activity(
            action_id=action_id,
            actor_user_id=actor_user_id,
            command=command,
            evaluated_at=received_at,
        )
        if replayed is None:
            return None
        return replayed, await self._activity_item(replayed, request_id=request_id)

    async def _activity_item(
        self,
        result: ActivityRecordingResult,
        *,
        request_id: str,
    ) -> AcquisitionActivityItem:
        key = (result.activity.party_kind, result.activity.party_id)
        details = await self._party_details(
            {key},
            correlation_prefix=f"{request_id}:activity-party",
        )
        return AcquisitionActivityItem(
            activity=result.activity,
            party_display_name=details[key].display_name,
        )

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
        # Fetch only the referenced parties (and the contacts of referenced
        # companies) in batched ID queries, never whole CRM collections.
        company_ids = tuple(
            party_id
            for kind, party_id in ordered
            if kind is AssignmentPartyKind.COMPANY
        )
        person_ids = tuple(
            party_id for kind, party_id in ordered if kind is AssignmentPartyKind.PERSON
        )
        companies, people, contacts = await asyncio.gather(
            self._crm.get_companies(
                company_ids,
                correlation_id=f"{correlation_prefix}:companies",
            ),
            self._crm.get_people(
                person_ids,
                correlation_id=f"{correlation_prefix}:people",
            ),
            self._crm.list_company_contacts(
                company_ids,
                correlation_id=f"{correlation_prefix}:contacts",
            ),
        )
        companies_by_id = {company.twenty_id: company for company in companies}
        people_by_id = {person.twenty_id: person for person in people}
        company_contacts: dict[UUID, tuple[PersonRecord, ...]] = {}
        for person in contacts:
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
        # The policy of the assignments themselves (authorized_scope): the
        # action's charity admins and every system admin.
        if actor.account.can_authenticate and may_manage_action(actor, action_id):
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
