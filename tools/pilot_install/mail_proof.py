#!/usr/bin/env python3
"""Real-system mail proof for ./leonaid test-pilot-install.

The pilot's SMTP relay is played by Mailpit with STARTTLS required, SMTP AUTH
required and a certificate from a throwaway test CA. The subcommands run in
different containers of the isolated test project:

- ``certificates DIR`` (core image): write the test CA and the relay's
  certificate for MAIL_SMTP_HOST;
- ``core-send RECIPIENT`` (inside the running worker, script on stdin): send
  one message through the core's own SMTP transport and production settings;
- ``twenty-reset EMAIL`` (inside the running api, script on stdin): ask Twenty
  for a password reset link, which Twenty's worker sends by mail;
- ``assert-delivered API RECIPIENT FROM SUBJECT_WORD`` (Python image on the
  egress network): wait until Mailpit accepted that message.

Nothing here prints credentials or message bodies.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


def certificates(directory: Path, host: str) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "LeonAid pilot-install test CA")]
    )
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    (directory / "ca.pem").write_bytes(ca.public_bytes(pem))
    (directory / "cert.pem").write_bytes(leaf.public_bytes(pem))
    (directory / "key.pem").write_bytes(
        key.private_bytes(
            pem,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    for name in ("ca.pem", "cert.pem", "key.pem"):
        # Throwaway test material; Mailpit and Twenty run as other users.
        (directory / name).chmod(0o644)


def core_send(recipient: str) -> None:
    from email.message import EmailMessage

    from leonaid.adapters.mail.transport import SmtpTransport
    from leonaid.configuration import load_mail_transport_settings

    settings = load_mail_transport_settings()
    transport = SmtpTransport(
        host=settings.host,
        port=settings.port,
        sender=settings.sender,
        mode=settings.mode,
        username=settings.username,
        password=(
            settings.password.get_secret_value()
            if settings.password is not None
            else None
        ),
        timeout_seconds=settings.timeout_seconds,
        verify_certificates=settings.verify_certificates,
        ca_file=settings.ca_file,
        envelope_from=settings.envelope_from,
        reply_to=settings.reply_to,
    )
    message = EmailMessage()
    message["From"] = settings.sender
    message["To"] = recipient
    message["Subject"] = "LeonAid pilot-install relay probe"
    message.set_content("Relay probe from the core worker.")
    transport.send(message)
    print(f"mail-proof: core worker sent through {settings.safe_summary()['mode']}")


def twenty_reset(email: str) -> None:
    body = json.dumps(
        {
            "query": "mutation Reset($email: String!) { "
            "emailPasswordResetLink(email: $email) { success } }",
            "variables": {"email": email},
        }
    ).encode()
    # Twenty serves its auth mutations on /metadata and resolves the
    # workspace from the browser origin, like its own sign-in page.
    request = urllib.request.Request(
        os.environ["TWENTY_BASE_URL"] + "/metadata",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Origin": os.environ["TWENTY_ORIGIN"],
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read())
    result = (payload.get("data") or {}).get("emailPasswordResetLink") or {}
    if result.get("success") is not True:
        # Twenty's auth errors carry no secrets; show code and message.
        problems = [
            (
                (error.get("extensions") or {}).get("code"),
                (error.get("extensions") or {}).get("subCode"),
                str(error.get("message", ""))[:200],
            )
            for error in payload.get("errors") or []
        ]
        raise SystemExit(f"mail-proof: Twenty refused the reset request: {problems}")
    print("mail-proof: Twenty accepted the password reset request")


def assert_delivered(api: str, recipient: str, sender: str, word: str) -> None:
    query = urllib.parse.urlencode({"query": f"to:{recipient}"})
    deadline = time.monotonic() + 90
    while True:
        with urllib.request.urlopen(
            f"{api}/api/v1/search?{query}", timeout=10
        ) as response:
            messages = json.loads(response.read()).get("messages") or []
        for message in messages:
            if (message.get("From") or {}).get("Address") == sender and word in (
                message.get("Subject") or ""
            ):
                print(
                    f"mail-proof: relay accepted '{message['Subject']}' "
                    f"from {sender} for {recipient}"
                )
                return
        if time.monotonic() > deadline:
            raise SystemExit(
                f"mail-proof: no message from {sender} for {recipient} with "
                f"'{word}' in the subject; {len(messages)} other message(s)"
            )
        time.sleep(2)


def main() -> None:
    command, *arguments = sys.argv[1:]
    if command == "certificates":
        certificates(Path(arguments[0]), arguments[1])
    elif command == "core-send":
        core_send(arguments[0])
    elif command == "twenty-reset":
        twenty_reset(arguments[0])
    elif command == "assert-delivered":
        assert_delivered(*arguments)
    else:
        raise SystemExit(f"mail-proof: unknown command {command}")


if __name__ == "__main__":
    main()
