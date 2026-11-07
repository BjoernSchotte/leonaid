"""Shared HTTP model base and error envelope; no business dependencies."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TransportModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda value: "".join(
            part if index == 0 else part.capitalize()
            for index, part in enumerate(value.split("_"))
        ),
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


class ApiErrorDetail(TransportModel):
    code: str = Field(examples=["endpoint_not_found"])
    message: str = Field(
        examples=["Dieser API-Endpunkt existiert nicht."],
    )
    request_id: str = Field(
        min_length=8,
        max_length=128,
        examples=["poc023:contract:golden-v1"],
    )
    details: dict[str, object] | None = Field(
        default=None,
        description=(
            "Machine-readable facts for codes that need them, for example "
            "`commitment_price_changed`: `lines` (offeringId, "
            "quotedUnitPriceMinor, unitPriceMinor, lineTotalMinor), "
            "`totalMinor` and `currency`."
        ),
    )


class ApiErrorResponse(TransportModel):
    error: ApiErrorDetail
