"""Acquisition-assignment state and history invariants."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, tzinfo
from enum import StrEnum
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import require_aware


class AssignmentPartyKind(StrEnum):
    COMPANY = "company"
    PERSON = "person"


class AssignmentStatus(StrEnum):
    OPEN = "open"
    CONTACTED = "contacted"
    COMMITTED = "committed"
    DECLINED = "declined"
    HANDED_OVER = "handed_over"


class ActivityChannel(StrEnum):
    PHONE = "phone"
    EMAIL = "email"
    IN_PERSON = "in_person"


class ActivityOutcome(StrEnum):
    REACHED = "reached"
    NO_ANSWER = "no_answer"
    INTERESTED = "interested"
    FOLLOW_UP = "follow_up"
    COMMITTED = "committed"
    DECLINED = "declined"

    def assignment_status(self) -> AssignmentStatus:
        if self is ActivityOutcome.COMMITTED:
            return AssignmentStatus.COMMITTED
        if self is ActivityOutcome.DECLINED:
            return AssignmentStatus.DECLINED
        return AssignmentStatus.CONTACTED


class ReminderUrgency(StrEnum):
    OVERDUE = "overdue"
    TODAY = "today"
    UPCOMING = "upcoming"
    NONE = "none"

    @property
    def rank(self) -> int:
        return {
            ReminderUrgency.OVERDUE: 0,
            ReminderUrgency.TODAY: 1,
            ReminderUrgency.UPCOMING: 2,
            ReminderUrgency.NONE: 3,
        }[self]


@dataclass(frozen=True, slots=True)
class ActivityCapture:
    channel: ActivityChannel
    outcome: ActivityOutcome
    note: str | None
    next_action: str | None
    due_at: datetime | None

    def __post_init__(self) -> None:
        if self.note is not None:
            if self.note != self.note.strip():
                raise DomainInvariantError(
                    "activity_note_whitespace",
                    "Die Notiz darf keine äußeren Leerzeichen enthalten.",
                )
            if not self.note or len(self.note) > 2000:
                raise DomainInvariantError(
                    "activity_note_length",
                    "Die Notiz darf höchstens 2.000 Zeichen lang sein.",
                )
            if any(
                ord(character) < 32 and character not in {"\n", "\t"}
                for character in self.note
            ):
                raise DomainInvariantError(
                    "activity_note_control_character",
                    "Die Notiz enthält nicht unterstützte Steuerzeichen.",
                )
        if (self.next_action is None) != (self.due_at is None):
            raise DomainInvariantError(
                "activity_reminder_incomplete",
                "Eine Wiedervorlage benötigt sowohl nächste Aktion als auch Datum.",
            )
        if self.next_action is not None:
            if self.next_action != self.next_action.strip():
                raise DomainInvariantError(
                    "activity_next_action_whitespace",
                    "Die nächste Aktion darf keine äußeren Leerzeichen enthalten.",
                )
            if not self.next_action or len(self.next_action) > 300:
                raise DomainInvariantError(
                    "activity_next_action_length",
                    "Die nächste Aktion darf höchstens 300 Zeichen lang sein.",
                )
        if self.due_at is not None:
            require_aware(self.due_at, "due_at")

    @classmethod
    def create(
        cls,
        *,
        channel: ActivityChannel,
        outcome: ActivityOutcome,
        note: str | None,
        next_action: str | None,
        due_at: datetime | None,
    ) -> ActivityCapture:
        normalized_note = None
        if note is not None:
            normalized_note = "\n".join(
                " ".join(line.split()) for line in note.replace("\r", "").split("\n")
            ).strip()
        normalized_next_action = (
            " ".join(next_action.split()) if next_action is not None else None
        )
        return cls(
            channel=channel,
            outcome=outcome,
            note=normalized_note or None,
            next_action=normalized_next_action or None,
            due_at=due_at,
        )


def reminder_urgency(
    due_at: datetime | None,
    *,
    evaluated_at: datetime,
    local_timezone: tzinfo,
) -> ReminderUrgency:
    require_aware(evaluated_at, "evaluated_at")
    if due_at is None:
        return ReminderUrgency.NONE
    require_aware(due_at, "due_at")
    due_on = due_at.astimezone(local_timezone).date()
    today = evaluated_at.astimezone(local_timezone).date()
    if due_on < today:
        return ReminderUrgency.OVERDUE
    if due_on == today:
        return ReminderUrgency.TODAY
    return ReminderUrgency.UPCOMING


@dataclass(frozen=True, slots=True)
class AssignmentState:
    status: AssignmentStatus = AssignmentStatus.OPEN
    priority: int = 0
    next_action: str | None = None
    due_at: datetime | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.priority <= 3:
            raise DomainInvariantError(
                "assignment_priority_invalid",
                "Die Priorität muss zwischen 0 und 3 liegen.",
            )
        if self.next_action is not None:
            if self.next_action != self.next_action.strip():
                raise DomainInvariantError(
                    "assignment_next_action_whitespace",
                    "Die nächste Aktion darf keine äußeren Leerzeichen enthalten.",
                )
            if not self.next_action or len(self.next_action) > 300:
                raise DomainInvariantError(
                    "assignment_next_action_invalid",
                    "Die nächste Aktion muss zwischen 1 und 300 Zeichen lang sein.",
                )
        if self.due_at is not None:
            require_aware(self.due_at, "due_at")

    def snapshot(self, *, acquirer_user_id: UUID) -> dict[str, object]:
        return {
            "status": self.status.value,
            "priority": self.priority,
            "nextAction": self.next_action,
            "dueAt": self.due_at.isoformat() if self.due_at is not None else None,
            "acquirerUserId": str(acquirer_user_id),
        }


@dataclass(frozen=True, slots=True)
class AcquisitionAssignment:
    id: UUID
    action_id: UUID
    party_kind: AssignmentPartyKind
    party_id: UUID
    acquirer_user_id: UUID
    acquirer_display_name: str
    state: AssignmentState
    revision: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.acquirer_display_name.strip():
            raise DomainInvariantError(
                "assignment_acquirer_name_empty",
                "Ein Akquisiteur benötigt einen Anzeigenamen.",
            )
        if self.revision <= 0:
            raise DomainInvariantError(
                "assignment_revision_invalid",
                "Die Zuordnungsrevision muss positiv sein.",
            )
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise DomainInvariantError(
                "assignment_timestamps_invalid",
                "Eine Zuordnung darf nicht vor ihrer Anlage geändert worden sein.",
            )

    def update_work(
        self,
        *,
        status: AssignmentStatus,
        priority: int,
        next_action: str | None,
        due_at: datetime | None,
        occurred_at: datetime,
    ) -> AcquisitionAssignment:
        require_aware(occurred_at, "occurred_at")
        if self.state.status is AssignmentStatus.HANDED_OVER:
            raise DomainInvariantError(
                "assignment_handed_over_terminal",
                "Eine übergebene Zuordnung kann nicht mehr bearbeitet werden.",
            )
        if status is AssignmentStatus.HANDED_OVER:
            raise DomainInvariantError(
                "assignment_handover_required",
                "Der Status „übergeben“ entsteht ausschließlich durch eine Übergabe.",
            )
        normalized_next_action = (
            " ".join(next_action.split()) if next_action is not None else None
        )
        next_state = AssignmentState(
            status=status,
            priority=priority,
            next_action=normalized_next_action or None,
            due_at=due_at,
        )
        if next_state == self.state:
            return self
        return replace(
            self,
            state=next_state,
            revision=self.revision + 1,
            updated_at=occurred_at,
        )

    def hand_over(self, *, occurred_at: datetime) -> AcquisitionAssignment:
        require_aware(occurred_at, "occurred_at")
        if self.state.status is AssignmentStatus.HANDED_OVER:
            raise DomainInvariantError(
                "assignment_already_handed_over",
                "Diese Zuordnung wurde bereits übergeben.",
            )
        return replace(
            self,
            state=replace(self.state, status=AssignmentStatus.HANDED_OVER),
            revision=self.revision + 1,
            updated_at=occurred_at,
        )

    def record_activity(
        self,
        capture: ActivityCapture,
        *,
        occurred_at: datetime,
    ) -> AcquisitionAssignment:
        require_aware(occurred_at, "occurred_at")
        if self.state.status is AssignmentStatus.HANDED_OVER:
            raise DomainInvariantError(
                "assignment_handed_over_terminal",
                "Eine übergebene Zuordnung kann keine Aktivität erhalten.",
            )
        return replace(
            self,
            state=AssignmentState(
                status=capture.outcome.assignment_status(),
                priority=self.state.priority,
                next_action=capture.next_action,
                due_at=capture.due_at,
            ),
            revision=self.revision + 1,
            updated_at=occurred_at,
        )


@dataclass(frozen=True, slots=True)
class AssignmentHistoryEntry:
    id: UUID
    assignment_id: UUID
    changed_by_user_id: UUID
    changed_by_display_name: str
    previous_state: dict[str, object]
    new_state: dict[str, object]
    changed_at: datetime

    def __post_init__(self) -> None:
        if not self.changed_by_display_name.strip():
            raise DomainInvariantError(
                "assignment_history_actor_empty",
                "Ein Historieneintrag benötigt einen Anzeigenamen.",
            )
        require_aware(self.changed_at, "changed_at")
