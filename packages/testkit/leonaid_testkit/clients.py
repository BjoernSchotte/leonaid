"""Narrow clients for the real systems used by LeonAid acceptance tests."""

from __future__ import annotations

import asyncio
import hashlib
import re
import smtplib
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from http.cookies import SimpleCookie
from typing import Any, Self

import asyncpg
import boto3
import httpx

from leonaid_testkit.context import TestContext, poll_until

JsonObject = dict[str, Any]
LOGIN_TOKEN_PATTERN = re.compile(
    r"/(?:login|fresh-login)\?token=([A-Za-z0-9_-]{32,256})"
)
SESSION_COOKIE_NAME = "__Host-leonaid_session"


def _json_object(
    response: httpx.Response,
    *,
    context: TestContext,
    step: str,
) -> JsonObject:
    try:
        value = response.json()
    except ValueError as error:
        raise context.failure(
            step,
            f"HTTP {response.status_code} lieferte kein JSON-Objekt.",
        ) from error
    if not isinstance(value, dict):
        raise context.failure(step, "HTTP-Antwort ist kein JSON-Objekt.")
    return value


def _recipient_addresses(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, str):
        if "@" in value:
            result.add(value.casefold())
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in {"address", "email"} and isinstance(item, str):
                result.add(item.casefold())
            else:
                result.update(_recipient_addresses(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_recipient_addresses(item))
    return result


@dataclass(frozen=True, slots=True)
class PersonaSession:
    persona: str
    email: str
    token: str

    @property
    def cookie_header(self) -> str:
        return f"{SESSION_COOKIE_NAME}={self.token}"


@dataclass(frozen=True, slots=True)
class MailpitMessage:
    message_id: str
    subject: str
    text: str
    recipients: frozenset[str]


class MailpitClient:
    """Send real SMTP messages and observe delivery through Mailpit's API."""

    def __init__(
        self,
        *,
        api_url: str,
        smtp_host: str,
        smtp_port: int,
        context: TestContext,
    ) -> None:
        self._context = context
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._client = httpx.AsyncClient(base_url=api_url.rstrip("/"), timeout=10)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def message_ids(self) -> set[str]:
        step = "mailpit-list"
        response = await self._client.get(
            "/api/v1/messages",
            headers={"X-Request-ID": self._context.request_id},
        )
        if response.status_code != 200:
            raise self._context.failure(
                step,
                f"Mailpit-Nachrichtenliste lieferte HTTP {response.status_code}.",
            )
        payload = _json_object(response, context=self._context, step=step)
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise self._context.failure(step, "Mailpit liefert keine messages-Liste.")
        return {
            str(item["ID"])
            for item in messages
            if isinstance(item, dict) and isinstance(item.get("ID"), str)
        }

    async def _find_message(
        self,
        *,
        recipient: str,
        previous_ids: set[str],
        subject: str | None,
    ) -> MailpitMessage | None:
        response = await self._client.get(
            "/api/v1/messages",
            headers={"X-Request-ID": self._context.request_id},
        )
        if response.status_code != 200:
            return None
        payload = _json_object(
            response,
            context=self._context,
            step="mailpit-poll",
        )
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise self._context.failure(
                "mailpit-poll",
                "Mailpit liefert beim Polling keine messages-Liste.",
            )
        for summary in messages:
            if not isinstance(summary, dict):
                continue
            message_id = summary.get("ID")
            if (
                not isinstance(message_id, str)
                or message_id in previous_ids
                or recipient.casefold() not in _recipient_addresses(summary.get("To"))
            ):
                continue
            detail_response = await self._client.get(
                f"/api/v1/message/{message_id}",
                headers={"X-Request-ID": self._context.request_id},
            )
            if detail_response.status_code != 200:
                continue
            detail = _json_object(
                detail_response,
                context=self._context,
                step="mailpit-detail",
            )
            message_subject = detail.get("Subject")
            text = detail.get("Text")
            if not isinstance(message_subject, str) or not isinstance(text, str):
                raise self._context.failure(
                    "mailpit-detail",
                    "Mailpit-Nachricht enthält Betreff oder Text nicht.",
                )
            if subject is not None and message_subject != subject:
                continue
            return MailpitMessage(
                message_id=message_id,
                subject=message_subject,
                text=text,
                recipients=frozenset(_recipient_addresses(detail.get("To"))),
            )
        return None

    async def wait_for_message(
        self,
        *,
        recipient: str,
        previous_ids: set[str],
        subject: str | None = None,
        timeout_seconds: float = 30,
    ) -> MailpitMessage:
        message = await poll_until(
            context=self._context,
            step="mailpit-delivery",
            probe=lambda: self._find_message(
                recipient=recipient,
                previous_ids=previous_ids,
                subject=subject,
            ),
            ready=lambda item: item is not None,
            timeout_seconds=timeout_seconds,
        )
        if message is None:
            raise self._context.failure(
                "mailpit-delivery",
                "Mailpit-Polling endete ohne Nachricht.",
            )
        return message

    async def send_and_wait(
        self,
        *,
        sender: str,
        recipient: str,
        subject: str,
        text: str,
    ) -> MailpitMessage:
        previous_ids = await self.message_ids()
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(text)

        def send() -> None:
            with smtplib.SMTP(
                self._smtp_host,
                self._smtp_port,
                timeout=10,
            ) as smtp:
                smtp.send_message(message)

        try:
            await asyncio.to_thread(send)
        except (OSError, smtplib.SMTPException) as error:
            raise self._context.failure(
                "mailpit-smtp-send",
                f"Realer SMTP-Versand an Mailpit schlug fehl: {error}.",
            ) from error
        return await self.wait_for_message(
            recipient=recipient,
            previous_ids=previous_ids,
            subject=subject,
        )


class LeonAidApiClient:
    """HTTP client including real passwordless persona login."""

    def __init__(self, *, base_url: str, context: TestContext) -> None:
        self._context = context
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=10)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def wait_ready(self) -> None:
        async def probe() -> int:
            response = await self._client.get(
                "/health/ready",
                headers={"X-Request-ID": self._context.request_id},
            )
            return response.status_code

        await poll_until(
            context=self._context,
            step="leonaid-readiness",
            probe=probe,
            ready=lambda status: status == 200,
            timeout_seconds=45,
        )

    async def login(
        self,
        *,
        email: str,
        persona: str,
        expected_user_id: str,
        expected_display_name: str,
        mailpit: MailpitClient,
    ) -> PersonaSession:
        previous_ids = await mailpit.message_ids()
        request = await self._client.post(
            "/api/v1/auth/login",
            headers={"X-Request-ID": self._context.request_id},
            json={"email": email},
        )
        if request.status_code != 202 or _json_object(
            request,
            context=self._context,
            step="persona-login-request",
        ) != {"status": "queued"}:
            raise self._context.failure(
                "persona-login-request",
                f"Login-Anfrage lieferte HTTP {request.status_code} ohne queued.",
            )
        login_mail = await mailpit.wait_for_message(
            recipient=email,
            previous_ids=previous_ids,
        )
        token_match = LOGIN_TOKEN_PATTERN.search(login_mail.text)
        if token_match is None:
            raise self._context.failure(
                "persona-login-mail",
                "Login-Mail enthält keinen Magic-Link.",
            )
        complete = await self._client.post(
            "/api/v1/auth/login/complete",
            headers={
                "X-Request-ID": self._context.request_id,
                "User-Agent": "LeonAid real-system testkit",
            },
            json={"magicToken": token_match.group(1)},
        )
        if complete.status_code != 200:
            raise self._context.failure(
                "persona-login-complete",
                f"Magic-Link-Abschluss lieferte HTTP {complete.status_code}.",
            )
        session_token = self._session_from_response(complete)
        session = PersonaSession(
            persona=persona,
            email=email,
            token=session_token,
        )
        identity = await self.get_json(
            "/api/v1/identity/me",
            session=session,
            step="persona-login-identity",
        )
        if (
            identity.get("userId") != expected_user_id
            or identity.get("displayName") != expected_display_name
        ):
            raise self._context.failure(
                "persona-login-identity",
                "Echte Sitzung gehört nicht zur angeforderten Persona.",
            )
        return session

    def _session_from_response(self, response: httpx.Response) -> str:
        values = [
            value
            for value in response.headers.get_list("set-cookie")
            if value.startswith(f"{SESSION_COOKIE_NAME}=")
        ]
        if len(values) != 1:
            raise self._context.failure(
                "persona-login-cookie",
                "Login setzt nicht genau ein Sitzungscookie.",
            )
        parsed = SimpleCookie()
        parsed.load(values[0])
        cookie = parsed.get(SESSION_COOKIE_NAME)
        if (
            cookie is None
            or not cookie["secure"]
            or not cookie["httponly"]
            or cookie["samesite"].casefold() != "lax"
            or cookie["domain"]
            or cookie["path"] != "/"
        ):
            raise self._context.failure(
                "persona-login-cookie",
                "Sitzungscookie verletzt den Secure/HttpOnly/Host-only-Vertrag.",
            )
        return cookie.value

    async def get_json(
        self,
        path: str,
        *,
        session: PersonaSession,
        step: str,
        params: Mapping[str, str | int] | None = None,
    ) -> JsonObject:
        response = await self._client.get(
            path,
            headers={
                "Cookie": session.cookie_header,
                "X-Request-ID": self._context.request_id,
            },
            params=params,
        )
        if response.status_code != 200:
            raise self._context.failure(
                step,
                f"LeonAid API lieferte HTTP {response.status_code}.",
            )
        return _json_object(response, context=self._context, step=step)


