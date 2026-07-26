from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import ActionRole
from leonaid.domain.invitations import (
    ActionInvitation,
    InvitationCode,
    InvitationStatus,
    after_failed_code_attempt,
    invitation_code_digest,
    magic_token_digest,
)
from leonaid.entrypoints.fastapi.schemas import (
    AcceptInvitationRequest,
    CreateInvitationRequest,
)

INVITATION_ID = UUID("41000000-0000-4000-8000-000000000041")
ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
INVITER_ID = UUID("10000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)


def invitation() -> ActionInvitation:
    return ActionInvitation(
        id=INVITATION_ID,
        action_id=ACTION_ID,
        action_name_snapshot="Krapfentaxi 2026",
        invited_by_user_id=INVITER_ID,
        invited_by_name_snapshot="Klara Kern",
        email_snapshot="neues-mitglied@leonaid.invalid",
        display_name_snapshot="Neues Mitglied",
        role_snapshot=ActionRole.ACQUIRER,
        status=InvitationStatus.PENDING,
        token_digest="a" * 64,
        code_digest="b" * 64,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )


def test_six_digit_code_preserves_leading_zero_and_generator_format() -> None:
    assert InvitationCode("000042").value == "000042"
    assert all(
        len(code.value) == 6 and code.value.isdecimal()
        for code in (InvitationCode.generate() for _ in range(256))
    )


@pytest.mark.parametrize("value", ["12345", "1234567", "12A456", "１２３４５６"])
def test_six_digit_code_rejects_invalid_formats(value: str) -> None:
    with pytest.raises(DomainInvariantError, match="sechs Ziffern"):
        InvitationCode(value)


def test_code_digest_is_keyed_and_email_normalized() -> None:
    code = InvitationCode("042931")
    first = invitation_code_digest(
        " Neues-Mitglied@LeonAid.Invalid ",
        code,
        "a-secret-pepper-that-is-definitely-long-enough",
    )
    same = invitation_code_digest(
        "neues-mitglied@leonaid.invalid",
        code,
        "a-secret-pepper-that-is-definitely-long-enough",
    )
    other_secret = invitation_code_digest(
        "neues-mitglied@leonaid.invalid",
        code,
        "a-different-pepper-that-is-also-long-enough",
    )

    assert first == same
    assert first != other_secret
    assert len(first) == 64


def test_fifth_failed_code_attempt_locks_invitation() -> None:
    decisions = [after_failed_code_attempt(attempts) for attempts in range(5)]

    assert [decision.attempts for decision in decisions] == [1, 2, 3, 4, 5]
    assert [decision.locked for decision in decisions] == [
        False,
        False,
        False,
        False,
        True,
    ]
    with pytest.raises(DomainInvariantError, match="Fehlversuchszähler"):
        after_failed_code_attempt(5)


@pytest.mark.parametrize(
    "target",
    [
        InvitationStatus.ACCEPTED,
        InvitationStatus.EXPIRED,
        InvitationStatus.REVOKED,
    ],
)
def test_only_pending_invitation_can_reach_a_terminal_status(
    target: InvitationStatus,
) -> None:
    terminal = invitation().transition_to(target, at=NOW + timedelta(minutes=1))

    assert terminal.status is target
    with pytest.raises(DomainInvariantError, match="Status nicht mehr ändern"):
        terminal.transition_to(
            InvitationStatus.REVOKED,
            at=NOW + timedelta(minutes=2),
        )


def test_expired_invitation_cannot_be_accepted() -> None:
    current = invitation()

    assert current.usable_at(current.expires_at - timedelta(microseconds=1))
    assert not current.usable_at(current.expires_at)
    with pytest.raises(DomainInvariantError, match="abgelaufen"):
        current.transition_to(
            InvitationStatus.ACCEPTED,
            at=current.expires_at,
        )


def test_invitation_snapshot_is_immutable_and_magic_digest_is_one_way() -> None:
    current = invitation()
    token = "real-random-looking-token-with-more-than-32-characters"

    assert len(magic_token_digest(token)) == 64
    with pytest.raises(FrozenInstanceError):
        current.email_snapshot = "changed@leonaid.invalid"  # type: ignore[misc]


def test_secure_mail_payload_is_authenticated_and_not_plaintext() -> None:
    payload = SecureMailPayload("mail-payload-secret-with-at-least-32-characters")
    encrypted = payload.protect(
        recipient="member@leonaid.invalid",
        subject="Einladung",
        text="Code 000042",
    )

    assert set(encrypted) == {"secureMail"}
    assert "000042" not in encrypted["secureMail"]
    assert payload.reveal(encrypted["secureMail"]) == {
        "to": "member@leonaid.invalid",
        "subject": "Einladung",
        "text": "Code 000042",
    }
    with pytest.raises(ValueError, match="ungültig"):
        SecureMailPayload("different-mail-payload-secret-with-32-characters").reveal(
            encrypted["secureMail"]
        )


def test_transport_normalizes_reserved_golden_email_without_weakening_shape() -> None:
    request = CreateInvitationRequest.model_validate(
        {
            "actionId": str(ACTION_ID),
            "email": " Golden-Pilot@LeonAid.Invalid ",
            "displayName": "Golden Pilot",
            "role": "acquirer",
        }
    )
    acceptance = AcceptInvitationRequest.model_validate(
        {"email": "GOLDEN-PILOT@LEONAID.INVALID", "code": "000042"}
    )

    assert request.email == "golden-pilot@leonaid.invalid"
    assert acceptance.email == "golden-pilot@leonaid.invalid"
    with pytest.raises(ValidationError):
        CreateInvitationRequest.model_validate(
            {
                "actionId": str(ACTION_ID),
                "email": "invalid@@leonaid.invalid",
                "displayName": "Invalid",
                "role": "acquirer",
            }
        )
