"""Each mail links the host of its audience (specs/multi-domain §7.6).

Single-host stacks cannot tell the bases apart, so these tests give every
service an admin base and a different site base and check the mailed host:
login, fresh login, invitation and e-mail change → admin host; survey
invitation → public host. LeonAid sends no customer order confirmation yet;
stage 2 adds it with the campaign's edition URL (D8).
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from leonaid.application.email_changes import EmailChangeService
from leonaid.application.invitations import InvitationService
from leonaid.application.links import LinkBuilder
from leonaid.application.sessions import LoginAccount, SessionService
from leonaid.domain.email_changes import (
    EmailChangeCode,
    EmailChangeStatus,
    PendingEmailChange,
)
from leonaid.domain.identity import ActionRole
from leonaid.domain.invitations import (
    ActionInvitation,
    InvitationCode,
    InvitationStatus,
)
from leonaid.modules.surveys.adapters.postgres.surveys import survey_invitation_text

ADMIN = "https://app.leonaid.org"
SITE = "https://leonaid.org"
LINKS = LinkBuilder(admin_base_url=ADMIN, site_base_url=SITE)
SECRET = "mail-link-host-test-secret-with-32-characters"
NOW = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)
URL = re.compile(r"https://[^\s]+")


class PlainMailPayload:
    """Keeps the mail text readable for the assertion."""

    def protect(self, *, recipient: str, subject: str, text: str) -> dict[str, Any]:
        return {"recipient": recipient, "subject": subject, "text": text}


class RecordingRepository:
    """Answers the account lookup and records the mail event of a challenge."""

    def __init__(self) -> None:
        self.account = LoginAccount(
            id=uuid4(), email="anna@leonaid.org", display_name="Anna"
        )
        self.events: list[Any] = []

    async def active_account_for_email(self, email: str) -> LoginAccount | None:
        return self.account if email == self.account.email else None

    async def create_challenge(self, challenge: Any, mail_event: Any, **_: Any) -> bool:
        self.events.append(mail_event)
        return True


def links_in(text: str) -> list[str]:
    return URL.findall(text)


def test_login_mail_links_the_admin_host() -> None:
    repository = RecordingRepository()
    service = SessionService(
        repository,  # type: ignore[arg-type]
        PlainMailPayload(),
        hmac_secret=SECRET,
        links=LINKS,
        clock=lambda: NOW,
    )
    asyncio.run(service.request_login("anna@leonaid.org", request_id="r1"))
    [event] = repository.events
    [link] = links_in(event.payload["text"])
    assert link.startswith(f"{ADMIN}/login?token=")


def test_invitation_mail_links_the_admin_host() -> None:
    service = InvitationService(
        object(),  # type: ignore[arg-type]
        PlainMailPayload(),
        hmac_secret=SECRET,
        links=LINKS,
    )
    invitation = ActionInvitation(
        id=uuid4(),
        action_id=uuid4(),
        action_name_snapshot="Krapfentaxi 2026",
        invited_by_user_id=uuid4(),
        invited_by_name_snapshot="Björn",
        email_snapshot="new@leonaid.org",
        display_name_snapshot="Neu",
        role_snapshot=ActionRole.ACQUIRER,
        status=InvitationStatus.PENDING,
        token_digest="a" * 64,
        code_digest="b" * 64,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )
    event = service._mail_event(invitation, "t" * 43, InvitationCode("123456"))
    [link] = links_in(event.payload["text"])
    assert link.startswith(f"{ADMIN}/invite?token=")


def test_email_change_mail_links_the_admin_host() -> None:
    service = EmailChangeService(
        object(),  # type: ignore[arg-type]
        PlainMailPayload(),
        hmac_secret=SECRET,
        links=LINKS,
    )
    change = PendingEmailChange(
        id=uuid4(),
        user_id=uuid4(),
        requested_by_user_id=uuid4(),
        old_email_snapshot="old@leonaid.org",
        new_email_snapshot="new@leonaid.org",
        display_name_snapshot="Anna",
        status=EmailChangeStatus.PENDING,
        token_digest="a" * 64,
        code_digest="b" * 64,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )
    events = service._request_mail_events(change, "t" * 43, EmailChangeCode("654321"))
    found = [link for event in events for link in links_in(event.payload["text"])]
    assert found and all(
        link.startswith(f"{ADMIN}/email-change?token=") for link in found
    )


def test_survey_invitation_links_the_public_host() -> None:
    text = survey_invitation_text(LINKS, "Feedback", uuid4(), "t" * 43, NOW)
    [link] = links_in(text)
    assert link.startswith(f"{SITE}/surveys/")
    assert "#invitation=" in link
