"""Survey use cases expose a persistence port, independent of HTTP."""

from leonaid.application.surveys.analysis_snapshot import (
    AnalysisVersions,
    AnalysisSnapshot,
    CreateAnalysisSnapshot,
)
from leonaid.application.surveys.response_selection import (
    ResponseSelection,
    ResponseItems,
    IndividualResponse,
    FreeTextItems,
)
from leonaid.application.surveys.exports import (
    SurveyExportSelection,
    SurveyExports,
    CreateSurveyExport,
    SurveyExportJob,
)
from leonaid.modules.surveys.models import (
    SnapshotReference,
    ResponsePage,
    IndividualResponseQuery,
    FreeTextQuery,
    InvitationPage,
    RevokeInvitation,
    SurveyInvitationsResponse,
)
from leonaid.modules.surveys.models import (
    Start,
    RedeemInvitation,
    AnswerSave,
    SurveyParticipationResponse,
    SurveyResponseSnapshot,
)
from leonaid.application.surveys.export_rendering import SurveyExportArtifact
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

    async def list_export_versions(
        self, actor: IdentityPrincipal, survey_id: UUID
    ) -> AnalysisVersions:
        result = await self.repository.author(
            actor, survey_id, "export-selection-versions", {}
        )
        return AnalysisVersions.model_validate(result)

    async def create_export_selection(
        self, actor: IdentityPrincipal, survey_id: UUID, body: CreateAnalysisSnapshot
    ) -> SurveyExportSelection:
        body = CreateAnalysisSnapshot.model_validate(body.model_dump())
        result = await self.repository.author(
            actor, survey_id, "export-selection-create", body.model_dump(mode="json")
        )
        return SurveyExportSelection.model_validate(result)

    async def list_analysis_versions(
        self, actor: IdentityPrincipal, survey_id: UUID
    ) -> AnalysisVersions:
        result = await self.repository.author(actor, survey_id, "analysis-versions", {})
        return AnalysisVersions.model_validate(result)

    async def create_analysis(
        self, actor: IdentityPrincipal, survey_id: UUID, body: CreateAnalysisSnapshot
    ) -> AnalysisSnapshot:
        body = CreateAnalysisSnapshot.model_validate(body.model_dump())
        result = await self.repository.author(
            actor, survey_id, "analysis-create", body.model_dump(mode="json")
        )
        return AnalysisSnapshot.model_validate(result)

    async def get_analysis(
        self, actor: IdentityPrincipal, survey_id: UUID, body: SnapshotReference
    ) -> AnalysisSnapshot:
        body = SnapshotReference.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "analysis-get", body.model_dump(mode="json")
        )
        return AnalysisSnapshot.model_validate(result)

    async def list_response_versions(
        self, actor: IdentityPrincipal, survey_id: UUID
    ) -> AnalysisVersions:
        result = await self.repository.author(actor, survey_id, "response-versions", {})
        return AnalysisVersions.model_validate(result)

    async def create_response_selection(
        self, actor: IdentityPrincipal, survey_id: UUID, body: CreateAnalysisSnapshot
    ) -> ResponseSelection:
        body = CreateAnalysisSnapshot.model_validate(body.model_dump())
        result = await self.repository.author(
            actor, survey_id, "response-create", body.model_dump(mode="json")
        )
        return ResponseSelection.model_validate(result)

    async def get_response_selection(
        self, actor: IdentityPrincipal, survey_id: UUID, body: SnapshotReference
    ) -> ResponseSelection:
        body = SnapshotReference.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "response-selection", body.model_dump(mode="json")
        )
        return ResponseSelection.model_validate(result)

    async def list_responses(
        self, actor: IdentityPrincipal, survey_id: UUID, body: ResponsePage
    ) -> ResponseItems:
        body = ResponsePage.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "response-list", body.model_dump(mode="json")
        )
        return ResponseItems.model_validate(result)

    async def get_response(
        self, actor: IdentityPrincipal, survey_id: UUID, body: IndividualResponseQuery
    ) -> IndividualResponse:
        body = IndividualResponseQuery.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "response-individual", body.model_dump(mode="json")
        )
        return IndividualResponse.model_validate(result)

    async def list_free_text(
        self, actor: IdentityPrincipal, survey_id: UUID, body: FreeTextQuery
    ) -> FreeTextItems:
        body = FreeTextQuery.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "response-free-text", body.model_dump(mode="json")
        )
        return FreeTextItems.model_validate(result)

    async def list_invitations(
        self, actor: IdentityPrincipal, survey_id: UUID, body: InvitationPage
    ) -> SurveyInvitationsResponse:
        body = InvitationPage.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "invitation-list", body.model_dump(mode="json")
        )
        return SurveyInvitationsResponse.model_validate(result)

    async def revoke_invitation(
        self, actor: IdentityPrincipal, survey_id: UUID, body: RevokeInvitation
    ) -> SurveyInvitationResponse:
        body = RevokeInvitation.model_validate(body)
        result = await self.repository.author(
            actor, survey_id, "invitation-revoke", body.model_dump(mode="json")
        )
        return SurveyInvitationResponse.model_validate(result)

    async def get_public_definition(self, survey_id: UUID) -> SurveyVersionResponse:
        result = await self.repository.participate(
            survey_id, None, "definition", {}, ""
        )
        return SurveyVersionResponse.model_validate(result)

    async def start_participation(
        self, survey_id: UUID, body: Start
    ) -> SurveyParticipationResponse:
        body = Start.model_validate(body)
        result = await self.repository.participate(
            survey_id,
            None,
            "start",
            body.model_dump(exclude={"resumeSecret"}),
            body.resumeSecret,
        )
        return SurveyParticipationResponse.model_validate(result)

    async def redeem_invitation(
        self, survey_id: UUID, body: RedeemInvitation
    ) -> SurveyParticipationResponse:
        body = RedeemInvitation.model_validate(body)
        result = await self.repository.participate(
            survey_id, None, "redeem", {}, body.token
        )
        return SurveyParticipationResponse.model_validate(result)

    async def restore_participation(
        self, survey_id: UUID, participation_id: UUID, secret: str
    ) -> SurveyParticipationResponse:
        result = await self.repository.participate(
            survey_id, participation_id, "restore", {}, secret
        )
        return SurveyParticipationResponse.model_validate(result)

    async def save_response(
        self, survey_id: UUID, participation_id: UUID, body: AnswerSave, secret: str
    ) -> SurveyResponseSnapshot:
        body = AnswerSave.model_validate(body)
        result = await self.repository.participate(
            survey_id, participation_id, "save", body.model_dump(), secret
        )
        return SurveyResponseSnapshot.model_validate(result)

    async def complete_response(
        self, survey_id: UUID, participation_id: UUID, body: Mutation, secret: str
    ) -> SurveyResponseSnapshot:
        body = Mutation.model_validate(body)
        result = await self.repository.participate(
            survey_id, participation_id, "complete", body.model_dump(), secret
        )
        return SurveyResponseSnapshot.model_validate(result)


