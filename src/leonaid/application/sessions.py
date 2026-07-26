"""Passwordless login, fresh authentication and session revocation."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Never, Protocol
from uuid import UUID, uuid4, uuid5

from leonaid.application.errors import (
    AuthenticationRequired,
    ResourceNotFound,
)
from leonaid.application.policies import require_system_admin
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.invitations import normalize_email
from leonaid.domain.outbox import JsonValue, PendingOutboxEvent
from leonaid.domain.sessions import (
    SESSION_LIFETIME,
    LoginChallenge,
    LoginChallengeStatus,
    LoginCode,
    LoginPurpose,
    login_code_digest,
    login_magic_digest,
    session_token_digest,
)

LOGIN_MAIL_NAMESPACE = UUID("aa259f26-d8cc-46f5-a317-6146721fe16e")


@dataclass(frozen=True, slots=True)
class LoginAccount:
    id: UUID
    email: str
    display_name: str


@dataclass(frozen=True, slots=True)
class SessionGrant:
    session_id: UUID
    user_id: UUID
    display_name: str
    raw_token: str
    expires_at: datetime
    fresh_login_at: datetime


@dataclass(frozen=True, slots=True)
class SessionCompletion:
    account: LoginAccount
    session_id: UUID
    expires_at: datetime


class SessionRepository(Protocol):
    async def active_account_for_email(self, email: str) -> LoginAccount | None: ...

    async def create_challenge(
        self,
        challenge: LoginChallenge,
        mail_event: PendingOutboxEvent,
        *,
        requested_by_user_id: UUID | None,
        request_id: str,
        occurred_at: datetime,
    ) -> bool: ...

    async def complete_login(
        self,
        *,
        purpose: LoginPurpose,
        token_digest: str | None,
        email: str | None,
        code_digest: str | None,
        session_id: UUID,
        session_token_digest: str,
        session_expires_at: datetime,
        current_session_digest: str | None,
        device_hint: str | None,
        request_id: str,
        occurred_at: datetime,
    ) -> SessionCompletion | None: ...

    async def issue_session(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        token_digest: str,
        expires_at: datetime,
        device_hint: str | None,
        request_id: str,
        occurred_at: datetime,
    ) -> LoginAccount | None: ...

    async def revoke_session(
        self,
        *,
        token_digest: str,
        request_id: str,
        occurred_at: datetime,
    ) -> bool: ...

    async def revoke_user_sessions(
        self,
        *,
        target_user_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> int | None: ...


class LoginMailPayloadProtector(Protocol):
    def protect(
        self,
        *,
        recipient: str,
        subject: str,
        text: str,
    ) -> dict[str, JsonValue]: ...


class SessionService:
    def __init__(
        self,
        repository: SessionRepository,
        mail_payload: LoginMailPayloadProtector,
        *,
        hmac_secret: str,
        public_base_url: str,
        challenge_ttl: timedelta = timedelta(minutes=10),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len(hmac_secret) < 32:
            raise ValueError("Der Login-Schlüssel ist zu kurz.")
        if challenge_ttl < timedelta(minutes=5) or challenge_ttl > timedelta(
            minutes=30
        ):
            raise ValueError(
                "Die Login-Challenge muss zwischen 5 und 30 Minuten gültig sein."
            )
        if not public_base_url.startswith(("http://", "https://")):
            raise ValueError("Die öffentliche Basis-URL ist ungültig.")
        self._repository = repository
        self._mail_payload = mail_payload
        self._hmac_secret = hmac_secret
        self._public_base_url = public_base_url.rstrip("/")
        self._challenge_ttl = challenge_ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def request_login(
        self,
        email: str,
        *,
        request_id: str,
    ) -> None:
        normalized_email = normalize_email(email)
        account = await self._repository.active_account_for_email(normalized_email)
        if account is None:
            code = LoginCode.generate()
            login_code_digest(
                normalized_email,
                code,
                self._hmac_secret,
                LoginPurpose.LOGIN,
            )
            login_magic_digest(secrets.token_urlsafe(32))
            return
        await self._create_challenge(
            account,
            LoginPurpose.LOGIN,
            requested_by_user_id=None,
            request_id=request_id,
        )

    async def request_fresh_login(
        self,
        actor: IdentityPrincipal,
        *,
        request_id: str,
    ) -> None:
        if not actor.account.can_authenticate:
            self._reject()
        await self._create_challenge(
            LoginAccount(
                id=actor.account.id,
                email=actor.account.email,
                display_name=actor.account.display_name,
            ),
            LoginPurpose.FRESH_LOGIN,
            requested_by_user_id=actor.account.id,
            request_id=request_id,
        )

    async def complete_login_magic(
        self,
        magic_token: str,
        *,
        device_hint: str | None,
        request_id: str,
    ) -> SessionGrant:
        try:
            digest = login_magic_digest(magic_token)
        except (DomainInvariantError, ValueError):
            self._reject()
        return await self._complete(
            purpose=LoginPurpose.LOGIN,
            token_digest=digest,
            email=None,
            code_digest=None,
            current_session_token=None,
            device_hint=device_hint,
            request_id=request_id,
        )

    async def complete_login_code(
        self,
        email: str,
        raw_code: str,
        *,
        device_hint: str | None,
        request_id: str,
    ) -> SessionGrant:
        normalized_email, digest = self._code_credential(
            email,
            raw_code,
            LoginPurpose.LOGIN,
        )
        return await self._complete(
            purpose=LoginPurpose.LOGIN,
            token_digest=None,
            email=normalized_email,
            code_digest=digest,
            current_session_token=None,
            device_hint=device_hint,
            request_id=request_id,
        )

    async def complete_fresh_magic(
        self,
        current_session_token: str | None,
        magic_token: str,
        *,
        device_hint: str | None,
        request_id: str,
    ) -> SessionGrant:
        try:
            digest = login_magic_digest(magic_token)
        except (DomainInvariantError, ValueError):
            self._reject()
        return await self._complete(
            purpose=LoginPurpose.FRESH_LOGIN,
            token_digest=digest,
            email=None,
            code_digest=None,
            current_session_token=current_session_token,
            device_hint=device_hint,
            request_id=request_id,
        )

    async def complete_fresh_code(
        self,
        actor: IdentityPrincipal,
        current_session_token: str | None,
        raw_code: str,
        *,
        device_hint: str | None,
        request_id: str,
    ) -> SessionGrant:
        normalized_email, digest = self._code_credential(
            actor.account.email,
            raw_code,
            LoginPurpose.FRESH_LOGIN,
        )
        return await self._complete(
            purpose=LoginPurpose.FRESH_LOGIN,
            token_digest=None,
            email=normalized_email,
            code_digest=digest,
            current_session_token=current_session_token,
            device_hint=device_hint,
            request_id=request_id,
        )

    async def issue_for_user(
        self,
        user_id: UUID,
        *,
        device_hint: str | None,
        request_id: str,
    ) -> SessionGrant:
        now = self._clock()
        raw_token, digest = self._new_session_token()
        session_id = uuid4()
        account = await self._repository.issue_session(
            user_id=user_id,
            session_id=session_id,
            token_digest=digest,
            expires_at=now + SESSION_LIFETIME,
            device_hint=self._device_hint(device_hint),
            request_id=request_id,
            occurred_at=now,
        )
        if account is None:
            self._reject()
        return SessionGrant(
            session_id=session_id,
            user_id=account.id,
            display_name=account.display_name,
            raw_token=raw_token,
            expires_at=now + SESSION_LIFETIME,
            fresh_login_at=now,
        )

    async def logout(
        self,
        current_session_token: str | None,
        *,
        request_id: str,
    ) -> None:
        if current_session_token is None:
            return
        try:
            digest = session_token_digest(current_session_token)
        except (DomainInvariantError, ValueError):
            return
        await self._repository.revoke_session(
            token_digest=digest,
            request_id=request_id,
            occurred_at=self._clock(),
        )

    async def revoke_all_for_user(
        self,
        actor: IdentityPrincipal,
        target_user_id: UUID,
        *,
        request_id: str,
    ) -> int:
        require_system_admin(actor)
        revoked = await self._repository.revoke_user_sessions(
            target_user_id=target_user_id,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=self._clock(),
        )
        if revoked is None:
            raise ResourceNotFound(
                "user_not_found",
                "Das Benutzerkonto wurde nicht gefunden.",
            )
        return revoked

    async def _create_challenge(
        self,
        account: LoginAccount,
        purpose: LoginPurpose,
        *,
        requested_by_user_id: UUID | None,
        request_id: str,
    ) -> None:
        now = self._clock()
        magic_token = secrets.token_urlsafe(32)
        code = LoginCode.generate()
        challenge = LoginChallenge(
            id=uuid4(),
            user_id=account.id,
            purpose=purpose,
            email_snapshot=account.email,
            token_digest=login_magic_digest(magic_token),
            code_digest=login_code_digest(
                account.email,
                code,
                self._hmac_secret,
                purpose,
            ),
            status=LoginChallengeStatus.PENDING,
            created_at=now,
            expires_at=now + self._challenge_ttl,
        )
        await self._repository.create_challenge(
            challenge,
            self._mail_event(account, challenge, magic_token, code),
            requested_by_user_id=requested_by_user_id,
            request_id=request_id,
            occurred_at=now,
        )

    async def _complete(
        self,
        *,
        purpose: LoginPurpose,
        token_digest: str | None,
        email: str | None,
        code_digest: str | None,
        current_session_token: str | None,
        device_hint: str | None,
        request_id: str,
    ) -> SessionGrant:
        try:
            current_digest = (
                session_token_digest(current_session_token)
                if current_session_token is not None
                else None
            )
        except (DomainInvariantError, ValueError):
            self._reject()
        if purpose is LoginPurpose.FRESH_LOGIN and current_digest is None:
            self._reject()
        now = self._clock()
        raw_token, new_digest = self._new_session_token()
        session_id = uuid4()
        completion = await self._repository.complete_login(
            purpose=purpose,
            token_digest=token_digest,
            email=email,
            code_digest=code_digest,
            session_id=session_id,
            session_token_digest=new_digest,
            session_expires_at=now + SESSION_LIFETIME,
            current_session_digest=current_digest,
            device_hint=self._device_hint(device_hint),
            request_id=request_id,
            occurred_at=now,
        )
        if completion is None:
            self._reject()
        return SessionGrant(
            session_id=completion.session_id,
            user_id=completion.account.id,
            display_name=completion.account.display_name,
            raw_token=raw_token,
            expires_at=completion.expires_at,
            fresh_login_at=now,
        )

    def _code_credential(
        self,
        email: str,
        raw_code: str,
        purpose: LoginPurpose,
    ) -> tuple[str, str]:
        try:
            normalized_email = normalize_email(email)
            digest = login_code_digest(
                normalized_email,
                LoginCode(raw_code),
                self._hmac_secret,
                purpose,
            )
        except (DomainInvariantError, ValueError):
            self._reject()
        return normalized_email, digest

    def _mail_event(
        self,
        account: LoginAccount,
        challenge: LoginChallenge,
        magic_token: str,
        code: LoginCode,
    ) -> PendingOutboxEvent:
        if challenge.purpose is LoginPurpose.FRESH_LOGIN:
            path = "/fresh-login"
            subject = "LeonAid-Anmeldung bestätigen"
            purpose_text = "deine sensible Aktion freizugeben"
        else:
            path = "/login"
            subject = "Dein LeonAid-Login"
            purpose_text = "dich bei LeonAid anzumelden"
        link = f"{self._public_base_url}{path}?token={magic_token}"
        text = (
            f"Hallo {account.display_name},\n\n"
            f"nutze diesen Magic Link, um {purpose_text}:\n{link}\n\n"
            f"Alternativ kannst du den Code {code.value} verwenden.\n\n"
            f"Link und Code sind bis {challenge.expires_at.isoformat()} gültig "
            "und können nur einmal verwendet werden."
        )
        return PendingOutboxEvent(
            id=uuid5(LOGIN_MAIL_NAMESPACE, str(challenge.id)),
            aggregate_type="login_challenge",
            aggregate_id=challenge.id,
            event_type="mail.send.v1",
            idempotency_key=f"login-challenge-mail:{challenge.id}",
            payload=self._mail_payload.protect(
                recipient=account.email,
                subject=subject,
                text=text,
            ),
        )

    @staticmethod
    def _new_session_token() -> tuple[str, str]:
        raw = secrets.token_urlsafe(48)
        return raw, session_token_digest(raw)

    @staticmethod
    def _device_hint(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(
            "".join(
                character if character.isprintable() else " " for character in value
            ).split()
        )
        return cleaned[:160] or None

    @staticmethod
    def _reject() -> Never:
        raise AuthenticationRequired(
            "login_invalid",
            "Dieser Login ist ungültig oder nicht mehr gültig.",
        )
