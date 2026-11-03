import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from leonaid.entrypoints.fastapi.platform import BODY_LIMITS
from leonaid.platform.http_body import RequestBodyLimitMiddleware

SURVEY_REQUEST_BYTES = 1_048_576
Message = dict[str, Any]


def run_middleware(
    path: str,
    chunks: list[bytes],
    app: Callable[..., Awaitable[None]],
    *,
    declared: int | None = None,
) -> tuple[list[Message], dict[str, Any]]:
    async def run() -> tuple[list[Message], dict[str, Any]]:
        messages = iter(
            [
                {
                    "type": "http.request",
                    "body": chunk,
                    "more_body": index < len(chunks) - 1,
                }
                for index, chunk in enumerate(chunks)
            ]
        )
        output: list[Message] = []

        async def receive() -> Message:
            return next(messages)

        async def send(message: Message) -> None:
            output.append(message)

        headers = (
            [(b"content-length", str(declared).encode())]
            if declared is not None
            else []
        )
        scope: dict[str, Any] = {"type": "http", "path": path, "headers": headers}
        await RequestBodyLimitMiddleware(app, BODY_LIMITS)(scope, receive, send)
        return output, scope

    return asyncio.run(run())


async def read_whole_body(scope: Any, receive: Any, send: Any) -> None:
    """Like FastAPI: the endpoint runs only after the full body was read."""
    while True:
        message = await receive()
        if not message.get("more_body", False):
            break
    raise AssertionError("An over-limit request reached the endpoint")


def test_body_limit_counts_streamed_bytes_instead_of_trusting_content_length() -> None:
    output, scope = run_middleware(
        "/api/v1/public/surveys/compact-id/participations",
        [b"x" * SURVEY_REQUEST_BYTES, b"x"],
        read_whole_body,
        declared=1,
    )
    assert output[0]["status"] == 413
    assert scope["state"]["error_code"] == "limit_exceeded"
    assert b"limit_exceeded" in output[1]["body"]


def test_declared_oversized_body_is_rejected_before_the_app_runs() -> None:
    async def forbidden(*_args: Any) -> None:
        raise AssertionError("An over-limit request reached the application")

    output, _ = run_middleware(
        "/api/v1/survey-settings", [b""], forbidden, declared=SURVEY_REQUEST_BYTES + 1
    )
    assert output[0]["status"] == 413


def test_body_at_the_limit_reaches_the_app() -> None:
    reached: list[int] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        total = 0
        while True:
            message = await receive()
            total += len(message["body"])
            if not message["more_body"]:
                break
        reached.append(total)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    output, _ = run_middleware(
        "/api/v1/surveys", [b"x" * (SURVEY_REQUEST_BYTES - 1), b"x"], app
    )
    assert reached == [SURVEY_REQUEST_BYTES]
    assert output[0]["status"] == 204


def test_paths_without_a_limit_are_not_counted() -> None:
    reached: list[int] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        reached.append(len((await receive())["body"]))

    run_middleware("/api/v1/identity/me", [b"x" * (SURVEY_REQUEST_BYTES * 2)], app)
    assert reached == [SURVEY_REQUEST_BYTES * 2]


def test_parser_error_after_the_limit_still_answers_413() -> None:
    """FastAPI turns a failed form read into its own 400; the limit wins."""

    async def app(scope: Any, receive: Any, send: Any) -> None:
        try:
            while (await receive())["more_body"]:
                pass
        except Exception:
            await send({"type": "http.response.start", "status": 400, "headers": []})
            await send({"type": "http.response.body", "body": b"parse error"})

    output, _ = run_middleware(
        "/api/v1/materials", [b"x" * (26 * 1024 * 1024), b"x"], app
    )
    assert output[0]["status"] == 413
    assert all(b"parse error" not in message.get("body", b"") for message in output)
