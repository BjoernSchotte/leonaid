"""Provider-neutral SMTP transport with secret-safe failure classification."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Literal

SmtpMode = Literal["plain", "starttls", "tls"]


class MailTransportError(RuntimeError):
    """A safe operational failure that never includes provider responses."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class SmtpTransport:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        mode: SmtpMode,
        username: str | None,
        password: str | None,
        timeout_seconds: float,
        verify_certificates: bool,
        ca_file: Path | None = None,
    ) -> None:
        if not host.strip() or port < 1 or not sender.strip():
            raise ValueError("SMTP-Konfiguration ist unvollständig.")
        if (username is None) != (password is None):
            raise ValueError("SMTP-Zugangsdaten sind unvollständig.")
        self.host = host
        self.port = port
        self.sender = sender
        self.mode = mode
        self.username = username
        self._password = password
        self.timeout_seconds = timeout_seconds
        self.verify_certificates = verify_certificates
        self.ca_file = ca_file

    def send(self, message: EmailMessage) -> None:
        try:
            self._send(message)
        except MailTransportError:
            raise
        except smtplib.SMTPAuthenticationError:
            raise MailTransportError(
                "mail_authentication_failed",
                retryable=False,
            ) from None
        except ssl.SSLCertVerificationError:
            raise MailTransportError(
                "mail_certificate_invalid",
                retryable=False,
            ) from None
        except TimeoutError:
            raise MailTransportError("mail_timeout", retryable=True) from None
        except smtplib.SMTPRecipientsRefused as error:
            codes = {
                int(response[0])
                for response in error.recipients.values()
                if isinstance(response, tuple) and response
            }
            if 452 in codes:
                raise MailTransportError(
                    "mail_provider_limited",
                    retryable=True,
                ) from None
            if codes and all(400 <= code <= 499 for code in codes):
                raise MailTransportError(
                    "mail_temporary_rejection",
                    retryable=True,
                ) from None
            raise MailTransportError(
                "mail_recipient_rejected",
                retryable=False,
            ) from None
        except smtplib.SMTPResponseException as error:
            raise self._response_error(error.smtp_code) from None
        except smtplib.SMTPNotSupportedError:
            raise MailTransportError(
                "mail_transport_unsupported",
                retryable=False,
            ) from None
        except smtplib.SMTPServerDisconnected as error:
            code = (
                "mail_timeout"
                if "timed out" in str(error).casefold()
                else "mail_unavailable"
            )
            raise MailTransportError(code, retryable=True) from None
        except ssl.SSLError:
            raise MailTransportError(
                "mail_tls_failed",
                retryable=False,
            ) from None
        except smtplib.SMTPException:
            raise MailTransportError(
                "mail_protocol_failed",
                retryable=True,
            ) from None
        except OSError:
            raise MailTransportError(
                "mail_unavailable",
                retryable=True,
            ) from None

    def _send(self, message: EmailMessage) -> None:
        context = self._tls_context()
        if self.mode == "tls":
            with smtplib.SMTP_SSL(
                self.host,
                self.port,
                timeout=self.timeout_seconds,
                context=context,
            ) as smtp:
                self._authenticate_and_send(smtp, message)
            return

        with smtplib.SMTP(
            self.host,
            self.port,
            timeout=self.timeout_seconds,
        ) as smtp:
            if self.mode == "starttls":
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            self._authenticate_and_send(smtp, message)

    def _authenticate_and_send(
        self,
        smtp: smtplib.SMTP,
        message: EmailMessage,
    ) -> None:
        if self.username is not None and self._password is not None:
            smtp.login(self.username, self._password)
        smtp.send_message(message)

    def _tls_context(self) -> ssl.SSLContext:
        if not self.verify_certificates:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            return context
        return ssl.create_default_context(
            cafile=str(self.ca_file) if self.ca_file is not None else None
        )

    @staticmethod
    def _response_error(code: int) -> MailTransportError:
        if code == 452:
            return MailTransportError("mail_provider_limited", retryable=True)
        if 400 <= code <= 499:
            return MailTransportError(
                "mail_temporary_rejection",
                retryable=True,
            )
        return MailTransportError("mail_permanent_rejection", retryable=False)
