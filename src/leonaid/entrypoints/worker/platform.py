"""Durable-worker process shell with dependency-aware health endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import asyncpg

from leonaid.adapters.operations import structured_event
from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.surveys import AsyncpgSurveyRepository
from leonaid.adapters.postgres.survey_retention import sweep_retention
from leonaid.adapters.postgres.survey_checkpoint_publisher import configured_publisher
from leonaid.entrypoints.worker.health import LoopHealth, error_location
from leonaid.entrypoints.worker.outbox import build_worker, configuration_problems

CLAIM_LEASE_SECONDS = float(os.environ.get("OUTBOX_CLAIM_LEASE_SECONDS", "300"))

# One job may legitimately run up to its claim lease (PDF rendering, SMTP,
# object storage), so the outbox loop counts as stalled only after that.
postgres_health = LoopHealth("postgres", stall_after_seconds=10)
outbox_health = LoopHealth("outbox", stall_after_seconds=CLAIM_LEASE_SECONDS + 30)
survey_health = LoopHealth("survey_sweep", stall_after_seconds=60)
LOOPS = (postgres_health, outbox_health, survey_health)


def worker_ready() -> bool:
    return all(loop.healthy() for loop in LOOPS)


def metrics_document() -> str:
    lines = [
        "# HELP leonaid_worker_ready Whether PostgreSQL is reachable and every worker loop makes progress.",
        "# TYPE leonaid_worker_ready gauge",
        f"leonaid_worker_ready {1 if worker_ready() else 0}",
        "# HELP leonaid_worker_loop_healthy Whether one worker loop completes iterations.",
        "# TYPE leonaid_worker_loop_healthy gauge",
    ]
    lines.extend(
        f'leonaid_worker_loop_healthy{{loop="{loop.name}"}} {1 if loop.healthy() else 0}'
        for loop in LOOPS
    )
    lines.extend(
        [
            "# HELP leonaid_worker_loop_failures_total Failed worker loop iterations.",
            "# TYPE leonaid_worker_loop_failures_total counter",
        ]
    )
    lines.extend(
        f'leonaid_worker_loop_failures_total{{loop="{loop.name}"}} {loop.total_failures}'
        for loop in LOOPS
    )
    lines.extend(
        [
            "# HELP leonaid_worker_loop_last_success_age_seconds Seconds since the loop last completed an iteration.",
            "# TYPE leonaid_worker_loop_last_success_age_seconds gauge",
        ]
    )
    for loop in LOOPS:
        age = loop.last_success_age()
        if age is not None:
            lines.append(
                f'leonaid_worker_loop_last_success_age_seconds{{loop="{loop.name}"}} {age:.3f}'
            )
    return "\n".join(lines) + "\n"


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        if self.path == "/health/live":
            self.respond(200, {"service": "leonaid-worker", "status": "live"})
            return
        if self.path == "/health/ready":
            ready = worker_ready()
            self.respond(
                200 if ready else 503,
                {
                    "service": "leonaid-worker",
                    "status": "ready" if ready else "not-ready",
                    "checks": {
                        loop.name: "ready" if loop.healthy() else "not-ready"
                        for loop in LOOPS
                    },
                },
            )
            return
        if self.path == "/metrics":
            body = metrics_document().encode()
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


def record_success(health: LoopHealth) -> None:
    if health.succeeded():
        print(structured_event("worker.loop.recovered", loop=health.name), flush=True)


def record_failure(
    health: LoopHealth, error: Exception, *, fixed_delay: float | None = None
) -> float:
    backoff = health.failed(error)
    delay = backoff if fixed_delay is None else fixed_delay
    print(
        structured_event(
            "worker.loop.failed",
            loop=health.name,
            errorType=type(error).__name__,
            location=error_location(error),
            consecutiveFailures=health.consecutive_failures,
            retryInSeconds=delay,
        ),
        flush=True,
    )
    return delay


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
                claim_lease_seconds=CLAIM_LEASE_SECONDS,
            )
            while True:
                handled = await worker.run_once()
                record_success(outbox_health)
                if not handled:
                    await asyncio.sleep(0.25)
        except Exception as error:
            delay = record_failure(outbox_health, error)
            await asyncio.sleep(delay)
        finally:
            if pool is not None:
                await pool.close()


async def database_readiness_loop() -> None:
    # The probe keeps a fixed cadence; it only measures reachability.
    probe_interval = 2.0
    while True:
        try:
            connection = await asyncpg.connect(
                os.environ["CORE_DATABASE_URL"],
                timeout=3,
            )
            try:
                await connection.fetchval("SELECT 1")
            finally:
                await connection.close()
            record_success(postgres_health)
        except Exception as error:
            record_failure(postgres_health, error, fixed_delay=probe_interval)
        await asyncio.sleep(probe_interval)


async def survey_timeout_loop() -> None:
    """Independent five-second sweep; catch up in bounded batches after outages."""
    while True:
        pool = None
        try:
            pool = await create_pool(os.environ["CORE_DATABASE_URL"], maximum_size=2)
            repository = AsyncpgSurveyRepository(pool)
            publisher = configured_publisher(pool)
            while True:
                closed = await repository.close_due_surveys()
                count = await repository.classify_overdue()
                retained = await sweep_retention(pool, checkpoint_publisher=publisher)
                record_success(survey_health)
                await asyncio.sleep(
                    0.25 if count == 1000 or closed == 100 or retained == 100 else 5
                )
        except Exception as error:
            # Logged by type and location only, never with private row data.
            delay = record_failure(survey_health, error)
            await asyncio.sleep(delay)
        finally:
            if pool is not None:
                await pool.close()


async def service_loop() -> None:
    await asyncio.gather(
        durable_worker_loop(), database_readiness_loop(), survey_timeout_loop()
    )


def main() -> None:
    problems = configuration_problems()
    if problems:
        print(
            structured_event(
                "worker.configuration.invalid", problems="; ".join(problems)
            ),
            flush=True,
        )
        raise SystemExit(78)
    server = ThreadingHTTPServer(("0.0.0.0", 8010), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    asyncio.run(service_loop())


if __name__ == "__main__":
    main()
