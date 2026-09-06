"""Survey transport; respondent credentials remain in HttpOnly cookies."""

from typing import Any, Literal, Self, cast
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Request, Response, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
    field_validator,
    EmailStr,
)

from leonaid.application.surveys import SurveyService
from leonaid.entrypoints.fastapi.schemas import ApiErrorResponse
from leonaid.domain.sessions import SESSION_COOKIE_NAME
from leonaid.domain.surveys.validation import json_size

router = APIRouter(
    prefix="/api/v1",
    tags=["surveys"],
    responses={
        code: {"model": ApiErrorResponse}
        for code in (401, 403, 404, 409, 422, 429, 503)
    },
)


class SurveyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Mutation(SurveyInput):
    operationId: str = Field(min_length=1, max_length=128)
    expectedRevision: int = Field(ge=1)


class DraftValidation(SurveyInput):
    expectedRevision: int = Field(ge=1)


class TimeoutSettings(Mutation):
    inactivityTimeoutSeconds: int = Field(ge=1, le=604800)


class SurveyTimeoutSettings(Mutation):
    inactivityTimeoutSeconds: int | None = Field(ge=1, le=604800)


class SurveyAccess(Mutation):
    accessMode: Literal["anonymous", "invitation"]


class SurveyInvitationCreate(Mutation):
    recipientEmail: EmailStr = Field(max_length=254)
    recipientName: str = Field(default="", max_length=160)
    expiresInDays: int = Field(default=30, ge=1, le=90)


class SurveyInvitationResponse(SurveyInput):
    id: str
    recipientEmail: str
    recipientName: str
    status: Literal[
        "queued",
        "retrying",
        "failed",
        "cancelled",
        "sent",
        "redeemed",
        "expired",
        "revoked",
    ]
    expiresAt: str
    createdAt: str


class SurveyInvitationsResponse(SurveyInput):
    items: list[SurveyInvitationResponse]
    total: int


class RedeemInvitation(SurveyInput):
    token: str = Field(min_length=32, max_length=256)


class SurveySchedule(Mutation):
    endsAt: str | None = Field(max_length=40)

    @field_validator("endsAt")
    @classmethod
    def aware_end(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        if "T" not in value or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("End time requires an explicit time zone")
        return parsed.astimezone(timezone.utc).isoformat()


class TimeoutSettingsResponse(SurveyInput):
    inactivityTimeoutSeconds: int
    revision: int


class Transition(Mutation):
    action: Literal["end", "archive", "unarchive", "trash", "restore"]


class Duplicate(Mutation):
    targetSurveyId: str = Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )
    title: str = Field(min_length=1, max_length=240, pattern=r"\S")


class SurveySummaryResponse(SurveyInput):
    id: str
    title: str
    actionId: str | None
    ownerUserId: str
    accessMode: Literal["anonymous", "invitation"]
    capabilities: list[str] = Field(default_factory=list)
    status: Literal["draft", "active", "ended", "archived", "deleted"]
    revision: int
    publishedVersionId: str | None
    inactivityTimeoutSeconds: int | None
    endsAt: str | None
    deletedAt: str | None


class DefinitionInput(SurveyInput):
    definition: dict[str, Any]

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if json_size(self.definition) > 262144:
            raise ValueError("Definition too large")
        return self


class Create(DefinitionInput):
    operationId: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=240, pattern=r"\S")
    inactivityTimeoutSeconds: int | None = Field(default=None, ge=1, le=604800)
    actionId: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
    )


class SurveyActionOption(SurveyInput):
    id: str
    name: str


class SurveyListResponse(SurveyInput):
    items: list[SurveySummaryResponse]
    total: int
    actions: list[SurveyActionOption]


class DraftSave(Mutation, DefinitionInput):
    pass


class Start(SurveyInput):
    operationId: str = Field(min_length=1, max_length=128)
    resumeSecret: str = Field(
        min_length=32, max_length=256, pattern=r"^[A-Za-z0-9_-]+$"
    )


class AnswerSave(Mutation):
    answers: dict[str, Any]
    currentPage: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if json_size(self.answers) > 262144:
            raise ValueError("Answers too large")
        return self


class SurveyDraftResponse(SurveyInput):
    surveyId: str
    revision: int
    definition: dict[str, Any]


class SurveyVersionResponse(SurveyInput):
    id: str
    surveyId: str
    number: int
    definition: dict[str, Any]
    rendererVersion: str
    capabilityProfile: str
    publishedAt: str


class SurveyDiagnostic(SurveyInput):
    path: str
    code: str
    message: str
    severity: Literal["error", "warning", "information"]


class SurveyResponseSnapshot(SurveyInput):
    participationId: str
    versionId: str
    revision: int
    status: Literal["in_progress", "partial", "completed"]
    answers: dict[str, Any]
    currentPage: str | None
    lastAnswerChangedAt: str | None
    completedAt: str | None
    diagnostics: list[SurveyDiagnostic]


