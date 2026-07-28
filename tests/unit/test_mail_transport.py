from __future__ import annotations

from email.message import EmailMessage

from pytest import raises

from leonaid.adapters.mail.transport import MailTransportError, SmtpTransport
from leonaid.application.outbox import OutboxWorker


def transport() -> SmtpTransport:
    return SmtpTransport(
        host="mailpit",
        port=1025,
        sender="LeonAid <noreply@leonaid.invalid>",
        mode="plain",
        username=None,
        password=None,
        timeout_seconds=5,
        verify_certificates=True,
    )


def test_transport_requires_complete_credentials() -> None:
    with raises(ValueError, match="unvollständig"):
        SmtpTransport(
            host="mailpit",
            port=1025,
            sender="LeonAid <noreply@leonaid.invalid>",
            mode="plain",
            username="smtp-user",
            password=None,
            timeout_seconds=5,
            verify_certificates=True,
        )


def test_provider_limit_is_safe_and_retryable() -> None:
    error = transport()._response_error(452)

    assert isinstance(error, MailTransportError)
    assert str(error) == "mail_provider_limited"
    assert error.retryable is True


def test_permanent_rejection_is_safe_and_terminal() -> None:
    error = transport()._response_error(550)

    assert str(error) == "mail_permanent_rejection"
    assert error.retryable is False


def test_outbox_preserves_only_valid_safe_transport_code() -> None:
    error = MailTransportError("mail_certificate_invalid", retryable=False)

    assert OutboxWorker.error_code(error) == "mail_certificate_invalid"
    assert OutboxWorker.error_code(RuntimeError("private provider text")) == (
        "runtimeerror"
    )


def test_transport_holds_no_message_data_in_its_representation() -> None:
    message = EmailMessage()
    message["From"] = transport().sender
    message["To"] = "person@example.invalid"
    message["Subject"] = "Ein vertraulicher Betreff"
    message.set_content("Ein vertraulicher Inhalt")

    assert "person@example.invalid" not in repr(transport())
    assert "vertraulich" not in repr(transport()).casefold()
