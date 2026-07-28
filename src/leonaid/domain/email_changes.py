"""Immutable pending login-email changes and one-time credentials."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError


class EmailChangeStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class EmailChangeCode:
    value: str

    def __post_init__(self) -> None:
        if len(self.value) != 6 or not self.value.isascii() or not self.value.isdigit():
            raise DomainInvariantError(
                "email_change_code_invalid",
                "Der Bestätigungscode muss sechsstellig sein.",
            )

    @classmethod
    def generate(cls) -> EmailChangeCode:
        return cls(f"{secrets.randbelow(1_000_000):06d}")


def email_change_token_digest(raw_token: str) -> str:
    if len(raw_token) < 32:
        raise DomainInvariantError(
            "email_change_token_invalid",
            "Der Bestätigungslink ist ungültig.",
        )
    return hashlib.sha256(raw_token.encode()).hexdigest()


def email_change_code_digest(
    email: str,
    code: EmailChangeCode,
    pepper: str,
) -> str:
    if len(pepper) < 32:
        raise ValueError("Der E-Mail-Änderungsschlüssel ist zu kurz.")
    material = f"leonaid-email-change:v1:{email}:{code.value}".encode()
    return hmac.new(pepper.encode(), material, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class PendingEmailChange:
    id: UUID
    user_id: UUID
    requested_by_user_id: UUID
    old_email_snapshot: str
    new_email_snapshot: str
    display_name_snapshot: str
    status: EmailChangeStatus
    token_digest: str
    code_digest: str
    created_at: datetime
    expires_at: datetime
    failed_code_attempts: int = 0

    def __post_init__(self) -> None:
        if self.old_email_snapshot == self.new_email_snapshot:
            raise DomainInvariantError(
                "email_change_address_unchanged",
                "Die neue E-Mail-Adresse muss sich von der bisherigen unterscheiden.",
            )
        if self.expires_at <= self.created_at:
            raise DomainInvariantError(
                "email_change_expiry_invalid",
                "Die Bestätigung muss nach ihrer Erstellung ablaufen.",
            )
        if not 0 <= self.failed_code_attempts <= 5:
            raise DomainInvariantError(
                "email_change_attempts_invalid",
                "Die Anzahl der Fehlversuche ist ungültig.",
            )

    def after_failed_code(self) -> PendingEmailChange:
        if self.status is not EmailChangeStatus.PENDING:
            return self
        attempts = min(self.failed_code_attempts + 1, 5)
        return replace(
            self,
            failed_code_attempts=attempts,
            status=(
                EmailChangeStatus.REVOKED
                if attempts >= 5
                else EmailChangeStatus.PENDING
            ),
        )
