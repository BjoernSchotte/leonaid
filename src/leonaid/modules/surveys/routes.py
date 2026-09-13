"""Survey transport; respondent credentials remain in HttpOnly cookies."""

from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Request, Response, Query


from leonaid.modules.surveys.api import SurveyService
from leonaid.modules.surveys.models import (
    Mutation,
    DraftValidation,
    SurveyDeletionResponse,
    TimeoutSettings,
    SurveyTimeoutSettings,
    SurveyAccess,
    SurveyInvitationCreate,
    SurveyInvitationResponse,
    SurveyInvitationsResponse,
    RedeemInvitation,
    SurveySchedule,
    TimeoutSettingsResponse,
    Transition,
    Duplicate,
    SurveySummaryResponse,
    SurveyListQuery,
    Create,
    SurveyListResponse,
    DraftSave,
    Start,
    AnswerSave,
    SurveyDraftResponse,
    SurveyVersionResponse,
    SurveyResponseSnapshot,
    SurveyParticipationResponse,
)
from leonaid.application.surveys.exports import (
    CreateSurveyExport,
    SurveyExportJob,
    SurveyExportSelection,
    SurveyExports,
)
from leonaid.application.surveys.analysis_snapshot import (
    AnalysisSnapshot,
    AnalysisVersions,
    CreateAnalysisSnapshot,
)
from leonaid.application.surveys.response_selection import (
    ResponseSelection,
    ResponseItems,
    IndividualResponse,
    FreeTextItems,
)
from leonaid.platform.http import ApiErrorResponse
from leonaid.domain.sessions import SESSION_COOKIE_NAME
from leonaid.domain.identity import IdentityPrincipal

router = APIRouter(
    prefix="/api/v1",
    tags=["surveys"],
    responses={
        code: {"model": ApiErrorResponse}
        for code in (401, 403, 404, 409, 413, 422, 429, 503)
    },
)


def service(request: Request) -> SurveyService:
    return cast(SurveyService, request.app.state.survey_service)


