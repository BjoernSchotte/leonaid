"""Durable-worker process shell with dependency-aware health endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import asyncpg

from leonaid.entrypoints.worker.outbox import build_worker

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
        if self.path == "/metrics":
            ready = time.monotonic() - last_database_success < 10
            body = (
                "# HELP leonaid_worker_ready Whether the durable worker can reach PostgreSQL.\n"
                "# TYPE leonaid_worker_ready gauge\n"
                f"leonaid_worker_ready {1 if ready else 0}\n"
            ).encode()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/plain; version=0.0.4; charset=utf-8",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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


async def durable_worker_loop() -> None:
    while True:
        pool = None
        try:
            pool, _, worker = await build_worker(
                database_url=os.environ["CORE_DATABASE_URL"],
                worker_id=f"compose-worker-{os.getpid()}",
                max_attempts=int(os.environ.get("OUTBOX_MAX_ATTEMPTS", "5")),
                base_backoff_seconds=float(
                    os.environ.get("OUTBOX_BASE_BACKOFF_SECONDS", "5")
                ),
                claim_lease_seconds=float(
                    os.environ.get("OUTBOX_CLAIM_LEASE_SECONDS", "300")
                ),
            )
            while True:
                handled = await worker.run_once()
                if not handled:
                    await asyncio.sleep(0.25)
        except Exception:
            await asyncio.sleep(2)
        finally:
            if pool is not None:
                await pool.close()


async def database_readiness_loop() -> None:
    global last_database_success
    while True:
        try:
            connection = await asyncpg.connect(
                os.environ["CORE_DATABASE_URL"],
                timeout=3,
            )
            try:
                await connection.fetchval("SELECT 1")
                last_database_success = time.monotonic()
            finally:
                await connection.close()
        except Exception:
            pass
        await asyncio.sleep(2)


async def service_loop() -> None:
    await asyncio.gather(durable_worker_loop(), database_readiness_loop())


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8010), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    asyncio.run(service_loop())


if __name__ == "__main__":
    main()
