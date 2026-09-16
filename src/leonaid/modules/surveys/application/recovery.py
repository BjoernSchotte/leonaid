"""Authenticated, content-free erasure checkpoints for offline restore gates."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_DOCUMENT_BYTES = 32 * 1024 * 1024


class ErasureCheckpointPublisher(Protocol):
    async def publish(self) -> None: ...


class ErasureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    survey_id: UUID
    requested_by: UUID
    operation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_revision: int = Field(ge=1, strict=True)
    event_id: UUID
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("An aware timestamp is required")
        return value


class ErasureCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    installation_id: UUID
    exported_at: datetime
    records: tuple[ErasureRecord, ...]

    @field_validator("exported_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("An aware timestamp is required")
        return value

    @model_validator(mode="after")
    def coherent(self) -> ErasureCheckpoint:
        if len({r.survey_id for r in self.records}) != len(self.records):
            raise ValueError("Duplicate survey identities")
        if len({r.event_id for r in self.records}) != len(self.records):
            raise ValueError("Duplicate event identities")
        if any(r.requested_at > self.exported_at for r in self.records):
            raise ValueError("Checkpoint precedes a contained request")
        return self


def canonical(checkpoint: ErasureCheckpoint) -> bytes:
    return json.dumps(
        checkpoint.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()


def signature(payload: bytes, secret: str) -> str:
    if len(secret) < 32:
        raise ValueError("Recovery authentication key is unavailable")
    key = hmac.digest(
        secret.encode(), b"leonaid-survey-erasure-checkpoint-v1", "sha256"
    )
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def seal(checkpoint: ErasureCheckpoint, secret: str) -> bytes:
    payload = canonical(checkpoint)
    document = (
        json.dumps(
            {
                "checkpoint": json.loads(payload),
                "hmac_sha256": signature(payload, secret),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    if len(document) > MAX_DOCUMENT_BYTES:
        raise ValueError("Checkpoint exceeds the supported size")
    return document


def verify(
    document: bytes, secret: str, *, installation_id: UUID, required_through: datetime
) -> ErasureCheckpoint:
    if required_through.tzinfo is None or required_through.utcoffset() is None:
        raise ValueError("Recovery cutoff must be timezone-aware")
    if len(document) > MAX_DOCUMENT_BYTES:
        raise ValueError("Checkpoint exceeds the supported size")
    envelope = json.loads(document)
    if not isinstance(envelope, dict) or set(envelope) != {"checkpoint", "hmac_sha256"}:
        raise ValueError("Invalid checkpoint envelope")
    checkpoint = ErasureCheckpoint.model_validate(envelope["checkpoint"])
    provided = envelope["hmac_sha256"]
    if not isinstance(provided, str) or not hmac.compare_digest(
        provided, signature(canonical(checkpoint), secret)
    ):
        raise ValueError("Checkpoint authentication failed")
    if checkpoint.installation_id != installation_id:
        raise ValueError("Checkpoint belongs to another installation")
    if (
        checkpoint.exported_at < required_through
        or checkpoint.exported_at > datetime.now(timezone.utc)
    ):
        raise ValueError("Checkpoint does not cover the recovery cutoff")
    return checkpoint