class SurveyParticipationResponse(SurveyInput):
    id: str
    version: SurveyVersionResponse
    response: SurveyResponseSnapshot
    inactivityTimeoutSeconds: int


def service(request: Request) -> SurveyService:
    return cast(SurveyService, request.app.state.survey_service)


async def author(
    request: Request, survey_id: UUID, operation: str, body: dict[str, Any]
) -> dict[str, Any]:
    principal = await request.app.state.identity_service.authenticate(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    return await service(request).author(principal, survey_id, operation, body)


def cookie_name(participation_id: UUID | str) -> str:
    return f"__Host-survey_{participation_id}"


@router.get("/surveys", operation_id="listSurveys", response_model=SurveyListResponse)
async def list_surveys(
    request: Request,
    response: Response,
    status: Literal["draft", "active", "ended", "archived", "deleted"] | None = None,
    search: str = Query(default="", max_length=240),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    principal = await request.app.state.identity_service.authenticate(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    return await service(request).list_surveys(principal, status, search, offset)


@router.get(
    "/survey-settings",
    operation_id="getSurveySettings",
    response_model=TimeoutSettingsResponse,
)
async def settings(request: Request, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    principal = await request.app.state.identity_service.authenticate(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    return await service(request).settings(principal, None)


@router.put(
    "/survey-settings",
    operation_id="updateSurveySettings",
    response_model=TimeoutSettingsResponse,
)
async def update_settings(
    body: TimeoutSettings, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    principal = await request.app.state.identity_service.authenticate(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    return await service(request).settings(principal, body.model_dump())


@router.put(
    "/surveys/{survey_id}/settings",
    operation_id="updateSurveyTimeout",
    response_model=SurveySummaryResponse,
)
async def update_survey_timeout(
    survey_id: UUID, body: SurveyTimeoutSettings, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(request, survey_id, "settings", body.model_dump())


@router.put(
    "/surveys/{survey_id}/schedule",
    operation_id="scheduleSurveyEnd",
    response_model=SurveySummaryResponse,
)
async def schedule_end(
    survey_id: UUID, body: SurveySchedule, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(request, survey_id, "schedule", body.model_dump())


@router.post(
    "/surveys/{survey_id}",
    operation_id="createSurvey",
    response_model=SurveyDraftResponse,
)
async def create(survey_id: UUID, body: Create, request: Request) -> dict[str, Any]:
    return await author(request, survey_id, "create", body.model_dump())


@router.get(
    "/surveys/{survey_id}",
    operation_id="getSurvey",
    response_model=SurveySummaryResponse,
)
async def summary(
    survey_id: UUID, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(request, survey_id, "summary", {})


@router.post(
    "/surveys/{survey_id}/transition",
    operation_id="transitionSurvey",
    response_model=SurveySummaryResponse,
)
async def transition(
    survey_id: UUID, body: Transition, request: Request
) -> dict[str, Any]:
    return await author(request, survey_id, "transition", body.model_dump())


@router.post(
    "/surveys/{survey_id}/duplicate",
    operation_id="duplicateSurvey",
    response_model=SurveySummaryResponse,
)
async def duplicate(
    survey_id: UUID, body: Duplicate, request: Request
) -> dict[str, Any]:
    return await author(request, survey_id, "duplicate", body.model_dump())


@router.get(
    "/surveys/{survey_id}/draft",
    operation_id="getSurveyDraft",
    response_model=SurveyDraftResponse,
)
async def draft(
    survey_id: UUID, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(request, survey_id, "draft", {})


@router.post(
    "/surveys/{survey_id}/draft/validate",
    operation_id="validateSurveyDraft",
    response_model=SurveyDraftResponse,
)
async def validate_draft(
    survey_id: UUID, body: DraftValidation, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(request, survey_id, "validate", body.model_dump())


@router.put(
    "/surveys/{survey_id}/draft",
    operation_id="saveSurveyDraft",
    response_model=SurveyDraftResponse,
)
async def save_draft(
    survey_id: UUID, body: DraftSave, request: Request
) -> dict[str, Any]:
    return await author(request, survey_id, "save", body.model_dump())


@router.post(
    "/surveys/{survey_id}/publish",
    operation_id="publishSurvey",
    response_model=SurveyVersionResponse,
)
async def publish(survey_id: UUID, body: Mutation, request: Request) -> dict[str, Any]:
    return await author(request, survey_id, "publish", body.model_dump())


@router.put(
    "/surveys/{survey_id}/access",
    operation_id="updateSurveyAccess",
    response_model=SurveySummaryResponse,
)
async def update_access(
    survey_id: UUID, body: SurveyAccess, request: Request, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(request, survey_id, "access", body.model_dump())


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
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await author(request, survey_id, "invitation-create", body.model_dump())


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
