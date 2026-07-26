"""Authenticated encryption for short-lived, durable mail payloads."""

from __future__ import annotations

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from leonaid.domain.outbox import JsonValue


class SecureMailPayload:
    """Keep delivery credentials out of plaintext outbox rows."""

    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("Der Mail-Payload-Schlüssel ist zu kurz.")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        self._fernet = Fernet(key)

    def protect(
        self,
        *,
        recipient: str,
        subject: str,
        text: str,
    ) -> dict[str, JsonValue]:
        document = json.dumps(
            {"to": recipient, "subject": subject, "text": text},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return {"secureMail": self._fernet.encrypt(document).decode()}

    def reveal(self, ciphertext: str) -> dict[str, str]:
        try:
            value = json.loads(self._fernet.decrypt(ciphertext.encode()))
        except (InvalidToken, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Verschlüsselter Mail-Payload ist ungültig.") from error
        if not isinstance(value, dict):
            raise ValueError("Verschlüsselter Mail-Payload ist kein Objekt.")
        result = {key: value.get(key) for key in ("to", "subject", "text")}
        if any(
            not isinstance(item, str) or not item.strip() for item in result.values()
        ):
            raise ValueError("Verschlüsselter Mail-Payload ist unvollständig.")
        return {key: str(item) for key, item in result.items()}
