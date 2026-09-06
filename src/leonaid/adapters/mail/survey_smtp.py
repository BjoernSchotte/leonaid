"""Invitation mail with current lifecycle/revocation checks before SMTP."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
import asyncpg
from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.adapters.mail.smtp import SmtpMailHandler
from leonaid.adapters.mail.transport import SmtpTransport
from leonaid.domain.outbox import ClaimedOutboxEvent


class SurveyInvitationSmtpHandler:
    def __init__(
        self,
        pool: asyncpg.Pool[Any],
        *,
        transport: SmtpTransport,
        secure_payload: SecureMailPayload,
    ):
        self.pool = pool
        self.mail = SmtpMailHandler(
            pool, transport=transport, secure_payload=secure_payload
        )

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            # Same survey-first lock order as revocation, closing and response writes.
            survey = await conn.fetchrow(
                "SELECT s.* FROM survey s JOIN survey_invitation i ON i.survey_id=s.id WHERE i.id=$1 FOR UPDATE OF s",
                event.aggregate_id,
            )
            if survey is None:
                return
            invitation = await conn.fetchrow(
                "SELECT * FROM survey_invitation WHERE id=$1 FOR UPDATE",
                event.aggregate_id,
            )
            now = datetime.now(timezone.utc)
            if (
                invitation is None
                or invitation["sent_at"]
                or invitation["revoked_at"]
                or invitation["expires_at"] <= now
                or survey["status"] != "active"
                or (survey["ends_at"] and survey["ends_at"] <= now)
            ):
                return
            payload = invitation["mail_payload"]
            if not payload:
                return
            await self.mail.handle(replace(event, payload={"secureMail": payload}))
            await conn.execute(
                "UPDATE survey_invitation SET sent_at=now(),mail_payload=NULL WHERE id=$1",
                event.aggregate_id,
            )
