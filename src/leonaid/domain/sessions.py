"""Passwordless login challenges and server-side session invariants."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import require_aware
from leonaid.domain.invitations import normalize_email

SESSION_COOKIE_NAME = "__Host-leonaid_session"
SESSION_LIFETIME = timedelta(days=90)
MAX_LOGIN_CODE_ATTEMPTS = 5


class LoginPurpose(StrEnum):
    LOGIN = "login"
    FRESH_LOGIN = "fresh_login"


class LoginChallengeStatus(StrEnum):
    PENDING = "pending"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class LoginCode:
    value: str

    def __post_init__(self) -> None:
        if (
            len(self.value) != 6
            or not self.value.isascii()
            or not self.value.isdecimal()
        ):
            raise DomainInvariantError(
                "login_code_invalid",
                "Ein Login-Code muss aus genau sechs ASCII-Ziffern bestehen.",
            )

    @classmethod
    def generate(cls) -> LoginCode:
        return cls(f"{secrets.randbelow(1_000_000):06d}")


def session_token_digest(raw_token: str) -> str:
    if (
        len(raw_token) < 32
        or len(raw_token) > 256
        or any(character.isspace() for character in raw_token)
    ):
        raise DomainInvariantError(
            "session_token_invalid",
            "Das Sitzungstoken besitzt kein gültiges Format.",
        )
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def login_magic_digest(raw_token: str) -> str:
    if (
        len(raw_token) < 32
        or len(raw_token) > 256
        or any(character.isspace() for character in raw_token)
    ):
        raise DomainInvariantError(
            "login_magic_token_invalid",
            "Das Login-Token besitzt kein gültiges Format.",
        )
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def login_code_digest(
    email: str,
    code: LoginCode,
    secret: str,
    purpose: LoginPurpose,
) -> str:
    if len(secret) < 32:
        raise ValueError("Der Login-Code-Schlüssel ist zu kurz.")
    normalized_email = normalize_email(email)
    message = (
        f"leonaid-login-code:v1:{purpose.value}:{normalized_email}:{code.value}"
    ).encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class UserSession:
    id: UUID
    user_id: UUID
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    fresh_login_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        for field, value in (
            ("created_at", self.created_at),
            ("expires_at", self.expires_at),
            ("last_seen_at", self.last_seen_at),
            ("fresh_login_at", self.fresh_login_at),
        ):
            require_aware(value, field)
        if self.revoked_at is not None:
            require_aware(self.revoked_at, "revoked_at")
        if self.expires_at != self.created_at + SESSION_LIFETIME:
            raise DomainInvariantError(
                "session_lifetime_invalid",
                "Eine Sitzung muss ein absolutes Ablaufdatum nach 90 Tagen besitzen.",
            )
        if self.last_seen_at < self.created_at:
            raise DomainInvariantError(
                "session_last_seen_invalid",
                "Der letzte Zugriff darf nicht vor Sitzungsbeginn liegen.",
            )
        if not self.created_at <= self.fresh_login_at <= self.last_seen_at:
            raise DomainInvariantError(
                "session_fresh_login_invalid",
                "Der Fresh-Login-Zeitpunkt liegt außerhalb der Sitzung.",
            )
        if self.revoked_at is not None and self.revoked_at < self.created_at:
            raise DomainInvariantError(
                "session_revocation_invalid",
                "Der Widerruf darf nicht vor Sitzungsbeginn liegen.",
            )

    def active_at(self, moment: datetime) -> bool:
        require_aware(moment, "moment")
        return self.revoked_at is None and moment < self.expires_at

    def fresh_at(self, moment: datetime, maximum_age: timedelta) -> bool:
        require_aware(moment, "moment")
        if maximum_age <= timedelta(0):
            raise ValueError("Das Fresh-Login-Fenster muss positiv sein.")
        return (
            self.active_at(moment)
            and self.fresh_login_at <= moment
            and moment - self.fresh_login_at <= maximum_age
        )

    def seen_at(self, moment: datetime) -> UserSession:
        require_aware(moment, "moment")
        if moment < self.last_seen_at:
            return self
        return replace(self, last_seen_at=moment)

    def revoke_at(self, moment: datetime) -> UserSession:
        require_aware(moment, "moment")
        if self.revoked_at is not None:
            return self
        if moment < self.created_at:
            raise DomainInvariantError(
                "session_revocation_invalid",
                "Der Widerruf darf nicht vor Sitzungsbeginn liegen.",
            )
        return replace(self, revoked_at=moment)


@dataclass(frozen=True, slots=True)
class LoginChallenge:
    id: UUID
    user_id: UUID
    purpose: LoginPurpose
    email_snapshot: str
    token_digest: str
    code_digest: str
    status: LoginChallengeStatus
    created_at: datetime
    expires_at: datetime
    failed_code_attempts: int = 0
    consumed_at: datetime | None = None
    expired_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        normalized = normalize_email(self.email_snapshot)
        if normalized != self.email_snapshot:
            raise DomainInvariantError(
                "login_email_snapshot_invalid",
                "Der E-Mail-Snapshot muss normalisiert sein.",
            )
        if len(self.token_digest) != 64 or len(self.code_digest) != 64:
            raise DomainInvariantError(
                "login_challenge_digest_invalid",
                "Login-Digests müssen SHA-256-Länge besitzen.",
            )
        require_aware(self.created_at, "created_at")
        require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise DomainInvariantError(
                "login_challenge_expiry_invalid",
                "Eine Login-Challenge muss nach ihrer Erstellung ablaufen.",
            )
        if not 0 <= self.failed_code_attempts <= MAX_LOGIN_CODE_ATTEMPTS:
            raise DomainInvariantError(
                "login_attempts_invalid",
                "Die Zahl fehlgeschlagener Login-Codes ist ungültig.",
            )
        for value in (self.consumed_at, self.expired_at, self.revoked_at):
            if value is not None:
                require_aware(value, "login_challenge_lifecycle")
        expected = {
            LoginChallengeStatus.PENDING: (False, False, False),
            LoginChallengeStatus.CONSUMED: (True, False, False),
            LoginChallengeStatus.EXPIRED: (False, True, False),
            LoginChallengeStatus.REVOKED: (False, False, True),
        }[self.status]
        actual = tuple(
            value is not None
            for value in (self.consumed_at, self.expired_at, self.revoked_at)
        )
        if actual != expected:
            raise DomainInvariantError(
                "login_challenge_state_invalid",
                "Status und Lebenszykluszeitpunkte der Login-Challenge widersprechen sich.",
            )

    def usable_at(self, moment: datetime) -> bool:
        require_aware(moment, "moment")
        return self.status is LoginChallengeStatus.PENDING and moment < self.expires_at

    def consume_at(self, moment: datetime) -> LoginChallenge:
        if not self.usable_at(moment):
            raise DomainInvariantError(
                "login_challenge_not_usable",
                "Die Login-Challenge ist nicht mehr verwendbar.",
            )
        return replace(
            self,
            status=LoginChallengeStatus.CONSUMED,
            consumed_at=moment,
        )

    def expire_at(self, moment: datetime) -> LoginChallenge:
        require_aware(moment, "moment")
        if self.status is not LoginChallengeStatus.PENDING:
            raise DomainInvariantError(
                "login_challenge_transition_invalid",
                "Nur eine offene Login-Challenge kann ablaufen.",
            )
        if moment < self.expires_at:
            raise DomainInvariantError(
                "login_challenge_not_expired",
                "Die Login-Challenge ist noch gültig.",
            )
        return replace(
            self,
            status=LoginChallengeStatus.EXPIRED,
            expired_at=moment,
        )

    def revoke_at(self, moment: datetime) -> LoginChallenge:
        require_aware(moment, "moment")
        if self.status is not LoginChallengeStatus.PENDING:
            raise DomainInvariantError(
                "login_challenge_transition_invalid",
                "Nur eine offene Login-Challenge kann widerrufen werden.",
            )
        return replace(
            self,
            status=LoginChallengeStatus.REVOKED,
            revoked_at=moment,
        )


@dataclass(frozen=True, slots=True)
class LoginCodeAttempt:
    attempts: int
    locked: bool


def after_failed_login_code(current_attempts: int) -> LoginCodeAttempt:
    if not 0 <= current_attempts < MAX_LOGIN_CODE_ATTEMPTS:
        raise DomainInvariantError(
            "login_attempts_invalid",
            "Die Zahl fehlgeschlagener Login-Codes ist ungültig.",
        )
    attempts = current_attempts + 1
    return LoginCodeAttempt(
        attempts=attempts,
        locked=attempts >= MAX_LOGIN_CODE_ATTEMPTS,
    )