async def author(
    request: Request, survey_id: UUID, operation: str, body: dict[str, Any]
) -> dict[str, Any]:
    principal = await request.app.state.identity_service.authenticate(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    return await service(request).author(principal, survey_id, operation, body)


async def principal(request: Request) -> IdentityPrincipal:
    return cast(
        IdentityPrincipal,
        await request.app.state.identity_service.authenticate(
            request.cookies.get(SESSION_COOKIE_NAME)
        ),
    )


def cookie_name(participation_id: UUID | str) -> str:
    return f"__Host-survey_{participation_id}"


@router.post(
    "/surveys/{survey_id}/exports",
    operation_id="createSurveyExport",
    response_model=SurveyExportJob,
)
async def export_create(
    request: Request, response: Response, survey_id: UUID, body: CreateSurveyExport
) -> SurveyExportJob:
    principal = await request.app.state.identity_service.authenticate(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    response.headers["Cache-Control"] = "no-store"
    return await cast(SurveyExports, request.app.state.survey_exports).create(
        principal.account.id, survey_id, body
    )


@router.get(
    "/surveys/{survey_id}/exports/{job_id}",
    operation_id="getSurveyExport",
    response_model=SurveyExportJob,
)
async def export_get(
    request: Request, response: Response, survey_id: UUID, job_id: UUID
) -> SurveyExportJob:
    principal = await request.app.state.identity_service.authenticate(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    response.headers["Cache-Control"] = "no-store"
    return await cast(SurveyExports, request.app.state.survey_exports).get(
        principal.account.id, survey_id, job_id
    )


@router.get(
    "/surveys/{survey_id}/exports/{job_id}/download",
    operation_id="downloadSurveyExport",
    response_class=Response,
    responses={
        200: {
            "description": "Private survey artifact; current export permission is required.",
            "content": {
                media: {"schema": {"type": "string", "format": "binary"}}
                for media in (
                    "text/csv",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/pdf",
                )
            },
        }
    },
)
async def export_download(request: Request, survey_id: UUID, job_id: UUID) -> Response:
    principal = await request.app.state.identity_service.authenticate(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    artifact = await cast(SurveyExports, request.app.state.survey_exports).download(
        principal.account.id, survey_id, job_id
    )
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
        },
    )


@router.get(
    "/surveys/{survey_id}/export-selections/versions",
    operation_id="listSurveyExportVersions",
    response_model=AnalysisVersions,
)
async def export_selection_versions(
    survey_id: UUID, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(request, survey_id, "export-selection-versions", {})


@router.post(
    "/surveys/{survey_id}/export-selections",
    operation_id="createSurveyExportSelection",
    response_model=SurveyExportSelection,
)
async def export_selection_create(
    survey_id: UUID, body: CreateAnalysisSnapshot, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(
        request, survey_id, "export-selection-create", body.model_dump()
    )


@router.get(
    "/surveys/{survey_id}/analysis/versions",
    operation_id="listSurveyAnalysisVersions",
    response_model=AnalysisVersions,
)
async def analysis_versions(
    survey_id: UUID, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(request, survey_id, "analysis-versions", {})


@router.post(
    "/surveys/{survey_id}/analysis",
    operation_id="createSurveyAnalysis",
    response_model=AnalysisSnapshot,
)
async def analysis_create(
    survey_id: UUID, body: CreateAnalysisSnapshot, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(request, survey_id, "analysis-create", body.model_dump())


@router.get(
    "/surveys/{survey_id}/analysis/{snapshot_id}",
    operation_id="getSurveyAnalysis",
    response_model=AnalysisSnapshot,
)
async def analysis_get(
    survey_id: UUID, snapshot_id: UUID, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(
        request, survey_id, "analysis-get", {"snapshotId": str(snapshot_id)}
    )


@router.get(
    "/surveys/{survey_id}/response-selections/versions",
    operation_id="listSurveyResponseVersions",
    response_model=AnalysisVersions,
)
async def response_versions(
    survey_id: UUID, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(request, survey_id, "response-versions", {})


@router.post(
    "/surveys/{survey_id}/response-selections",
    operation_id="createSurveyResponseSelection",
    response_model=ResponseSelection,
)
async def response_selection_create(
    survey_id: UUID, body: CreateAnalysisSnapshot, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(request, survey_id, "response-create", body.model_dump())


@router.get(
    "/surveys/{survey_id}/response-selections/{snapshot_id}",
    operation_id="getSurveyResponseSelection",
    response_model=ResponseSelection,
)
async def response_selection_get(
    survey_id: UUID, snapshot_id: UUID, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(
        request, survey_id, "response-selection", {"snapshotId": str(snapshot_id)}
    )


@router.get(
    "/surveys/{survey_id}/response-selections/{snapshot_id}/responses",
    operation_id="listSurveyResponses",
    response_model=ResponseItems,
)
async def response_list(
    survey_id: UUID,
    snapshot_id: UUID,
    request: Request,
    response: Response,
    offset: int = Query(default=0, ge=0, le=5000),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(
        request,
        survey_id,
        "response-list",
        {"snapshotId": str(snapshot_id), "offset": offset},
    )


@router.get(
    "/surveys/{survey_id}/response-selections/{snapshot_id}/responses/{participation_id}",
    operation_id="getSurveyResponse",
    response_model=IndividualResponse,
)
async def response_individual(
    survey_id: UUID,
    snapshot_id: UUID,
    participation_id: UUID,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(
        request,
        survey_id,
        "response-individual",
        {"snapshotId": str(snapshot_id), "participationId": str(participation_id)},
    )


@router.get(
    "/surveys/{survey_id}/response-selections/{snapshot_id}/free-text/{question_id}",
    operation_id="listSurveyFreeText",
    response_model=FreeTextItems,
)
async def response_free_text(
    survey_id: UUID,
    snapshot_id: UUID,
    question_id: str,
    request: Request,
    response: Response,
    offset: int = Query(default=0, ge=0, le=5000),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(
        request,
        survey_id,
        "response-free-text",
        {"snapshotId": str(snapshot_id), "questionId": question_id, "offset": offset},
    )


@router.get("/surveys", operation_id="listSurveys", response_model=SurveyListResponse)
async def list_surveys(
    request: Request,
    response: Response,
    status: Literal["draft", "active", "ended", "archived", "deleted"] | None = None,
    search: str = Query(default="", max_length=240),
    offset: int = Query(default=0, ge=0),
) -> SurveyListResponse:
    response.headers["Cache-Control"] = "no-store"
    principal = await request.app.state.identity_service.authenticate(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    return await service(request).list_surveys(
        principal, SurveyListQuery(status=status, search=search, offset=offset)
    )


@router.get(
    "/survey-settings",
    operation_id="getSurveySettings",
    response_model=TimeoutSettingsResponse,
)
async def settings(request: Request, response: Response) -> TimeoutSettingsResponse:
    response.headers["Cache-Control"] = "no-store"
    principal = await request.app.state.identity_service.authenticate(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    return await service(request).get_settings(principal)


@router.put(
    "/survey-settings",
    operation_id="updateSurveySettings",
    response_model=TimeoutSettingsResponse,
)
async def update_settings(
    body: TimeoutSettings, request: Request, response: Response
) -> TimeoutSettingsResponse:
    response.headers["Cache-Control"] = "no-store"
    principal = await request.app.state.identity_service.authenticate(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    return await service(request).update_settings(principal, body)


@router.put(
    "/surveys/{survey_id}/settings",
    operation_id="updateSurveyTimeout",
    response_model=SurveySummaryResponse,
)
async def update_survey_timeout(
    survey_id: UUID, body: SurveyTimeoutSettings, request: Request, response: Response
) -> SurveySummaryResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).update_timeout(
        await principal(request), survey_id, body
    )


@router.put(
    "/surveys/{survey_id}/schedule",
    operation_id="scheduleSurveyEnd",
    response_model=SurveySummaryResponse,
)
async def schedule_end(
    survey_id: UUID, body: SurveySchedule, request: Request, response: Response
) -> SurveySummaryResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).schedule_end(
        await principal(request), survey_id, body
    )


@router.post(
    "/surveys/{survey_id}",
    operation_id="createSurvey",
    response_model=SurveyDraftResponse,
)
async def create(
    survey_id: UUID, body: Create, request: Request
) -> SurveyDraftResponse:
    return await service(request).create_survey(
        await principal(request), survey_id, body
    )


@router.get(
    "/surveys/{survey_id}",
    operation_id="getSurvey",
    response_model=SurveySummaryResponse,
)
async def summary(
    survey_id: UUID, request: Request, response: Response
) -> SurveySummaryResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).get_survey(await principal(request), survey_id)


@router.post(
    "/surveys/{survey_id}/delete-permanently",
    operation_id="deleteSurveyPermanently",
    response_model=SurveyDeletionResponse,
)
async def delete_permanently(
    survey_id: UUID, body: Mutation, request: Request, response: Response
) -> SurveyDeletionResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).delete_permanently(
        await principal(request), survey_id, body
    )


@router.get(
    "/surveys/{survey_id}/deletion",
    operation_id="getSurveyDeletion",
    response_model=SurveyDeletionResponse,
)
async def deletion_status(
    survey_id: UUID, request: Request, response: Response
) -> SurveyDeletionResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).get_deletion_status(
        await principal(request), survey_id
    )


@router.post(
    "/surveys/{survey_id}/transition",
    operation_id="transitionSurvey",
    response_model=SurveySummaryResponse,
)
async def transition(
    survey_id: UUID, body: Transition, request: Request
) -> SurveySummaryResponse:
    return await service(request).transition(await principal(request), survey_id, body)


@router.post(
    "/surveys/{survey_id}/duplicate",
    operation_id="duplicateSurvey",
    response_model=SurveySummaryResponse,
)
async def duplicate(
    survey_id: UUID, body: Duplicate, request: Request
) -> SurveySummaryResponse:
    return await service(request).duplicate(await principal(request), survey_id, body)


@router.get(
    "/surveys/{survey_id}/draft",
    operation_id="getSurveyDraft",
    response_model=SurveyDraftResponse,
)
async def draft(
    survey_id: UUID, request: Request, response: Response
) -> SurveyDraftResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).get_draft(await principal(request), survey_id)


@router.get(
    "/surveys/{survey_id}/publication",
    operation_id="getSurveyPublicationDraft",
    response_model=SurveyDraftResponse,
)
async def publication_draft(
    survey_id: UUID, request: Request, response: Response
) -> SurveyDraftResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).get_publication_draft(
        await principal(request), survey_id
    )


@router.post(
    "/surveys/{survey_id}/draft/validate",
    operation_id="validateSurveyDraft",
    response_model=SurveyDraftResponse,
)
async def validate_draft(
    survey_id: UUID, body: DraftValidation, request: Request, response: Response
) -> SurveyDraftResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).validate_draft(
        await principal(request), survey_id, body
    )


@router.put(
    "/surveys/{survey_id}/draft",
    operation_id="saveSurveyDraft",
    response_model=SurveyDraftResponse,
)
async def save_draft(
    survey_id: UUID, body: DraftSave, request: Request
) -> SurveyDraftResponse:
    return await service(request).save_draft(await principal(request), survey_id, body)


@router.post(
    "/surveys/{survey_id}/publish",
    operation_id="publishSurvey",
    response_model=SurveyVersionResponse,
)
async def publish(
    survey_id: UUID, body: Mutation, request: Request
) -> SurveyVersionResponse:
    return await service(request).publish(await principal(request), survey_id, body)


@router.put(
    "/surveys/{survey_id}/access",
    operation_id="updateSurveyAccess",
    response_model=SurveySummaryResponse,
)
async def update_access(
    survey_id: UUID, body: SurveyAccess, request: Request, response: Response
) -> SurveySummaryResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).update_access(
        await principal(request), survey_id, body
    )


@router.get(
    "/surveys/{survey_id}/invitations",
    operation_id="listSurveyInvitations",
    response_model=SurveyInvitationsResponse,
)
async def list_invitations(
    survey_id: UUID,
    request: Request,
    response: Response,
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(request, survey_id, "invitation-list", {"offset": offset})


@router.post(
    "/surveys/{survey_id}/invitations",
    operation_id="createSurveyInvitation",
    response_model=SurveyInvitationResponse,
)
async def create_invitation(
    survey_id: UUID, body: SurveyInvitationCreate, request: Request, response: Response
) -> SurveyInvitationResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).create_invitation(
        await principal(request), survey_id, body
    )


@router.post(
    "/surveys/{survey_id}/invitations/{invitation_id}/revoke",
    operation_id="revokeSurveyInvitation",
    response_model=SurveyInvitationResponse,
)
async def revoke_invitation(
    survey_id: UUID,
    invitation_id: UUID,
    body: Mutation,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(
        request,
        survey_id,
        "invitation-revoke",
        {**body.model_dump(), "invitationId": str(invitation_id)},
    )


@router.post(
    "/public/surveys/{survey_id}/invitation/redeem",
    operation_id="redeemSurveyInvitation",
    response_model=SurveyParticipationResponse,
)
async def redeem_invitation(
    survey_id: UUID, body: RedeemInvitation, request: Request, response: Response
) -> dict[str, Any]:
    result = await service(request).participate(
        survey_id, None, "redeem", {}, body.token
    )
    response.set_cookie(
        cookie_name(result["id"]),
        body.token,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=90 * 86400,
    )
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get(
    "/public/surveys/{survey_id}",
    operation_id="getPublicSurvey",
    response_model=SurveyVersionResponse,
)
async def definition(
    survey_id: UUID, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).participate(survey_id, None, "definition", {}, "")


@router.post(
    "/public/surveys/{survey_id}/participations",
    operation_id="startSurveyParticipation",
    response_model=SurveyParticipationResponse,
)
async def start(
    survey_id: UUID, body: Start, request: Request, response: Response
) -> dict[str, Any]:
    result = await service(request).participate(
        survey_id,
        None,
        "start",
        body.model_dump(exclude={"resumeSecret"}),
        body.resumeSecret,
    )
    response.set_cookie(
        cookie_name(result["id"]),
        body.resumeSecret,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=90 * 86400,
    )
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get(
    "/public/surveys/{survey_id}/participations/{participation_id}",
    operation_id="restoreSurveyParticipation",
    response_model=SurveyParticipationResponse,
)
async def restore(
    survey_id: UUID, participation_id: UUID, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).participate(
        survey_id,
        participation_id,
        "restore",
        {},
        request.cookies.get(cookie_name(participation_id), ""),
    )


@router.put(
    "/public/surveys/{survey_id}/participations/{participation_id}",
    operation_id="saveSurveyResponse",
    response_model=SurveyResponseSnapshot,
)
async def save(
    survey_id: UUID,
    participation_id: UUID,
    body: AnswerSave,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).participate(
        survey_id,
        participation_id,
        "save",
        body.model_dump(),
        request.cookies.get(cookie_name(participation_id), ""),
    )


@router.post(
    "/public/surveys/{survey_id}/participations/{participation_id}/complete",
    operation_id="completeSurveyResponse",
    response_model=SurveyResponseSnapshot,
)
async def complete(
    survey_id: UUID,
    participation_id: UUID,
    body: Mutation,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).participate(
        survey_id,
        participation_id,
        "complete",
        body.model_dump(),
        request.cookies.get(cookie_name(participation_id), ""),
    )
