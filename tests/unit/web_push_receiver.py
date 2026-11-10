"""The receiving side of Web Push, as a user agent implements it.

Written from RFC 8291 section 3.4 ("For a user agent") and RFC 8188
section 2, independent of the sender in ``leonaid.adapters.web_push``: the
tests decrypt what LeonAid sends with the subscription's private key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def public_point(key: ec.EllipticCurvePrivateKey) -> bytes:
    numbers = key.public_key().public_numbers()
    return b"\x04" + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")


def _hmac(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def decrypt_push_message(
    body: bytes,
    *,
    ua_private: ec.EllipticCurvePrivateKey,
    auth_secret: bytes,
) -> bytes:
    """Read one ``aes128gcm`` push message; raises on any deviation."""

    salt = body[:16]
    record_size = int.from_bytes(body[16:20], "big")
    key_length = body[20]
    if key_length != 65:
        raise ValueError("keyid is not an uncompressed P-256 point")
    as_public = body[21 : 21 + key_length]
    ciphertext = body[21 + key_length :]
    if len(ciphertext) > record_size:
        raise ValueError("more than one record")
    ecdh_secret = ua_private.exchange(
        ec.ECDH(),
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public),
    )
    prk_key = _hmac(auth_secret, ecdh_secret)
    key_info = b"WebPush: info\x00" + public_point(ua_private) + as_public
    ikm = _hmac(prk_key, key_info + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    padded = AESGCM(cek).decrypt(nonce, ciphertext, None)
    plaintext = padded.rstrip(b"\x00")
    if not plaintext.endswith(b"\x02"):
        raise ValueError("padding delimiter of the last record is missing")
    return plaintext[:-1]
