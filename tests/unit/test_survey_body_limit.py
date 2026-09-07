import asyncio

from leonaid.entrypoints.fastapi.survey_body_limit import (
    SURVEY_REQUEST_BYTES,
    SurveyBodyLimitMiddleware,
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
        await SurveyBodyLimitMiddleware(forbidden_app)(scope, receive, send)
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

        await SurveyBodyLimitMiddleware(forbidden)(
            {"type": "http", "path": "/api/v1/survey-settings"}, receive, forbidden
        )

    asyncio.run(run())