class SurveyExportService:
    """Validated export operations; the port rechecks current database permissions."""

    def __init__(self, exports: SurveyExports):
        self._exports = exports

    async def create_export(
        self, actor: IdentityPrincipal, survey_id: UUID, body: CreateSurveyExport
    ) -> SurveyExportJob:
        body = CreateSurveyExport.model_validate(body.model_dump())
        return await self._exports.create(actor.account.id, survey_id, body)

    async def get_export(
        self, actor: IdentityPrincipal, survey_id: UUID, job_id: UUID
    ) -> SurveyExportJob:
        return await self._exports.get(actor.account.id, survey_id, job_id)

    async def download_export(
        self, actor: IdentityPrincipal, survey_id: UUID, job_id: UUID
    ) -> SurveyExportArtifact:
        return await self._exports.download(actor.account.id, survey_id, job_id)


def navigation(actor: IdentityPrincipal) -> tuple[NavigationItem, ...]:
    if not actor.account.can_authenticate:
        return ()
    return (NavigationItem("surveys", "Umfragen", "/admin/surveys", "web"),)


__all__ = [
    "SurveyService",
    "SurveyExportService",
    "navigation",
    "AnalysisSnapshot",
    "AnalysisVersions",
    "AnswerSave",
    "Create",
    "CreateAnalysisSnapshot",
    "CreateSurveyExport",
    "DraftSave",
    "DraftValidation",
    "Duplicate",
    "FreeTextItems",
    "FreeTextQuery",
    "IndividualResponse",
    "IndividualResponseQuery",
    "InvitationPage",
    "Mutation",
    "RedeemInvitation",
    "ResponseItems",
    "ResponsePage",
    "ResponseSelection",
    "RevokeInvitation",
    "SnapshotReference",
    "Start",
    "SurveyAccess",
    "SurveyDeletionResponse",
    "SurveyDraftResponse",
    "SurveyExportArtifact",
    "SurveyExportJob",
    "SurveyExportSelection",
    "SurveyInvitationCreate",
    "SurveyInvitationResponse",
    "SurveyInvitationsResponse",
    "SurveyListQuery",
    "SurveyListResponse",
    "SurveyParticipationResponse",
    "SurveyResponseSnapshot",
    "SurveySchedule",
    "SurveySummaryResponse",
    "SurveyTimeoutSettings",
    "SurveyVersionResponse",
    "TimeoutSettings",
    "TimeoutSettingsResponse",
    "Transition",
]
