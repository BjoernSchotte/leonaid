"""Invitation issuance, delivery and atomic acceptance."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Never, Protocol
from uuid import UUID, uuid4, uuid5

from leonaid.application.errors import ApplicationError
from leonaid.application.identity import ROLE_LABELS
from leonaid.application.policies import require_action_manager
from leonaid.domain.identity import ActionRole, IdentityPrincipal
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.invitations import (
    ActionInvitation,
    InvitationAcceptanceMethod,
    InvitationCode,
    InvitationStatus,
    invitation_code_digest,
    magic_token_digest,
    normalize_email,
)
from leonaid.domain.outbox import JsonValue, PendingOutboxEvent
from leonaid.domain.policies import PolicySurface

INVITATION_MAIL_NAMESPACE = UUID("cd8925bf-7111-4cce-b12d-e217f76ec68d")


@dataclass(frozen=True, slots=True)
class InviteableAction:
    id: UUID
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class InvitationContext:
    action: InviteableAction
    invited_by_name: str


@dataclass(frozen=True, slots=True)
class InvitationDispatch:
    invitation_id: UUID
    status: str = "queued"


@dataclass(frozen=True, slots=True)
class InvitationSummary:
    id: UUID
    action_id: UUID
    action_name: str
    email: str
    display_name: str
    role: ActionRole
    status: InvitationStatus
    invited_by_name: str
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    expired_at: datetime | None
    supersedes_invitation_id: UUID | None


@dataclass(frozen=True, slots=True)
class InvitationReissueContext:
    action_id: UUID
    action_name: str
    email: str
    display_name: str
    role: ActionRole
    invited_by_name: str


@dataclass(frozen=True, slots=True)
class InvitationAcceptance:
    user_id: UUID
    action_id: UUID
    action_name: str
    role: ActionRole


class InvitationRepository(Protocol):
    async def inviteable_actions(
        self,
        actor_user_id: UUID,
        *,
        now: datetime,
    ) -> tuple[InviteableAction, ...]: ...

    async def invitation_context(
        self,
        actor_user_id: UUID,
        action_id: UUID,
        *,
        now: datetime,
    ) -> InvitationContext: ...

    async def list_authorized(
        self,
        actor_user_id: UUID,
        *,
        action_id: UUID | None,
        status: InvitationStatus | None,
        now: datetime,
    ) -> tuple[InvitationSummary, ...]: ...

    async def reissue_context(
        self,
        invitation_id: UUID,
        *,
        actor_user_id: UUID,
        now: datetime,
    ) -> InvitationReissueContext | None: ...

    async def create(
        self,
        invitation: ActionInvitation,
        mail_event: PendingOutboxEvent,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> UUID: ...

    async def accept(
        self,
        *,
        token_digest: str | None,
        email: str | None,
        code_digest: str | None,
        method: InvitationAcceptanceMethod,
        request_id: str,
        occurred_at: datetime,
    ) -> InvitationAcceptance | None: ...

    async def revoke(
        self,
        invitation_id: UUID,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> bool: ...

    async def replace(
        self,
        replaced_invitation_id: UUID,
        replacement: ActionInvitation,
        mail_event: PendingOutboxEvent,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
        minimum_age: timedelta,
    ) -> UUID | None: ...


class InvitationMailPayloadProtector(Protocol):
    def protect(
        self,
        *,
        recipient: str,
        subject: str,
        text: str,
    ) -> dict[str, JsonValue]: ...


class InvitationService:
    def __init__(
        self,
        repository: InvitationRepository,
        mail_payload: InvitationMailPayloadProtector,
        *,
        hmac_secret: str,
        public_base_url: str,
        ttl: timedelta = timedelta(minutes=30),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len(hmac_secret) < 32:
            raise ValueError("Der Einladungsschlüssel ist zu kurz.")
        if ttl < timedelta(minutes=5) or ttl > timedelta(days=1):
            raise ValueError(
                "Die Einladungsdauer muss zwischen 5 Minuten und 1 Tag liegen."
            )
        if not public_base_url.startswith(("http://", "https://")):
            raise ValueError("Die öffentliche Basis-URL ist ungültig.")
        self._repository = repository
        self._mail_payload = mail_payload
        self._hmac_secret = hmac_secret
        self._public_base_url = public_base_url.rstrip("/")
        self._ttl = ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def options(
        self,
        actor: IdentityPrincipal,
    ) -> tuple[InviteableAction, ...]:
        return await self._repository.inviteable_actions(
            actor.account.id,
            now=self._clock(),
        )

    async def list(
        self,
        actor: IdentityPrincipal,
        *,
        action_id: UUID | None = None,
        status: InvitationStatus | None = None,
    ) -> tuple[InvitationSummary, ...]:
        return await self._repository.list_authorized(
            actor.account.id,
            action_id=action_id,
            status=status,
            now=self._clock(),
        )

    async def create(
        self,
        actor: IdentityPrincipal,
        *,
        action_id: UUID,
        email: str,
        display_name: str,
        role: ActionRole,
        request_id: str,
    ) -> InvitationDispatch:
        now = self._clock()
        require_action_manager(
            actor,
            action_id,
            PolicySurface.WRITE,
            code="invitation_action_forbidden",
            message="Du darfst für diese Charity-Aktion keine Mitglieder einladen.",
        )
        normalized_email = normalize_email(email)
        normalized_name = " ".join(display_name.split())
        if not normalized_name:
            raise ApplicationError(
                "invitation_display_name_invalid",
                "Bitte gib den Namen des eingeladenen Mitglieds an.",
            )
        context = await self._repository.invitation_context(
            actor.account.id,
            action_id,
            now=now,
        )
        magic_token = secrets.token_urlsafe(32)
        code = InvitationCode.generate()
        invitation = ActionInvitation(
            id=uuid4(),
            action_id=context.action.id,
            action_name_snapshot=context.action.name,
            invited_by_user_id=actor.account.id,
            invited_by_name_snapshot=context.invited_by_name,
            email_snapshot=normalized_email,
            display_name_snapshot=normalized_name,
            role_snapshot=role,
            status=InvitationStatus.PENDING,
            token_digest=magic_token_digest(magic_token),
            code_digest=invitation_code_digest(
                normalized_email,
                code,
                self._hmac_secret,
            ),
            created_at=now,
            expires_at=now + self._ttl,
        )
        mail_event = self._mail_event(invitation, magic_token, code)
        invitation_id = await self._repository.create(
            invitation,
            mail_event,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=now,
        )
        return InvitationDispatch(invitation_id=invitation_id)

    async def accept_magic_link(
        self,
        magic_token: str,
        *,
        request_id: str,
    ) -> InvitationAcceptance:
        try:
            digest = magic_token_digest(magic_token)
        except DomainInvariantError:
            self._reject()
        accepted = await self._repository.accept(
            token_digest=digest,
            email=None,
            code_digest=None,
            method=InvitationAcceptanceMethod.MAGIC_LINK,
            request_id=request_id,
            occurred_at=self._clock(),
        )
        if accepted is None:
            self._reject()
        return accepted

    async def accept_code(
        self,
        email: str,
        raw_code: str,
        *,
        request_id: str,
    ) -> InvitationAcceptance:
        try:
            normalized_email = normalize_email(email)
            code = InvitationCode(raw_code)
            digest = invitation_code_digest(
                normalized_email,
                code,
                self._hmac_secret,
            )
        except (DomainInvariantError, ValueError):
            self._reject()
        accepted = await self._repository.accept(
            token_digest=None,
            email=normalized_email,
            code_digest=digest,
            method=InvitationAcceptanceMethod.CODE,
            request_id=request_id,
            occurred_at=self._clock(),
        )
        if accepted is None:
            self._reject()
        return accepted

    async def revoke(
        self,
        actor: IdentityPrincipal,
        invitation_id: UUID,
        *,
        request_id: str,
    ) -> None:
        revoked = await self._repository.revoke(
            invitation_id,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=self._clock(),
        )
        if not revoked:
            self._reject()

    async def resend(
        self,
        actor: IdentityPrincipal,
        invitation_id: UUID,
        *,
        request_id: str,
    ) -> InvitationDispatch:
        return await self._reissue(
            actor,
            invitation_id,
            email=None,
            request_id=request_id,
            minimum_age=timedelta(minutes=1),
        )

    async def correct_address(
        self,
        actor: IdentityPrincipal,
        invitation_id: UUID,
        *,
        email: str,
        request_id: str,
    ) -> InvitationDispatch:
        return await self._reissue(
            actor,
            invitation_id,
            email=normalize_email(email),
            request_id=request_id,
            minimum_age=timedelta(0),
        )

    async def _reissue(
        self,
        actor: IdentityPrincipal,
        invitation_id: UUID,
        *,
        email: str | None,
        request_id: str,
        minimum_age: timedelta,
    ) -> InvitationDispatch:
        now = self._clock()
        context = await self._repository.reissue_context(
            invitation_id,
            actor_user_id=actor.account.id,
            now=now,
        )
        if context is None:
            self._reject()
        target_email = email or context.email
        magic_token = secrets.token_urlsafe(32)
        code = InvitationCode.generate()
        replacement = ActionInvitation(
            id=uuid4(),
            action_id=context.action_id,
            action_name_snapshot=context.action_name,
            invited_by_user_id=actor.account.id,
            invited_by_name_snapshot=context.invited_by_name,
            email_snapshot=target_email,
            display_name_snapshot=context.display_name,
            role_snapshot=context.role,
            status=InvitationStatus.PENDING,
            token_digest=magic_token_digest(magic_token),
            code_digest=invitation_code_digest(
                target_email,
                code,
                self._hmac_secret,
            ),
            created_at=now,
            expires_at=now + self._ttl,
        )
        replacement_id = await self._repository.replace(
            invitation_id,
            replacement,
            self._mail_event(replacement, magic_token, code),
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=now,
            minimum_age=minimum_age,
        )
        if replacement_id is None:
            raise ApplicationError(
                "invitation_reissue_unavailable",
                "Die Einladung wurde bereits bearbeitet oder gerade erst versendet.",
            )
        return InvitationDispatch(invitation_id=replacement_id)

    def _mail_event(
        self,
        invitation: ActionInvitation,
        magic_token: str,
        code: InvitationCode,
    ) -> PendingOutboxEvent:
        role_label = ROLE_LABELS[invitation.role_snapshot]
        magic_link = f"{self._public_base_url}/invite?token={magic_token}"
        subject = f"Einladung zu {invitation.action_name_snapshot}"
        text = (
            f"Hallo {invitation.display_name_snapshot},\n\n"
            f"{invitation.invited_by_name_snapshot} lädt dich als "
            f"{role_label} zur Charity-Aktion "
            f"„{invitation.action_name_snapshot}“ ein.\n\n"
            f"Magic Link: {magic_link}\n"
            f"Alternativ kannst du für {invitation.email_snapshot} "
            f"den Code {code.value} verwenden.\n\n"
            f"Link und Code sind bis {invitation.expires_at.isoformat()} "
            "gültig und können nur einmal verwendet werden."
        )
        payload = self._mail_payload.protect(
            recipient=invitation.email_snapshot,
            subject=subject,
            text=text,
        )
        return PendingOutboxEvent(
            id=uuid5(INVITATION_MAIL_NAMESPACE, str(invitation.id)),
            aggregate_type="action_invitation",
            aggregate_id=invitation.id,
            event_type="mail.send.v1",
            idempotency_key=f"invitation-mail:{invitation.id}",
            payload=payload,
        )

    @staticmethod
    def _reject() -> Never:
        raise ApplicationError(
            "invitation_invalid",
            "Diese Einladung ist ungültig oder nicht mehr gültig.",
        )
