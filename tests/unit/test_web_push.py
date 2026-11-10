"""Web Push sending: RFC 8291 encryption, RFC 8292 VAPID, endpoint rules.

The encryption vector is the example of RFC 8291 section 5 with the
intermediate values of its Appendix A, copied from the RFC text
(https://www.rfc-editor.org/rfc/rfc8291.txt).
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from leonaid.adapters.web_push import (
    MAX_PLAINTEXT_OCTETS,
    VapidSigner,
    WebPushSender,
    encrypt_push_message,
    generate_vapid_private_key,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.push import (
    PushEndpointPolicy,
    PushOutcome,
    PushTarget,
    require_push_keys,
)
from tests.unit.web_push_receiver import b64url_decode, decrypt_push_message

# RFC 8291, section 5 and Appendix A.
RFC_PLAINTEXT = b"When I grow up, I want to be a watermelon"
RFC_AUTH_SECRET = "BTBZMqHH6r4Tts7J_aSIgg"
RFC_UA_PRIVATE = "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"
RFC_UA_PUBLIC = (
    "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcx"
    "aOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
)
RFC_AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
RFC_AS_PUBLIC = (
    "BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIg"
    "Dll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
)
RFC_SALT = "DGv6ra1nlYgDCS1FRnbzlw"
RFC_BODY = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
    "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
    "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
)

NOW = datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)
SUBJECT = "mailto:betrieb@leonaid.invalid"


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def private_key(encoded: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(
        int.from_bytes(b64url_decode(encoded), "big"), ec.SECP256R1()
    )


def test_encryption_reproduces_the_rfc_8291_example() -> None:
    body = encrypt_push_message(
        RFC_PLAINTEXT,
        ua_public=b64url_decode(RFC_UA_PUBLIC),
        auth_secret=b64url_decode(RFC_AUTH_SECRET),
        as_private=private_key(RFC_AS_PRIVATE),
        salt=b64url_decode(RFC_SALT),
    )

    assert b64url(body) == RFC_BODY
    # The header names the sender key of the example (keyid, 65 octets).
    assert body[21:86] == b64url_decode(RFC_AS_PUBLIC)
    # Header (86), plaintext (41), delimiter (1), tag (16). The example's
    # "Content-Length: 145" does not match its own body of 144 octets.
    assert len(body) == 144


def test_the_receiver_of_the_rfc_example_reads_the_plaintext() -> None:
    plaintext = decrypt_push_message(
        b64url_decode(RFC_BODY),
        ua_private=private_key(RFC_UA_PRIVATE),
        auth_secret=b64url_decode(RFC_AUTH_SECRET),
    )

    assert plaintext == RFC_PLAINTEXT


def test_each_message_gets_a_fresh_sender_key_and_salt() -> None:
    receiver = ec.generate_private_key(ec.SECP256R1())
    ua_public = receiver.public_key().public_numbers()
    point = b"\x04" + ua_public.x.to_bytes(32, "big") + ua_public.y.to_bytes(32, "big")
    auth = bytes(range(16))

    first = encrypt_push_message(b"{}", ua_public=point, auth_secret=auth)
    second = encrypt_push_message(b"{}", ua_public=point, auth_secret=auth)

    assert first[:16] != second[:16]
    assert first[21:86] != second[21:86]
    assert decrypt_push_message(first, ua_private=receiver, auth_secret=auth) == b"{}"
    assert decrypt_push_message(second, ua_private=receiver, auth_secret=auth) == b"{}"


def test_encryption_refuses_what_a_push_service_need_not_carry() -> None:
    receiver = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()
    point = b"\x04" + receiver.x.to_bytes(32, "big") + receiver.y.to_bytes(32, "big")

    with pytest.raises(ValueError, match="plaintext"):
        encrypt_push_message(
            b"x" * (MAX_PLAINTEXT_OCTETS + 1), ua_public=point, auth_secret=bytes(16)
        )
    with pytest.raises(ValueError, match="auth"):
        encrypt_push_message(b"{}", ua_public=point, auth_secret=bytes(15))
    with pytest.raises(ValueError):
        # Not a point on P-256.
        encrypt_push_message(
            b"{}", ua_public=b"\x04" + bytes(64), auth_secret=bytes(16)
        )


def decode_segment(segment: str) -> dict[str, object]:
    value = json.loads(b64url_decode(segment))
    assert isinstance(value, dict)
    return value


def test_vapid_token_is_signed_with_the_configured_key() -> None:
    encoded = generate_vapid_private_key()
    signer = VapidSigner(encoded, SUBJECT)

    header = signer.authorization(
        "https://FCM.googleapis.com:443/fcm/send/abc:def?x=1", now=NOW
    )

    assert header.startswith("vapid t=")
    token, key = header.removeprefix("vapid t=").split(", k=")
    assert key == signer.public_key
    public_point = b64url_decode(key)
    assert len(public_point) == 65 and public_point[0] == 4
    head, claims, signature = token.split(".")
    assert decode_segment(head) == {"typ": "JWT", "alg": "ES256"}
    assert decode_segment(claims) == {
        # RFC 8292 section 2: the origin of the push resource, nothing more,
        # in the spelling the push service uses for itself.
        "aud": "https://fcm.googleapis.com",
        "exp": int((NOW + timedelta(hours=12)).timestamp()),
        "sub": SUBJECT,
    }
    raw = b64url_decode(signature)
    assert len(raw) == 64
    verifier = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), public_point
    )
    der = encode_dss_signature(
        int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
    )
    verifier.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    with pytest.raises(InvalidSignature):
        verifier.verify(der, f"{head}.{claims}x".encode(), ec.ECDSA(hashes.SHA256()))
    # The public key belongs to the configured private key.
    assert public_point == _public_point(private_key(encoded))


def _public_point(key: ec.EllipticCurvePrivateKey) -> bytes:
    numbers = key.public_key().public_numbers()
    return b"\x04" + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")


@pytest.mark.parametrize(
    "key",
    ["", "AAAA", b64url(bytes(32)), b64url(b"\xff" * 32), "not base64 !!"],
)
def test_vapid_refuses_a_key_that_is_no_p256_scalar(key: str) -> None:
    with pytest.raises(ValueError):
        VapidSigner(key, SUBJECT)


@pytest.mark.parametrize(
    "subject",
    ["", "betrieb@leonaid.invalid", "http://leonaid.invalid", "mailto:", "mailto:a b"],
)
def test_vapid_refuses_a_subject_that_is_no_contact(subject: str) -> None:
    with pytest.raises(ValueError):
        VapidSigner(generate_vapid_private_key(), subject)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com/fcm/send/abc",
        "https://fcm.googleapis.com/wp/abc",
        "https://jmt17.google.com/fcm/send/abc",
        "https://updates.push.services.mozilla.com/wpush/v2/abc",
        "https://web.push.apple.com/abc",
        "https://wns2-par02p.notify.windows.com/w/?token=abc",
        "https://FCM.googleapis.com:443/fcm/send/abc",
    ],
)
def test_endpoints_of_the_known_push_services_pass(endpoint: str) -> None:
    assert PushEndpointPolicy().require(endpoint) == endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/abc",
        "https://fcm.googleapis.com.attacker.example/fcm/send/abc",
        "https://attacker.example/fcm.googleapis.com",
        "https://user@fcm.googleapis.com/fcm/send/abc",
        "https://fcm.googleapis.com:8443/fcm/send/abc",
        "https://notify.windows.com.attacker.example/w",
        "https://evilpush.apple.com/abc",
        # APNs is Apple's service for native apps, not for Web Push.
        "https://api.push.apple.com/3/device/abc",
        "https://127.0.0.1/abc",
        "https://core-postgres:5432/",
        "https://fcm.googleapis.com/fcm/send/abc#fragment",
        # Characters that URL parsers strip or rewrite.
        "https://fcm.googleapis.com/fcm/send/a\tbc",
        "https://fcm.googleapis.com/fcm/send/abc\n",
        " https://fcm.googleapis.com/fcm/send/abc",
        "https://fcm.googleapis.com/fcm/send/abc\x00",
        "https://fcm。googleapis。com/fcm/send/abc",
        "https://attacker.example\\@fcm.googleapis.com/fcm/send/abc",
        "https://fcm.googleapis.com\\.attacker.example/fcm/send/abc",
        "https://fcm.googleapis.com/" + "a" * 2100,
        "ftp://fcm.googleapis.com/abc",
        "",
        "https://",
    ],
)
def test_other_endpoints_are_refused(endpoint: str) -> None:
    with pytest.raises(DomainInvariantError) as captured:
        PushEndpointPolicy().require(endpoint)

    assert captured.value.code == "push_endpoint_not_allowed"


def test_an_extra_origin_is_a_whole_origin_never_a_suffix() -> None:
    policy = PushEndpointPolicy(extra_origins=frozenset({"http://127.0.0.1:9911"}))

    assert policy.require("http://127.0.0.1:9911/push/a") == (
        "http://127.0.0.1:9911/push/a"
    )
    for endpoint in (
        "http://127.0.0.1:9912/push/a",
        "https://127.0.0.1:9911/push/a",
        "http://127.0.0.1.attacker.example:9911/push/a",
    ):
        with pytest.raises(DomainInvariantError):
            policy.require(endpoint)


def test_subscription_keys_must_be_a_p256_point_and_16_octets() -> None:
    receiver = ec.generate_private_key(ec.SECP256R1())
    point = b64url(_public_point(receiver))

    assert require_push_keys(point, b64url(bytes(16))) == (
        _public_point(receiver),
        bytes(16),
    )
    for p256dh, auth in (
        (point, b64url(bytes(15))),
        (b64url(bytes(65)), b64url(bytes(16))),
        (b64url(b"\x02" + bytes(32)), b64url(bytes(16))),
        ("%%%", b64url(bytes(16))),
    ):
        with pytest.raises(DomainInvariantError) as captured:
            require_push_keys(p256dh, auth)
        assert captured.value.code == "push_subscription_keys_invalid"


def target(endpoint: str) -> PushTarget:
    receiver = ec.generate_private_key(ec.SECP256R1())
    return PushTarget(endpoint=endpoint, p256dh=_public_point(receiver), auth=bytes(16))


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (201, PushOutcome.DELIVERED),
        (200, PushOutcome.DELIVERED),
        (404, PushOutcome.GONE),
        (410, PushOutcome.GONE),
        (400, PushOutcome.REJECTED),
        (403, PushOutcome.REJECTED),
        (413, PushOutcome.REJECTED),
        (429, PushOutcome.UNAVAILABLE),
        (500, PushOutcome.UNAVAILABLE),
        (503, PushOutcome.UNAVAILABLE),
        # A redirect is never followed: it could leave the allowlist.
        (307, PushOutcome.REJECTED),
    ],
)
@pytest.mark.asyncio
async def test_the_push_service_answer_decides_the_outcome(
    status: int, outcome: PushOutcome
) -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            status, headers={"location": "https://attacker.example/x"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
        sender = WebPushSender(
            VapidSigner(generate_vapid_private_key(), SUBJECT),
            client,
            PushEndpointPolicy(),
        )
        result = await sender.send(
            target("https://fcm.googleapis.com/fcm/send/abc"),
            b'{"kind":"feed","count":1,"path":"/app/activities"}',
            topic="feed",
            now=NOW,
        )

    assert result.outcome is outcome
    # For the operator's log: the host and the status, never the path.
    assert result.host == "fcm.googleapis.com"
    assert result.status == status
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.headers["content-encoding"] == "aes128gcm"
    assert request.headers["ttl"] == "86400"
    assert request.headers["topic"] == "feed"
    assert request.headers["urgency"] == "normal"
    assert request.headers["authorization"].startswith("vapid t=")
    # The body is ciphertext: nothing of the payload is readable in it.
    assert b"feed" not in request.content


@pytest.mark.asyncio
async def test_the_sender_never_calls_a_host_outside_the_allowlist() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request to {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
        sender = WebPushSender(
            VapidSigner(generate_vapid_private_key(), SUBJECT),
            client,
            PushEndpointPolicy(),
        )
        result = await sender.send(
            target("https://core-postgres:5432/"), b"{}", topic="feed", now=NOW
        )

    assert result.outcome is PushOutcome.GONE
    assert result.status is None


@pytest.mark.asyncio
async def test_a_network_failure_is_a_temporary_outcome() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
        sender = WebPushSender(
            VapidSigner(generate_vapid_private_key(), SUBJECT),
            client,
            PushEndpointPolicy(),
        )
        result = await sender.send(
            target("https://web.push.apple.com/abc"), b"{}", topic="feed", now=NOW
        )

    assert result.outcome is PushOutcome.UNAVAILABLE
    assert (result.host, result.status) == ("web.push.apple.com", None)


def test_the_vapid_audience_keeps_a_port_that_is_not_the_default() -> None:
    signer = VapidSigner(generate_vapid_private_key(), SUBJECT)

    header = signer.authorization("http://127.0.0.1:9911/push/a", now=NOW)

    claims = header.removeprefix("vapid t=").split(".")[1]
    assert decode_segment(claims)["aud"] == "http://127.0.0.1:9911"


@pytest.mark.asyncio
async def test_a_request_ends_after_its_deadline_as_a_whole() -> None:
    async def never(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(never)) as client:
        sender = WebPushSender(
            VapidSigner(generate_vapid_private_key(), SUBJECT),
            client,
            PushEndpointPolicy(),
            request_seconds=0.05,
        )
        started = asyncio.get_running_loop().time()
        result = await sender.send(
            target("https://fcm.googleapis.com/fcm/send/abc"),
            b"{}",
            topic="feed",
            now=NOW,
        )

    assert result.outcome is PushOutcome.UNAVAILABLE
    assert asyncio.get_running_loop().time() - started < 2


@pytest.mark.parametrize(
    ("endpoint", "name"),
    [
        ("https://fcm.googleapis.com/fcm/send/secret-token", "fcm.googleapis.com"),
        ("https://FCM.googleapis.com:443/fcm/send/x", "fcm.googleapis.com"),
        ("https://web.push.apple.com/secret", "web.push.apple.com"),
        # Below notify.windows.com a member chooses the labels: cut off.
        ("https://wns2-par02p.notify.windows.com/w/?token=x", "notify.windows.com"),
        (
            "https://" + "a" * 60 + ".member-chosen.notify.windows.com/w/x",
            "notify.windows.com",
        ),
        ("https://attacker.example/x", ""),
        ("https://core-postgres:5432/", ""),
    ],
)
def test_the_logged_host_is_the_push_service_never_a_members_label(
    endpoint: str, name: str
) -> None:
    assert PushEndpointPolicy().service_name(endpoint) == name


def test_the_logged_host_of_a_proof_origin_is_bounded() -> None:
    host = "h" * 63 + "." + "i" * 63 + ".invalid"
    policy = PushEndpointPolicy(extra_origins=frozenset({f"http://{host}:9911"}))

    assert policy.service_name(f"http://{host}:9911/push/a") == host[:64]


@pytest.mark.asyncio
async def test_no_answer_names_the_service_and_no_status() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
        sender = WebPushSender(
            VapidSigner(generate_vapid_private_key(), SUBJECT),
            client,
            PushEndpointPolicy(),
        )
        result = await sender.send(
            target("https://db5p-member.notify.windows.com/w/?token=secret"),
            b"{}",
            topic="feed",
            now=NOW,
        )

    assert (result.outcome, result.host, result.status) == (
        PushOutcome.UNAVAILABLE,
        "notify.windows.com",
        None,
    )
    assert result.blames_device is False
