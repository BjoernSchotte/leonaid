import asyncio

from leonaid.platform.http_body import RequestBodyLimitMiddleware

SURVEY_REQUEST_BYTES = 1_048_576
LIMITS = (
    ("/api/v1/public/surveys", SURVEY_REQUEST_BYTES),
    ("/api/v1/survey-settings", SURVEY_REQUEST_BYTES),
)


def test_body_limit_counts_streamed_bytes_instead_of_trusting_content_length():
    async def run():
        messages = iter(
            [
                {
                    "type": "http.request",
                    "body": b"x" * SURVEY_REQUEST_BYTES,
                    "more_body": True,
                },
                {"type": "http.request", "body": b"x", "more_body": True},
            ]
        )
        output = []

        async def receive():
            return next(messages)

        async def send(message):
            output.append(message)

        async def forbidden_app(scope, receive, send):
            raise AssertionError("An over-limit request reached the application")

        scope = {
            "type": "http",
            "path": "/api/v1/public/surveys/compact-id/participations",
            "headers": [(b"content-length", b"1")],
        }
        await RequestBodyLimitMiddleware(forbidden_app, LIMITS)(scope, receive, send)
        assert output[0]["status"] == 413
        assert scope["state"]["error_code"] == "limit_exceeded"
        assert b"limit_exceeded" in output[1]["body"]

    asyncio.run(run())


def test_disconnect_during_body_never_dispatches_a_partial_request():
    async def run():
        async def receive():
            return {"type": "http.disconnect"}

        async def forbidden(*args):
            raise AssertionError("Disconnected request was dispatched or answered")

        await RequestBodyLimitMiddleware(forbidden, LIMITS)(
            {"type": "http", "path": "/api/v1/survey-settings"}, receive, forbidden
        )

    asyncio.run(run())
