"""Survey export job contracts; storage locations never cross this boundary."""

from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, field_validator

from leonaid.application.surveys.analysis import AggregateModel
from leonaid.application.surveys.export_rendering import (
    ExportProduct,
    SurveyExportArtifact,
)


class CreateSurveyExport(AggregateModel):
    operationId: str = Field(min_length=1, max_length=128)
    snapshotId: str = Field(min_length=36, max_length=36)
    product: ExportProduct

    @field_validator("snapshotId")
    @classmethod
    def snapshot_uuid(cls, value: str) -> str:
        return str(UUID(value))


class SurveyExportJob(AggregateModel):
    id: str
    surveyId: str
    snapshotId: str
    product: ExportProduct
    status: Literal[
        "queued", "processing", "retrying", "failed", "available", "cancelled"
    ]
    createdAt: str
    completedAt: str | None
    filename: str | None
    sizeBytes: int | None
    errorCode: str | None


class SurveyExports(Protocol):
    async def create(
        self, user_id: UUID, survey_id: UUID, body: CreateSurveyExport
    ) -> SurveyExportJob: ...
    async def get(
        self, user_id: UUID, survey_id: UUID, job_id: UUID
    ) -> SurveyExportJob: ...
    async def download(
        self, user_id: UUID, survey_id: UUID, job_id: UUID
    ) -> SurveyExportArtifact: ...
