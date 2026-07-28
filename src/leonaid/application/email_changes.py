"""System-admin initiated, recipient-confirmed login-email changes."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Never, Protocol
from uuid import UUID, uuid4, uuid5

from leonaid.application.errors import ApplicationError, Conflict, ResourceNotFound
from leonaid.application.policies import require_system_admin
from leonaid.domain.email_changes import (
    EmailChangeCode,
    EmailChangeStatus,
    PendingEmailChange,
    email_change_code_digest,
    email_change_token_digest,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.invitations import normalize_email
from leonaid.domain.outbox import JsonValue, PendingOutboxEvent

EMAIL_CHANGE_MAIL_NAMESPACE = UUID("53f145ad-7115-43f2-84bf-06ec507b2640")


@dataclass(frozen=True, slots=True)
class EmailChangeContext:
    user_id: UUID
    email: str
    display_name: str


@dataclass(frozen=True, slots=True)
class EmailChangeDispatch:
    change_id: UUID
    status: str = "pending"


@dataclass(frozen=True, slots=True)
class EmailChangeConfirmation:
    user_id: UUID
    revoked_session_count: int
    status: str = "confirmed"


class EmailChangeCreateResult(StrEnum):
    CREATED = "created"
    TARGET_NOT_FOUND = "target_not_found"
    ADDRESS_IN_USE = "address_in_use"
    CHANGE_PENDING = "change_pending"
    CONTEXT_CHANGED = "context_changed"


class EmailChangeConfirmResult(StrEnum):
    CONFIRMED = "confirmed"
    INVALID = "invalid"
    ADDRESS_IN_USE = "address_in_use"


class EmailChangeRepository(Protocol):
    async def context(self, user_id: UUID) -> EmailChangeContext | None: ...

    async def create(
        self,
        change: PendingEmailChange,
        mail_events: tuple[PendingOutboxEvent, ...],
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> EmailChangeCreateResult: ...

    async def confirm(
        self,
        *,
        token_digest: str | None,
        email: str | None,
        code_digest: str | None,
        completion_mail_events: Callable[
            [PendingEmailChange], tuple[PendingOutboxEvent, ...]
        ],
        request_id: str,
        occurred_at: datetime,
    ) -> tuple[EmailChangeConfirmResult, EmailChangeConfirmation | None]: ...


class EmailChangeMailPayloadProtector(Protocol):
    def protect(
        self,
        *,
        recipient: str,
        subject: str,
        text: str,
    ) -> dict[str, JsonValue]: ...


class EmailChangeService:
    def __init__(
        self,
        repository: EmailChangeRepository,
        mail_payload: EmailChangeMailPayloadProtector,
        *,
        hmac_secret: str,
        public_base_url: str,
        ttl: timedelta = timedelta(minutes=30),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len(hmac_secret) < 32:
            raise ValueError("Der E-Mail-Änderungsschlüssel ist zu kurz.")
        if ttl < timedelta(minutes=5) or ttl > timedelta(days=1):
            raise ValueError(
                "Die E-Mail-Bestätigung muss zwischen 5 Minuten und 1 Tag gelten."
            )
        if not public_base_url.startswith(("http://", "https://")):
            raise ValueError("Die öffentliche Basis-URL ist ungültig.")
        self._repository = repository
        self._mail_payload = mail_payload
        self._hmac_secret = hmac_secret
        self._public_base_url = public_base_url.rstrip("/")
        self._ttl = ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def request(
        self,
        actor: IdentityPrincipal,
        target_user_id: UUID,
        *,
        new_email: str,
        request_id: str,
    ) -> EmailChangeDispatch:
        require_system_admin(actor)
        context = await self._repository.context(target_user_id)
        if context is None:
            raise ResourceNotFound(
                "user_not_found",
                "Das Benutzerkonto wurde nicht gefunden.",
            )
        normalized_email = normalize_email(new_email)
        now = self._clock()
        token = secrets.token_urlsafe(32)
        code = EmailChangeCode.generate()
        change = PendingEmailChange(
            id=uuid4(),
            user_id=context.user_id,
            requested_by_user_id=actor.account.id,
            old_email_snapshot=context.email,
            new_email_snapshot=normalized_email,
            display_name_snapshot=context.display_name,
            status=EmailChangeStatus.PENDING,
            token_digest=email_change_token_digest(token),
            code_digest=email_change_code_digest(
                normalized_email,
                code,
                self._hmac_secret,
            ),
            created_at=now,
            expires_at=now + self._ttl,
        )
        result = await self._repository.create(
            change,
            self._request_mail_events(change, token, code),
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=now,
        )
        if result is EmailChangeCreateResult.CREATED:
            return EmailChangeDispatch(change_id=change.id)
        if result is EmailChangeCreateResult.TARGET_NOT_FOUND:
            raise ResourceNotFound(
                "user_not_found",
                "Das Benutzerkonto wurde nicht gefunden.",
            )
        if result is EmailChangeCreateResult.ADDRESS_IN_USE:
            raise Conflict(
                "email_change_address_in_use",
                "Diese E-Mail-Adresse wird bereits verwendet.",
            )
        if result is EmailChangeCreateResult.CHANGE_PENDING:
            raise Conflict(
                "email_change_already_pending",
                "Für dieses Mitglied wartet bereits eine E-Mail-Korrektur auf Bestätigung.",
            )
        raise Conflict(
            "email_change_context_changed",
            "Der Kontostand hat sich geändert. Lade das Mitglied neu und versuche es erneut.",
        )

    async def confirm_magic(
        self,
        token: str,
        *,
        request_id: str,
    ) -> EmailChangeConfirmation:
        try:
            digest = email_change_token_digest(token)
        except (DomainInvariantError, ValueError):
            self._reject()
        return await self._confirm(
            token_digest=digest,
            email=None,
            code_digest=None,
            request_id=request_id,
        )

    async def confirm_code(
        self,
        email: str,
        raw_code: str,
        *,
        request_id: str,
    ) -> EmailChangeConfirmation:
        try:
            normalized_email = normalize_email(email)
            code = EmailChangeCode(raw_code)
            digest = email_change_code_digest(
                normalized_email,
                code,
                self._hmac_secret,
            )
        except (DomainInvariantError, ValueError):
            self._reject()
        return await self._confirm(
            token_digest=None,
            email=normalized_email,
            code_digest=digest,
            request_id=request_id,
        )

    async def _confirm(
        self,
        *,
        token_digest: str | None,
        email: str | None,
        code_digest: str | None,
        request_id: str,
    ) -> EmailChangeConfirmation:
        result, confirmation = await self._repository.confirm(
            token_digest=token_digest,
            email=email,
            code_digest=code_digest,
            completion_mail_events=self._completion_mail_events,
            request_id=request_id,
            occurred_at=self._clock(),
        )
        if result is EmailChangeConfirmResult.ADDRESS_IN_USE:
            raise Conflict(
                "email_change_address_in_use",
                "Diese E-Mail-Adresse kann nicht mehr verwendet werden. Bitte fordere eine neue Korrektur an.",
            )
        if result is not EmailChangeConfirmResult.CONFIRMED or confirmation is None:
            self._reject()
        return confirmation

    def _request_mail_events(
        self,
        change: PendingEmailChange,
        token: str,
        code: EmailChangeCode,
    ) -> tuple[PendingOutboxEvent, ...]:
        link = f"{self._public_base_url}/email-change?token={token}"
        confirmation_text = (
            f"Hallo {change.display_name_snapshot},\n\n"
            "für dein LeonAid-Konto wurde eine neue Login-E-Mail angefordert.\n\n"
            f"Bestätigungslink: {link}\n"
            f"Alternativ kannst du für {change.new_email_snapshot} "
            f"den Code {code.value} verwenden.\n\n"
            f"Link und Code sind bis {change.expires_at.isoformat()} gültig. "
            "Ohne Bestätigung bleibt die bisherige Login-E-Mail aktiv."
        )
        security_text = (
            f"Hallo {change.display_name_snapshot},\n\n"
            "ein LeonAid-System-Admin hat eine Änderung deiner Login-E-Mail "
            "angefordert. Deine bisherige Adresse bleibt aktiv, bis die neue "
            "Adresse die Änderung bestätigt.\n\n"
            "Wenn du das nicht erwartest, wende dich bitte an deinen "
            "Charity- oder System-Admin."
        )
        return (
            self._mail_event(
                change,
                "request-old",
                recipient=change.old_email_snapshot,
                subject="Änderung deiner LeonAid-Login-E-Mail angefordert",
                text=security_text,
            ),
            self._mail_event(
                change,
                "request-new",
                recipient=change.new_email_snapshot,
                subject="Neue LeonAid-Login-E-Mail bestätigen",
                text=confirmation_text,
            ),
        )

    def _completion_mail_events(
        self,
        change: PendingEmailChange,
    ) -> tuple[PendingOutboxEvent, ...]:
        text = (
            f"Hallo {change.display_name_snapshot},\n\n"
            "deine LeonAid-Login-E-Mail wurde bestätigt und geändert. "
            "Alle bisherigen Sitzungen wurden beendet. Melde dich beim "
            "nächsten Zugriff mit der neuen Adresse an.\n\n"
            "Wenn du das nicht erwartest, informiere bitte sofort einen "
            "System-Admin."
        )
        return (
            self._mail_event(
                change,
                "completed-old",
                recipient=change.old_email_snapshot,
                subject="LeonAid-Login-E-Mail wurde geändert",
                text=text,
            ),
            self._mail_event(
                change,
                "completed-new",
                recipient=change.new_email_snapshot,
                subject="LeonAid-Login-E-Mail bestätigt",
                text=text,
            ),
        )

    def _mail_event(
        self,
        change: PendingEmailChange,
        kind: str,
        *,
        recipient: str,
        subject: str,
        text: str,
    ) -> PendingOutboxEvent:
        return PendingOutboxEvent(
            id=uuid5(EMAIL_CHANGE_MAIL_NAMESPACE, f"{change.id}:{kind}"),
            aggregate_type="email_change",
            aggregate_id=change.id,
            event_type="mail.send.v1",
            idempotency_key=f"email-change:{change.id}:{kind}",
            payload=self._mail_payload.protect(
                recipient=recipient,
                subject=subject,
                text=text,
            ),
        )

    @staticmethod
    def _reject() -> Never:
        raise ApplicationError(
            "email_change_invalid",
            "Diese E-Mail-Korrektur ist ungültig oder nicht mehr gültig.",
        )
