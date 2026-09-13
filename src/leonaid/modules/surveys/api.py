"""Survey use cases expose a persistence port, independent of HTTP."""

from typing import Any, Protocol
from uuid import UUID

from leonaid.domain.identity import IdentityPrincipal
from leonaid.platform.navigation import NavigationItem
from leonaid.modules.surveys.models import (
    SurveyListQuery,
    SurveyListResponse,
    TimeoutSettings,
    TimeoutSettingsResponse,
    Create,
    DraftSave,
    DraftValidation,
    Duplicate,
    Mutation,
    SurveyAccess,
    SurveyDeletionResponse,
    SurveyDraftResponse,
    SurveyInvitationCreate,
    SurveyInvitationResponse,
    SurveySchedule,
    SurveySummaryResponse,
    SurveyTimeoutSettings,
    SurveyVersionResponse,
    Transition,
)


class SurveyRepository(Protocol):
    async def list_surveys(
        self, actor: IdentityPrincipal, status: str | None, search: str, offset: int
    ) -> dict[str, Any]: ...
    async def settings(
        self, actor: IdentityPrincipal, body: dict[str, Any] | None
    ) -> dict[str, Any]: ...

    async def author(
        self,
        actor: IdentityPrincipal,
        survey_id: UUID,
        operation: str,
        body: dict[str, Any],
    ) -> dict[str, Any]: ...
    async def participate(
        self,
        survey_id: UUID,
        participation_id: UUID | None,
        operation: str,
        body: dict[str, Any],
        secret: str,
    ) -> dict[str, Any]: ...


class SurveyService:
    def __init__(self, repository: SurveyRepository):
        self.repository = repository

    async def list_surveys(
        self, actor: IdentityPrincipal, query: SurveyListQuery
    ) -> SurveyListResponse:
        query = SurveyListQuery.model_validate(query)
        result = await self.repository.list_surveys(
            actor, query.status, query.search, query.offset
        )
        return SurveyListResponse.model_validate(result)

    async def get_settings(self, actor: IdentityPrincipal) -> TimeoutSettingsResponse:
        return TimeoutSettingsResponse.model_validate(
            await self.repository.settings(actor, None)
        )

    async def update_settings(
        self, actor: IdentityPrincipal, body: TimeoutSettings
    ) -> TimeoutSettingsResponse:
        body = TimeoutSettings.model_validate(body)
        result = await self.repository.settings(
            actor, body.model_dump(exclude_unset=True)
        )
        return TimeoutSettingsResponse.model_validate(result)

    async def author(
        self,
        actor: IdentityPrincipal,
        survey_id: UUID,
        operation: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.repository.author(actor, survey_id, operation, body)

    async def participate(
        self,
        survey_id: UUID,
        participation_id: UUID | None,
        operation: str,
        body: dict[str, Any],
        secret: str,
    ) -> dict[str, Any]:
        return await self.repository.participate(
            survey_id, participation_id, operation, body, secret
        )

    async def create_survey(
        self, actor: IdentityPrincipal, survey_id: UUID, body: Create
    ) -> SurveyDraftResponse:
        body = Create.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "create", body.model_dump()
        )
        return SurveyDraftResponse.model_validate(result)

    async def get_survey(
        self, actor: IdentityPrincipal, survey_id: UUID
    ) -> SurveySummaryResponse:
        result = await self.repository.author(actor, survey_id, "summary", {})
        return SurveySummaryResponse.model_validate(result)

    async def get_draft(
        self, actor: IdentityPrincipal, survey_id: UUID
    ) -> SurveyDraftResponse:
        result = await self.repository.author(actor, survey_id, "draft", {})
        return SurveyDraftResponse.model_validate(result)

    async def get_publication_draft(
        self, actor: IdentityPrincipal, survey_id: UUID
    ) -> SurveyDraftResponse:
        result = await self.repository.author(actor, survey_id, "publication", {})
        return SurveyDraftResponse.model_validate(result)

    async def validate_draft(
        self, actor: IdentityPrincipal, survey_id: UUID, body: DraftValidation
    ) -> SurveyDraftResponse:
        body = DraftValidation.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "validate", body.model_dump()
        )
        return SurveyDraftResponse.model_validate(result)

    async def save_draft(
        self, actor: IdentityPrincipal, survey_id: UUID, body: DraftSave
    ) -> SurveyDraftResponse:
        body = DraftSave.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "save", body.model_dump()
        )
        return SurveyDraftResponse.model_validate(result)

    async def publish(
        self, actor: IdentityPrincipal, survey_id: UUID, body: Mutation
    ) -> SurveyVersionResponse:
        body = Mutation.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "publish", body.model_dump()
        )
        return SurveyVersionResponse.model_validate(result)

    async def transition(
        self, actor: IdentityPrincipal, survey_id: UUID, body: Transition
    ) -> SurveySummaryResponse:
        body = Transition.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "transition", body.model_dump()
        )
        return SurveySummaryResponse.model_validate(result)

    async def duplicate(
        self, actor: IdentityPrincipal, survey_id: UUID, body: Duplicate
    ) -> SurveySummaryResponse:
        body = Duplicate.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "duplicate", body.model_dump()
        )
        return SurveySummaryResponse.model_validate(result)

    async def update_timeout(
        self, actor: IdentityPrincipal, survey_id: UUID, body: SurveyTimeoutSettings
    ) -> SurveySummaryResponse:
        body = SurveyTimeoutSettings.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "settings", body.model_dump()
        )
        return SurveySummaryResponse.model_validate(result)

    async def schedule_end(
        self, actor: IdentityPrincipal, survey_id: UUID, body: SurveySchedule
    ) -> SurveySummaryResponse:
        body = SurveySchedule.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "schedule", body.model_dump()
        )
        return SurveySummaryResponse.model_validate(result)

    async def update_access(
        self, actor: IdentityPrincipal, survey_id: UUID, body: SurveyAccess
    ) -> SurveySummaryResponse:
        body = SurveyAccess.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "access", body.model_dump()
        )
        return SurveySummaryResponse.model_validate(result)

    async def create_invitation(
        self, actor: IdentityPrincipal, survey_id: UUID, body: SurveyInvitationCreate
    ) -> SurveyInvitationResponse:
        body = SurveyInvitationCreate.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "invitation-create", body.model_dump()
        )
        return SurveyInvitationResponse.model_validate(result)

    async def delete_permanently(
        self, actor: IdentityPrincipal, survey_id: UUID, body: Mutation
    ) -> SurveyDeletionResponse:
        body = Mutation.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "delete-permanently", body.model_dump()
        )
        return SurveyDeletionResponse.model_validate(result)

    async def get_deletion_status(
        self, actor: IdentityPrincipal, survey_id: UUID
    ) -> SurveyDeletionResponse:
        result = await self.repository.author(actor, survey_id, "deletion-status", {})
        return SurveyDeletionResponse.model_validate(result)


def navigation(actor: IdentityPrincipal) -> tuple[NavigationItem, ...]:
    if not actor.account.can_authenticate:
        return ()
    return (NavigationItem("surveys", "Umfragen", "/admin/surveys", "web"),)
