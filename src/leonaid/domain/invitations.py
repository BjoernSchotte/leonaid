"""Invitation snapshots, one-time credentials and lifecycle rules."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import ActionRole, require_aware

SIX_DIGIT_CODE = re.compile(r"[0-9]{6}\Z")
MAX_INVITATION_CODE_ATTEMPTS = 5


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class InvitationAcceptanceMethod(StrEnum):
    MAGIC_LINK = "magic_link"
    CODE = "code"


@dataclass(frozen=True, slots=True)
class InvitationCode:
    value: str

    def __post_init__(self) -> None:
        if SIX_DIGIT_CODE.fullmatch(self.value) is None:
            raise DomainInvariantError(
                "invitation_code_invalid",
                "Der Einladungscode muss aus genau sechs Ziffern bestehen.",
            )

    @classmethod
    def generate(cls) -> InvitationCode:
        return cls(f"{secrets.randbelow(1_000_000):06d}")


@dataclass(frozen=True, slots=True)
class CodeAttemptDecision:
    attempts: int
    locked: bool


def after_failed_code_attempt(current_attempts: int) -> CodeAttemptDecision:
    if current_attempts < 0 or current_attempts >= MAX_INVITATION_CODE_ATTEMPTS:
        raise DomainInvariantError(
            "invitation_code_attempt_state_invalid",
            "Der Fehlversuchszähler ist ungültig.",
        )
    attempts = current_attempts + 1
    return CodeAttemptDecision(
        attempts=attempts,
        locked=attempts >= MAX_INVITATION_CODE_ATTEMPTS,
    )


def normalize_email(value: str) -> str:
    normalized = value.strip().casefold()
    if (
        normalized.count("@") != 1
        or any(character.isspace() for character in normalized)
        or normalized.startswith("@")
        or normalized.endswith("@")
    ):
        raise DomainInvariantError(
            "invitation_email_invalid",
            "Die E-Mail-Adresse der Einladung ist ungültig.",
        )
    return normalized


def magic_token_digest(token: str) -> str:
    if len(token) < 32 or any(character.isspace() for character in token):
        raise DomainInvariantError(
            "invitation_token_invalid",
            "Der Magic Link enthält kein gültiges Einladungstoken.",
        )
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def invitation_code_digest(email: str, code: InvitationCode, pepper: str) -> str:
    if len(pepper) < 32:
        raise ValueError("Der Einladungsschlüssel ist zu kurz.")
    message = f"{normalize_email(email)}:{code.value}".encode()
    return hmac.new(pepper.encode(), message, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class ActionInvitation:
    id: UUID
    action_id: UUID
    action_name_snapshot: str
    invited_by_user_id: UUID
    invited_by_name_snapshot: str
    email_snapshot: str
    display_name_snapshot: str
    role_snapshot: ActionRole
    status: InvitationStatus
    token_digest: str
    code_digest: str
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for value, code, message in (
            (
                self.action_name_snapshot,
                "invitation_action_name_empty",
                "Der Aktions-Snapshot darf nicht leer sein.",
            ),
            (
                self.invited_by_name_snapshot,
                "invitation_inviter_name_empty",
                "Der Einladenden-Snapshot darf nicht leer sein.",
            ),
            (
                self.display_name_snapshot,
                "invitation_display_name_empty",
                "Der Anzeigename darf nicht leer sein.",
            ),
        ):
            if not value.strip():
                raise DomainInvariantError(code, message)
        if normalize_email(self.email_snapshot) != self.email_snapshot:
            raise DomainInvariantError(
                "invitation_email_not_normalized",
                "Der E-Mail-Snapshot muss normalisiert sein.",
            )
        if any(
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in (self.token_digest, self.code_digest)
        ):
            raise DomainInvariantError(
                "invitation_digest_invalid",
                "Einladungsnachweise müssen SHA-256-Digests sein.",
            )
        require_aware(self.created_at, "created_at")
        require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise DomainInvariantError(
                "invitation_expiry_invalid",
                "Eine Einladung muss nach ihrer Erstellung ablaufen.",
            )

    def transition_to(
        self,
        target: InvitationStatus,
        *,
        at: datetime,
    ) -> ActionInvitation:
        require_aware(at, "at")
        if self.status is not InvitationStatus.PENDING or target not in {
            InvitationStatus.ACCEPTED,
            InvitationStatus.EXPIRED,
            InvitationStatus.REVOKED,
        }:
            raise DomainInvariantError(
                "invitation_status_transition_invalid",
                "Diese Einladung kann ihren Status nicht mehr ändern.",
            )
        if target is InvitationStatus.ACCEPTED and at >= self.expires_at:
            raise DomainInvariantError(
                "invitation_expired",
                "Diese Einladung ist abgelaufen.",
            )
        return replace(self, status=target)

    def usable_at(self, moment: datetime) -> bool:
        require_aware(moment, "moment")
        return self.status is InvitationStatus.PENDING and moment < self.expires_at