class TwentyClient:
    """Read Golden CRM records through Twenty's supported REST Data API."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        context: TestContext,
    ) -> None:
        self._context = context
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
            timeout=10,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def get_company(self, twenty_id: str) -> JsonObject:
        response = await self._client.get(
            f"/rest/companies/{twenty_id}",
            headers={"X-Request-ID": self._context.request_id},
        )
        if response.status_code != 200:
            raise self._context.failure(
                "twenty-company-read",
                f"Twenty lieferte für {twenty_id} HTTP {response.status_code}.",
            )
        payload = _json_object(
            response,
            context=self._context,
            step="twenty-company-read",
        )
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise self._context.failure(
                "twenty-company-read",
                "Twenty liefert kein Firmenobjekt.",
            )
        nested = data.get("company")
        return dict(nested) if isinstance(nested, dict) else dict(data)


class RustFsClient:
    """Round-trip objects through the real S3-compatible RustFS endpoint."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        context: TestContext,
    ) -> None:
        self._bucket = bucket
        self._context = context
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
        )

    async def round_trip(self, *, key: str, content: bytes) -> str:
        expected_hash = hashlib.sha256(content).hexdigest()

        def execute() -> str:
            try:
                self._client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=content,
                    ContentType="text/plain; charset=utf-8",
                    Metadata={"sha256": expected_hash},
                )
                response = self._client.get_object(Bucket=self._bucket, Key=key)
                body = response["Body"].read()
                metadata = response.get("Metadata", {})
                actual_hash = hashlib.sha256(body).hexdigest()
                if body != content or actual_hash != expected_hash:
                    raise self._context.failure(
                        "rustfs-hash",
                        "RustFS-Leseinhalt besitzt nicht den geschriebenen SHA-256.",
                    )
                if metadata.get("sha256") != expected_hash:
                    raise self._context.failure(
                        "rustfs-metadata",
                        "RustFS hat die SHA-256-Metadaten nicht erhalten.",
                    )
                return actual_hash
            finally:
                self._client.delete_object(Bucket=self._bucket, Key=key)

        try:
            return await asyncio.to_thread(execute)
        except Exception as error:
            if isinstance(error, AssertionError):
                raise
            raise self._context.failure(
                "rustfs-roundtrip",
                f"Realer RustFS-Schreib-/Lesezyklus schlug fehl: {error}.",
            ) from error


