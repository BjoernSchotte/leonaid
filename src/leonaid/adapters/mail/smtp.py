"""SMTP outbox handler with a durable idempotency ledger."""

from __future__ import annotations

import asyncio
import hashlib
from email.message import EmailMessage
from typing import Any
from uuid import UUID, uuid5

import asyncpg

from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.adapters.mail.transport import SmtpTransport
from leonaid.domain.outbox import ClaimedOutboxEvent

MAIL_DELIVERY_NAMESPACE = UUID("8a30d44c-d313-4cc6-af6a-237af95a4d4c")


class SmtpMailHandler:
    def __init__(
        self,
        pool: asyncpg.Pool[Any],
        *,
        transport: SmtpTransport,
        secure_payload: SecureMailPayload | None = None,
    ) -> None:
        self._pool = pool
        self._transport = transport
        self._secure_payload = secure_payload

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        fields = self._mail_fields(event)
        recipient = fields["to"]
        subject = fields["subject"]
        text = fields["text"]
        if await self._was_sent(event.idempotency_key):
            return

        message_id = self.message_id(event.idempotency_key)
        message = EmailMessage()
        message["From"] = self._transport.sender
        message["To"] = recipient
        message["Subject"] = subject
        message["Message-ID"] = message_id
        message.set_content(text)
        await asyncio.to_thread(self._send, message)

        recipient_sha256 = hashlib.sha256(
            recipient.strip().casefold().encode()
        ).hexdigest()
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO mail_delivery (
                    id, outbox_event_id, idempotency_key, message_id,
                    recipient_sha256, status
                )
                VALUES ($1, $2, $3, $4, $5, 'sent')
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                uuid5(MAIL_DELIVERY_NAMESPACE, event.idempotency_key),
                event.id,
                event.idempotency_key,
                message_id,
                recipient_sha256,
            )

    def _send(self, message: EmailMessage) -> None:
        self._transport.send(message)

    async def _was_sent(self, idempotency_key: str) -> bool:
        async with self._pool.acquire() as connection:
            return bool(
                await connection.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM mail_delivery
                        WHERE idempotency_key = $1 AND status = 'sent'
                    )
                    """,
                    idempotency_key,
                )
            )

    @staticmethod
    def message_id(idempotency_key: str) -> str:
        digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
        return f"<{digest}@outbox.leonaid.invalid>"

    @staticmethod
    def _required_text(event: ClaimedOutboxEvent, key: str) -> str:
        value = event.payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Mail-Payload-Feld {key} fehlt.")
        return value

    def _mail_fields(self, event: ClaimedOutboxEvent) -> dict[str, str]:
        encrypted = event.payload.get("secureMail")
        if encrypted is None:
            return {
                key: self._required_text(event, key)
                for key in ("to", "subject", "text")
            }
        if not isinstance(encrypted, str) or self._secure_payload is None:
            raise ValueError("Sicherer Mail-Payload kann nicht gelesen werden.")
        return self._secure_payload.reveal(encrypted)
