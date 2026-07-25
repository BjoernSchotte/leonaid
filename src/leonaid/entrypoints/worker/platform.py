"""Durable-worker process shell with dependency-aware health endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import asyncpg

last_database_success = 0.0


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        if self.path == "/health/live":
            self.respond(200, {"service": "leonaid-worker", "status": "live"})
            return
        if self.path == "/health/ready":
            ready = time.monotonic() - last_database_success < 10
            self.respond(
                200 if ready else 503,
                {
                    "service": "leonaid-worker",
                    "status": "ready" if ready else "not-ready",
                    "checks": {"postgres": "ready" if ready else "not-ready"},
                },
            )
            return
        self.respond(404, {"status": "not-found"})

    def respond(self, code: int, document: dict[str, object]) -> None:
        body = json.dumps(document, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


async def dependency_loop() -> None:
    global last_database_success
    while True:
        try:
            connection = await asyncpg.connect(
                os.environ["CORE_DATABASE_URL"], timeout=3
            )
            try:
                await connection.fetchval("SELECT 1")
                last_database_success = time.monotonic()
            finally:
                await connection.close()
        except Exception:
            pass
        await asyncio.sleep(2)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8010), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    asyncio.run(dependency_loop())


if __name__ == "__main__":
    main()
