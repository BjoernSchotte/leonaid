from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.sessions import (
    MAX_LOGIN_CODE_ATTEMPTS,
    LoginChallenge,
    LoginChallengeStatus,
    LoginCode,
    LoginPurpose,
    SESSION_LIFETIME,
    UserSession,
    after_failed_login_code,
    login_code_digest,
    login_magic_digest,
    session_token_digest,
)

USER_ID = UUID("10000000-0000-4000-8000-000000000003")
SESSION_ID = UUID("42000000-0000-4000-8000-000000000001")
CHALLENGE_ID = UUID("42000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
SECRET = "poc042-domain-separated-secret-value"


def session() -> UserSession:
    return UserSession(
        id=SESSION_ID,
        user_id=USER_ID,
        created_at=NOW,
        expires_at=NOW + SESSION_LIFETIME,
        last_seen_at=NOW,
        fresh_login_at=NOW,
    )


def challenge() -> LoginChallenge:
    return LoginChallenge(
        id=CHALLENGE_ID,
        user_id=USER_ID,
        purpose=LoginPurpose.LOGIN,
        email_snapshot="anna.akquise@leonaid.invalid",
        token_digest="a" * 64,
        code_digest="b" * 64,
        status=LoginChallengeStatus.PENDING,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def test_session_has_absolute_ninety_day_lifetime_and_fresh_window() -> None:
    current = session()

    assert current.active_at(NOW + timedelta(days=89, hours=23))
    assert not current.active_at(NOW + SESSION_LIFETIME)
    assert current.fresh_at(NOW + timedelta(minutes=15), timedelta(minutes=15))
    assert not current.fresh_at(
        NOW + timedelta(minutes=15, microseconds=1),
        timedelta(minutes=15),
    )
    assert current.seen_at(NOW + timedelta(days=30)).expires_at == (
        NOW + SESSION_LIFETIME
    )


def test_session_rejects_sliding_or_invalid_timestamps() -> None:
    with pytest.raises(DomainInvariantError, match="90 Tagen"):
        UserSession(
            id=SESSION_ID,
            user_id=USER_ID,
            created_at=NOW,
            expires_at=NOW + timedelta(days=91),
            last_seen_at=NOW,
            fresh_login_at=NOW,
        )
    with pytest.raises(DomainInvariantError, match="Fresh-Login"):
        UserSession(
            id=SESSION_ID,
            user_id=USER_ID,
            created_at=NOW,
            expires_at=NOW + SESSION_LIFETIME,
            last_seen_at=NOW,
            fresh_login_at=NOW + timedelta(seconds=1),
        )


def test_session_revocation_is_immediate_and_immutable() -> None:
    revoked = session().revoke_at(NOW + timedelta(hours=1))

    assert not revoked.active_at(NOW + timedelta(hours=1))
    assert revoked.revoke_at(NOW + timedelta(hours=2)) is revoked
    with pytest.raises(FrozenInstanceError):
        revoked.revoked_at = None  # type: ignore[misc]


@pytest.mark.parametrize("value", ["12345", "1234567", "１２３４５６", "12a456"])
def test_login_code_is_exactly_six_ascii_digits(value: str) -> None:
    with pytest.raises(DomainInvariantError, match="ASCII-Ziffern"):
        LoginCode(value)


def test_login_code_preserves_leading_zero_and_uses_domain_separated_hmac() -> None:
    code = LoginCode("012345")

    assert code.value == "012345"
    assert login_code_digest(
        " Anna.Akquise@Leonaid.Invalid ",
        code,
        SECRET,
        LoginPurpose.LOGIN,
    ) == login_code_digest(
        "anna.akquise@leonaid.invalid",
        code,
        SECRET,
        LoginPurpose.LOGIN,
    )
    assert (
        login_code_digest(
            "anna.akquise@leonaid.invalid",
            code,
            SECRET,
            LoginPurpose.LOGIN,
        )
        != login_code_digest(
            "anna.akquise@leonaid.invalid",
            code,
            SECRET,
            LoginPurpose.FRESH_LOGIN,
        )
        != session_token_digest("x" * 32)
    )


def test_magic_and_session_tokens_are_validated_and_hashed() -> None:
    assert len(login_magic_digest("m" * 32)) == 64
    assert len(session_token_digest("s" * 48)) == 64
    with pytest.raises(DomainInvariantError):
        login_magic_digest("short")
    with pytest.raises(DomainInvariantError):
        session_token_digest("has whitespace " * 3)


def test_challenge_has_terminal_transitions_and_expiry_boundary() -> None:
    current = challenge()
    assert current.usable_at(current.expires_at - timedelta(microseconds=1))
    assert not current.usable_at(current.expires_at)
    assert current.consume_at(NOW).status is LoginChallengeStatus.CONSUMED
    assert current.expire_at(current.expires_at).expired_at == current.expires_at
    assert current.revoke_at(NOW).status is LoginChallengeStatus.REVOKED
    with pytest.raises(DomainInvariantError):
        current.consume_at(current.expires_at)


def test_fifth_failed_login_code_locks_challenge() -> None:
    decision = None
    attempts = 0
    for _ in range(MAX_LOGIN_CODE_ATTEMPTS):
        decision = after_failed_login_code(attempts)
        attempts = decision.attempts

    assert decision is not None
    assert decision.attempts == 5
    assert decision.locked
    with pytest.raises(DomainInvariantError):
        after_failed_login_code(5)
