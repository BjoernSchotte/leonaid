"""Bound request bodies per path prefix without buffering them.

The declared ``Content-Length`` is checked before the app runs. Chunked or
under-declared bodies are counted while the app reads them; once the limit
is crossed the read fails and the client gets 413, provided no response has
started. Nothing is held in memory beyond what the app itself reads, so a
25 MiB upload limit does not cost an extra 25 MiB per request.
"""

from __future__ import annotations

from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyLimitExceeded(Exception):
    """The request body crossed the limit of its path."""


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, limits: tuple[tuple[str, int], ...]) -> None:
        if any(maximum <= 0 for _, maximum in limits):
            raise ValueError("Body limits must be positive.")
        self.app = app
        # Longest prefix first, so a specific path can override a general one.
        self.limits = tuple(sorted(limits, key=lambda item: -len(item[0])))

    def limit_for(self, path: str) -> int | None:
        return next(
            (
                maximum
                for prefix, maximum in self.limits
                if path == prefix or path.startswith(prefix + "/")
            ),
            None,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = (
            self.limit_for(scope.get("path", "")) if scope["type"] == "http" else None
        )
        if limit is None:
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers", ())).get(b"content-length")
        if declared is not None:
            try:
                too_large = int(declared) > limit
            except ValueError:
                too_large = False  # The server rejects malformed lengths itself.
            if too_large:
                await self.reject(scope, receive, send)
                return

        received = 0
        started = False

        async def counted_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyLimitExceeded
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted_receive, tracked_send)
        except BodyLimitExceeded:
            if started:
                raise
            await self.reject(scope, receive, send)

    @staticmethod
    async def reject(scope: Scope, receive: Receive, send: Send) -> None:
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
            headers={"Cache-Control": "no-store", "Connection": "close"},
        )
        await response(scope, receive, send)
