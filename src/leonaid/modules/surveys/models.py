"""Transport-independent Survey inputs and results, shared by HTTP and direct calls."""

from typing import Any, Literal, Self
from datetime import datetime, timezone
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
    field_validator,
    EmailStr,
)
from leonaid.domain.surveys.validation import json_size


class SurveyInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, revalidate_instances="always"
    )


class Mutation(SurveyInput):
    operationId: str = Field(min_length=1, max_length=128)
    expectedRevision: int = Field(ge=1)


class DraftValidation(SurveyInput):
    expectedRevision: int = Field(ge=1)


class SurveyDeletionResponse(SurveyInput):
    surveyId: str
    status: Literal["pending", "retrying", "failed", "completed"]
    requestedAt: str
    completedAt: str | None
    retryEventId: str | None = None


class TimeoutSettings(Mutation):
    inactivityTimeoutSeconds: int = Field(ge=1, le=604800)
    endedRetentionSeconds: int | None = Field(default=None, ge=1, le=315360000)
    trashRetentionSeconds: int | None = Field(default=None, ge=1, le=315360000)


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
    endedRetentionSeconds: int | None = None
    trashRetentionSeconds: int | None = None
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


class SurveyListQuery(SurveyInput):
    status: Literal["draft", "active", "ended", "archived", "deleted"] | None = None
    search: str = Field(default="", max_length=240)
    offset: int = Field(default=0, ge=0)
