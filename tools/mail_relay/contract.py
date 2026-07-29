"""Real provider-neutral SMTP transport contract against pinned services."""

from __future__ import annotations

import json
import os
from email.message import EmailMessage
from urllib.request import urlopen

from leonaid.adapters.mail.transport import MailTransportError, SmtpTransport

MESSAGE_ID = "<pilot-mail-relay-contract@outbox.leonaid.invalid>"
ENVELOPE_FROM = "bounces@leonaid.invalid"
REPLY_TO = "LeonAid Support <support@leonaid.invalid>"


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
        envelope_from=ENVELOPE_FROM,
        reply_to=REPLY_TO,
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


def latest_message(api_url: str) -> dict[str, object]:
    with urlopen(
        f"{api_url.rstrip('/')}/api/v1/message/latest",
        timeout=5,
    ) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("Mailpit-Vertrag lieferte keine Nachricht.")
    return payload


def address(payload: object) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get("Address"), str):
        raise RuntimeError("Mailpit-Vertrag lieferte keine Mailadresse.")
    return str(payload["Address"])


def assert_delivery_identity(api_url: str) -> None:
    payload = latest_message(api_url)
    reply_to = payload.get("ReplyTo")
    if (
        address(payload.get("From")) != "noreply@leonaid.invalid"
        or not isinstance(reply_to, list)
        or len(reply_to) != 1
        or address(reply_to[0]) != "support@leonaid.invalid"
        or str(payload.get("ReturnPath", "")).strip("<>") != ENVELOPE_FROM
        or str(payload.get("MessageID", "")).strip("<>") != MESSAGE_ID.strip("<>")
    ):
        raise RuntimeError(
            "SMTP-Server empfing falsches From, Reply-To, "
            "Envelope-From oder Message-ID."
        )


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
    assert_delivery_identity(plain_api)

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
    assert_delivery_identity(starttls_api)

    transport(
        tls_host,
        mode="tls",
        username="pilot-user",
        password="pilot-password",
        verify=False,
    ).send(message("Implizites TLS und Authentifizierung"))
    if message_count(tls_api) != before_tls + 1:
        raise RuntimeError("TLS-Mail wurde nicht genau einmal angenommen.")
    assert_delivery_identity(tls_api)

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
                "deliveryIdentities": "proven",
                "envelopeFrom": "proven",
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
