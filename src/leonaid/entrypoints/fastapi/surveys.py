"""Survey transport; respondent credentials remain in HttpOnly cookies."""

from typing import Any, Literal, Self, cast
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
