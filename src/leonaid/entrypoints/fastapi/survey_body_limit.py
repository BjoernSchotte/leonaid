"""Bound survey request bytes before JSON parsing, including chunked bodies."""

from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SURVEY_REQUEST_BYTES = 1_048_576


class SurveyBodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        is_survey = any(
            path == prefix or path.startswith(prefix + "/")
            for prefix in (
                "/api/v1/surveys",
                "/api/v1/public/surveys",
                "/api/v1/survey-settings",
            )
        )
        if scope["type"] != "http" or not is_survey:
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > SURVEY_REQUEST_BYTES:
                state = scope.setdefault("state", {})
                state["error_code"] = "limit_exceeded"
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "limit_exceeded",
                            "message": "Die Anfrage überschreitet die zulässige Größe.",
                            "requestId": state.get("request_id", str(uuid4())),
                        }
                    },
                    headers={"Cache-Control": "no-store"},
                )
                await response(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