class ReadOnlySqlClient:
    """Execute diagnostic reads in explicit PostgreSQL read-only transactions."""

    def __init__(self, *, database_url: str, context: TestContext) -> None:
        self._database_url = database_url
        self._context = context
        self._connection: asyncpg.Connection | None = None

    async def __aenter__(self) -> Self:
        try:
            self._connection = await asyncpg.connect(self._database_url, timeout=10)
        except (OSError, asyncpg.PostgresError) as error:
            raise self._context.failure(
                "sql-connect",
                f"Read-only SQL-Verbindung schlug fehl: {error}.",
            ) from error
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def fetchrow(self, query: str, *args: object) -> JsonObject:
        normalized = query.lstrip().casefold()
        if not normalized.startswith(("select", "with", "show")):
            raise self._context.failure(
                "sql-readonly-guard",
                "Testkit-SQL erlaubt ausschließlich lesende Statements.",
            )
        connection = self._connection
        if connection is None:
            raise self._context.failure(
                "sql-read",
                "Read-only SQL-Client wurde nicht geöffnet.",
            )
        try:
            async with connection.transaction(readonly=True):
                row = await connection.fetchrow(query, *args)
        except asyncpg.PostgresError as error:
            raise self._context.failure(
                "sql-read",
                f"Read-only SQL-Prüfung schlug fehl: {error}.",
            ) from error
        if row is None:
            raise self._context.failure(
                "sql-read",
                "Read-only SQL-Prüfung fand keinen Datensatz.",
            )
        return dict(row)
