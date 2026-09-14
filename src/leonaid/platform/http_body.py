"""Bound configured request bytes before parsing, including chunked bodies."""

from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, limits: tuple[tuple[str, int], ...]) -> None:
        self.app = app
        self.limits = limits

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        limit = next(
            (
                maximum
                for prefix, maximum in self.limits
                if path == prefix or path.startswith(prefix + "/")
            ),
            None,
        )
        if scope["type"] != "http" or limit is None:
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
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
