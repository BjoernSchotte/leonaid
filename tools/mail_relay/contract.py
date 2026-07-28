"""Real provider-neutral SMTP transport contract against pinned services."""

from __future__ import annotations

import json
import os
from email.message import EmailMessage
from urllib.request import urlopen

from leonaid.adapters.mail.transport import MailTransportError, SmtpTransport

MESSAGE_ID = "<pilot-mail-relay-contract@outbox.leonaid.invalid>"


def message(subject: str) -> EmailMessage:
    value = EmailMessage()
    value["From"] = "LeonAid <noreply@leonaid.invalid>"
    value["To"] = "controlled-recipient@leonaid.invalid"
    value["Subject"] = subject
    value["Message-ID"] = MESSAGE_ID
    value.set_content("Synthetischer Pilot-Mailvertrag ohne reale Personendaten.")
    return value


def transport(
    host: str,
    *,
    mode: str = "plain",
    username: str | None = None,
    password: str | None = None,
    timeout: float = 2,
    verify: bool = True,
) -> SmtpTransport:
    if mode not in {"plain", "starttls", "tls"}:
        raise RuntimeError("Ungültiger Test-Transportmodus.")
    return SmtpTransport(
        host=host,
        port=1025,
        sender="LeonAid <noreply@leonaid.invalid>",
        mode=mode,  # type: ignore[arg-type]
        username=username,
        password=password,
        timeout_seconds=timeout,
        verify_certificates=verify,
    )


def expect_failure(
    expected_code: str,
    expected_retryable: bool,
    send: SmtpTransport,
    subject: str,
) -> None:
    try:
        send.send(message(subject))
    except MailTransportError as error:
        if error.code != expected_code or error.retryable != expected_retryable:
            raise RuntimeError(
                "Unsichere oder falsche SMTP-Fehlerklassifikation."
            ) from error
        if str(error) != expected_code:
            raise RuntimeError("SMTP-Fehler enthält Providerdetails.")
        return
    raise RuntimeError(f"Erwarteter SMTP-Fehler blieb aus: {expected_code}")


def message_count(api_url: str) -> int:
    with urlopen(f"{api_url.rstrip('/')}/api/v1/messages", timeout=5) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or not isinstance(payload.get("total"), int):
        raise RuntimeError("Mailpit-Vertrag lieferte keinen Zähler.")
    return int(payload["total"])


def main() -> None:
    plain_host = os.environ["MAIL_CONTRACT_PLAIN_HOST"]
    starttls_host = os.environ["MAIL_CONTRACT_STARTTLS_HOST"]
    tls_host = os.environ["MAIL_CONTRACT_TLS_HOST"]
    chaos_host = os.environ["MAIL_CONTRACT_CHAOS_HOST"]
    blackhole_host = os.environ["MAIL_CONTRACT_BLACKHOLE_HOST"]
    plain_api = os.environ["MAIL_CONTRACT_PLAIN_API"]
    starttls_api = os.environ["MAIL_CONTRACT_STARTTLS_API"]
    tls_api = os.environ["MAIL_CONTRACT_TLS_API"]

    before_plain = message_count(plain_api)
    before_starttls = message_count(starttls_api)
    before_tls = message_count(tls_api)

    # Der erste Versuch wird vom echten SMTP-Server vor der Annahme mit einem
    # Provider-Limit abgewiesen; der Retry wird genau einmal angenommen.
    expect_failure(
        "mail_provider_limited",
        True,
        transport(chaos_host),
        "Limitierter Erstversuch",
    )
    transport(plain_host).send(message("Erfolgreicher Retry"))
    if message_count(plain_api) != before_plain + 1:
        raise RuntimeError(
            "Der erfolgreiche Retry wurde nicht exakt einmal angenommen."
        )

    # STARTTLS plus Authentifizierung läuft real gegen Mailpit. Für diesen
    # isolierten Positivtest ist dessen kurzlebiges Self-signed-Zertifikat
    # bewusst erlaubt; Produktion erzwingt Verifikation.
    transport(
        starttls_host,
        mode="starttls",
        username="pilot-user",
        password="pilot-password",
        verify=False,
    ).send(message("STARTTLS und Authentifizierung"))
    if message_count(starttls_api) != before_starttls + 1:
        raise RuntimeError("STARTTLS-Mail wurde nicht genau einmal angenommen.")

    transport(
        tls_host,
        mode="tls",
        username="pilot-user",
        password="pilot-password",
        verify=False,
    ).send(message("Implizites TLS und Authentifizierung"))
    if message_count(tls_api) != before_tls + 1:
        raise RuntimeError("TLS-Mail wurde nicht genau einmal angenommen.")

    expect_failure(
        "mail_certificate_invalid",
        False,
        transport(
            starttls_host,
            mode="starttls",
            username="pilot-user",
            password="pilot-password",
            verify=True,
        ),
        "Ungültiges Zertifikat",
    )
    expect_failure(
        "mail_authentication_failed",
        False,
        transport(
            starttls_host,
            mode="starttls",
            username="pilot-user",
            password="wrong-password",
            verify=False,
        ),
        "Ungültige Authentifizierung",
    )
    expect_failure(
        "mail_timeout",
        True,
        transport(blackhole_host, timeout=0.5),
        "SMTP-Timeout",
    )

    print(
        json.dumps(
            {
                "authentication": "proven",
                "certificateFailure": "proven",
                "implicitTls": "proven",
                "providerLimit": "proven",
                "retryAcceptedCount": 1,
                "starttls": "proven",
                "timeout": "proven",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
