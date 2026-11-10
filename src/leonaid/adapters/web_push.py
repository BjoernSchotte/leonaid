"""Web Push sending on `cryptography` and `httpx` (ADR-0017).

Message encryption after RFC 8291 (content coding ``aes128gcm``, RFC 8188)
and voluntary application server identification after RFC 8292 (VAPID).
One record per message, a fresh sender key and salt per message.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Final
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from leonaid.domain.push import (
    PushEndpointPolicy,
    PushOutcome,
    PushResult,
    PushTarget,
)

# RFC 8291 section 4: a push service need not carry more than 4096 octets;
# less the header (86), the padding delimiter (1) and the tag (16).
RECORD_SIZE: Final = 4096
MAX_PLAINTEXT_OCTETS: Final = RECORD_SIZE - 86 - 1 - 16
# How long a push service keeps a message for a device that is off.
PUSH_TTL_SECONDS: Final = 86400
# RFC 8292 section 2: "exp" must not be more than 24 hours ahead.
VAPID_LIFETIME: Final = timedelta(hours=12)
# Order of the P-256 group: a private key is a scalar in [1, n-1].
P256_ORDER: Final = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_MAILTO: Final = re.compile(r"mailto:[^\s@]+@[^\s@]+\Z")
_TOPIC: Final = re.compile(r"[A-Za-z0-9_-]{1,32}\Z")


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64url_decode(value: str) -> bytes:
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError) as error:
        raise ValueError("not base64url") from error


def _point(key: ec.EllipticCurvePublicKey) -> bytes:
    numbers = key.public_numbers()
    return b"\x04" + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")


def _hmac(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def generate_vapid_private_key() -> str:
    """A fresh P-256 private key as the base64url of its 32-octet scalar."""

    while True:
        candidate = secrets.token_bytes(32)
        if 1 <= int.from_bytes(candidate, "big") < P256_ORDER:
            return _b64url(candidate)


def encrypt_push_message(
    plaintext: bytes,
    *,
    ua_public: bytes,
    auth_secret: bytes,
    as_private: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
) -> bytes:
    """One ``aes128gcm`` record for the subscription (RFC 8291 section 3.4).

    ``as_private`` and ``salt`` are fresh per message; they are parameters
    only so that the RFC's example can be reproduced.
    """

    if len(plaintext) > MAX_PLAINTEXT_OCTETS:
        raise ValueError("plaintext is longer than one push record")
    if len(auth_secret) != 16:
        raise ValueError("auth secret must be 16 octets")
    # Rejects anything that is no point on P-256. (Compressed points would
    # pass here; require_push_keys and the table accept 65 octets only.)
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    sender = as_private or ec.generate_private_key(ec.SECP256R1())
    salt = salt if salt is not None else os.urandom(16)
    if len(salt) != 16:
        raise ValueError("salt must be 16 octets")
    as_public = _point(sender.public_key())
    ecdh_secret = sender.exchange(ec.ECDH(), receiver)
    # HKDF with one block of output each, written out as in the RFC.
    prk_key = _hmac(auth_secret, ecdh_secret)
    key_info = b"WebPush: info\x00" + ua_public + as_public
    ikm = _hmac(prk_key, key_info + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    # 0x02 ends the last (here: only) record; no further padding.
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + ciphertext


class VapidSigner:
    """Signs the JWT a push service uses to recognise this installation."""

    def __init__(self, private_key: str, subject: str) -> None:
        scalar = _b64url_decode(private_key.strip())
        if len(scalar) != 32 or not 1 <= int.from_bytes(scalar, "big") < P256_ORDER:
            raise ValueError("VAPID private key must be a P-256 scalar as base64url")
        subject = subject.strip()
        if not self._valid_subject(subject):
            raise ValueError("VAPID subject must be a mailto: or https: contact")
        self._key = ec.derive_private_key(int.from_bytes(scalar, "big"), ec.SECP256R1())
        self._subject = subject
        self.public_key: Final = _b64url(_point(self._key.public_key()))

    @staticmethod
    def _valid_subject(subject: str) -> bool:
        if _MAILTO.fullmatch(subject):
            return True
        if any(character.isspace() for character in subject):
            return False
        parts = urlsplit(subject)
        return parts.scheme == "https" and bool(parts.hostname)

    def authorization(self, endpoint: str, *, now: datetime) -> str:
        """The ``Authorization`` header for a push to ``endpoint`` (RFC 8292 §3)."""

        parts = urlsplit(endpoint)
        # The origin as the push service names itself: lower case, without
        # the default port.
        port = parts.port
        default = {"https": 443, "http": 80}.get(parts.scheme)
        origin = f"{parts.scheme}://{(parts.hostname or '').lower()}" + (
            f":{port}" if port is not None and port != default else ""
        )
        claims = {
            "aud": origin,
            "exp": int((now + VAPID_LIFETIME).timestamp()),
            "sub": self._subject,
        }
        signing_input = ".".join(
            _b64url(json.dumps(part, separators=(",", ":")).encode())
            for part in ({"typ": "JWT", "alg": "ES256"}, claims)
        )
        r, s = decode_dss_signature(
            self._key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256()))
        )
        # JWS (RFC 7518 §3.4): r and s as two 32-octet integers, not DER.
        signature = _b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        return f"vapid t={signing_input}.{signature}, k={self.public_key}"


class WebPushSender:
    """Sends one encrypted message to one subscription.

    The client must not follow redirects (httpx's default): an answer that
    points elsewhere would leave the endpoint allowlist.
    """

    def __init__(
        self,
        vapid: VapidSigner,
        client: httpx.AsyncClient,
        endpoints: PushEndpointPolicy,
        *,
        request_seconds: float = 10.0,
    ) -> None:
        if client.follow_redirects:
            raise ValueError("The push client must not follow redirects.")
        self._request_seconds = request_seconds
        self._vapid = vapid
        self._client = client
        self._endpoints = endpoints

    async def send(
        self,
        target: PushTarget,
        payload: bytes,
        *,
        topic: str,
        now: datetime,
    ) -> PushResult:
        """One request, ended after ``request_seconds`` whatever it waits for.

        Never raises for what a push service or the network does: the
        answer is an outcome.
        """

        if not _TOPIC.fullmatch(topic):
            raise ValueError("A push topic is 1 to 32 base64url characters.")
        # Checked again here: a stored row is no proof of where it points.
        if not self._endpoints.allows(target.endpoint):
            return PushResult(PushOutcome.GONE, host="")
        host = self._endpoints.service_name(target.endpoint)
        try:
            body = encrypt_push_message(
                payload, ua_public=target.p256dh, auth_secret=target.auth
            )
        except ValueError:
            return PushResult(PushOutcome.GONE, host=host)
        try:
            # httpx counts its timeout per phase (connect, write, read); the
            # request as a whole gets one deadline.
            async with asyncio.timeout(self._request_seconds):
                response = await self._client.post(
                    target.endpoint,
                    content=body,
                    headers={
                        "Authorization": self._vapid.authorization(
                            target.endpoint, now=now
                        ),
                        "Content-Encoding": "aes128gcm",
                        "Content-Type": "application/octet-stream",
                        "TTL": str(PUSH_TTL_SECONDS),
                        # A newer message of the same kind replaces one the
                        # service still holds for a device that is off.
                        "Topic": topic,
                        "Urgency": "normal",
                    },
                )
        except (httpx.HTTPError, httpx.InvalidURL, TimeoutError):
            return PushResult(PushOutcome.UNAVAILABLE, host=host)
        status = response.status_code
        if 200 <= status < 300:
            outcome = PushOutcome.DELIVERED
        elif status in (404, 410):
            outcome = PushOutcome.GONE
        elif status == 429 or status >= 500:
            outcome = PushOutcome.UNAVAILABLE
        else:
            # 400, 401, 403, 413 and redirects: the service refuses this
            # message (a wrong VAPID key or subject, a malformed request).
            outcome = PushOutcome.REJECTED
        return PushResult(outcome, host=host, status=status)
