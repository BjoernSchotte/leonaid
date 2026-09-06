"""Survey lifecycle and access invariants independent of persistence."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal, require_aware
from leonaid.domain.policies import may_manage_action


class SurveyStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ENDED = "ended"
    ARCHIVED = "archived"
    DELETED = "deleted"


class Capability(StrEnum):
    DESIGN = "design"
    PUBLISH = "publish"
    ARCHIVE = "archive"
    VIEW_AGGREGATES = "view_aggregates"
    READ_RESPONSES = "read_responses"
    EXPORT_RAW = "export_raw"
    EXPORT_REPORTS = "export_reports"
    MANAGE_INVITATIONS = "manage_invitations"
    DELETE = "delete"


def require_transition(
    current: SurveyStatus, target: SurveyStatus, *, has_published_version: bool
) -> None:
    allowed = {
        SurveyStatus.DRAFT: {SurveyStatus.ACTIVE, SurveyStatus.DELETED},
        SurveyStatus.ACTIVE: {SurveyStatus.ENDED, SurveyStatus.DELETED},
        SurveyStatus.ENDED: {SurveyStatus.ARCHIVED, SurveyStatus.DELETED},
        SurveyStatus.ARCHIVED: {SurveyStatus.ENDED, SurveyStatus.DELETED},
        SurveyStatus.DELETED: {
            SurveyStatus.ENDED if has_published_version else SurveyStatus.DRAFT
        },
    }
    if target not in allowed[current]:
        raise DomainInvariantError(
            "survey_transition_invalid", "Dieser Statuswechsel ist nicht erlaubt."
        )


def effective_response_status(
    status: str,
    *,
    created_at: datetime,
    last_answer_changed_at: datetime | None,
    timeout_seconds: int,
    now: datetime,
) -> str:
    for value in (created_at, last_answer_changed_at, now):
        if value is not None:
            require_aware(value, "survey timestamp")
    if not 1 <= timeout_seconds <= 604800:
        raise DomainInvariantError("survey_timeout_invalid", "Ungültiger Zeitraum.")
    if status == "completed":
        return status
    if status not in {"in_progress", "partial"}:
        raise DomainInvariantError(
            "survey_response_status_invalid", "Ungültiger Status."
        )
    changed_at = last_answer_changed_at or created_at
    return (
        "partial"
        if now >= changed_at + timedelta(seconds=timeout_seconds)
        else "in_progress"
    )


def may_access_survey(
    principal: IdentityPrincipal,
    *,
    owner_user_id: UUID,
    action_id: UUID | None,
    capability: Capability,
    grants: frozenset[Capability],
) -> bool:
    if not principal.account.can_authenticate:
        return False
    if principal.is_system_admin:
        return True
    if action_id is not None:
        if may_manage_action(principal, action_id):
            return True
        # Explicit survey grants cannot bypass the linked action's membership scope.
        if not principal.roles_for(action_id):
            return False
    return principal.account.id == owner_user_id or capability in grants
