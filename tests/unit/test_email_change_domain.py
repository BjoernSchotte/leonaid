from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from leonaid.domain.email_changes import (
    EmailChangeCode,
    EmailChangeStatus,
    PendingEmailChange,
    email_change_code_digest,
    email_change_token_digest,
)
from leonaid.domain.errors import DomainInvariantError

NOW = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)


def pending() -> PendingEmailChange:
    return PendingEmailChange(
        id=UUID("71000000-0000-4000-8000-000000000001"),
        user_id=UUID("10000000-0000-4000-8000-000000000002"),
        requested_by_user_id=UUID("10000000-0000-4000-8000-000000000001"),
        old_email_snapshot="old@leonaid.invalid",
        new_email_snapshot="new@leonaid.invalid",
        display_name_snapshot="Klara Kern",
        status=EmailChangeStatus.PENDING,
        token_digest="a" * 64,
        code_digest="b" * 64,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )


def test_credentials_are_context_bound() -> None:
    code = EmailChangeCode("123456")
    first = email_change_code_digest("new@leonaid.invalid", code, "s" * 32)
    second = email_change_code_digest("other@leonaid.invalid", code, "s" * 32)
    assert first != second
    assert len(email_change_token_digest("token-" * 8)) == 64


def test_fifth_failed_code_revokes_pending_change() -> None:
    change = pending()
    for _ in range(4):
        change = change.after_failed_code()
        assert change.status is EmailChangeStatus.PENDING
    change = change.after_failed_code()
    assert change.status is EmailChangeStatus.REVOKED
    assert change.failed_code_attempts == 5


def test_unchanged_address_and_invalid_code_are_rejected() -> None:
    with pytest.raises(DomainInvariantError):
        EmailChangeCode("12345")
    with pytest.raises(DomainInvariantError):
        replace(
            pending(),
            new_email_snapshot="old@leonaid.invalid",
        )
