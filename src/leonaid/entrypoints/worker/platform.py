"""Durable-worker process shell with dependency-aware health endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import asyncpg

from leonaid.adapters.operations import structured_event
from leonaid.adapters.postgres.outbox import AsyncpgOutboxQueue
from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.security import AsyncpgSecurityRateLimitRepository
from leonaid.bootstrap.worker import background_loops, build_worker
from leonaid.entrypoints.worker.health import LoopHealth, error_location
from leonaid.bootstrap.registry import RegistrationError
from leonaid.configuration import (
    ConfigurationError,
    load_module_settings,
    load_retention_settings,
)
from leonaid.entrypoints.worker.outbox import configuration_problems
from leonaid.entrypoints.worker.retention import (
    RetentionResult,
    sweep_operational_retention,
)
from leonaid.platform.background import BackgroundLoop

CLAIM_LEASE_SECONDS = float(os.environ.get("OUTBOX_CLAIM_LEASE_SECONDS", "300"))

# One job may legitimately run up to its claim lease (PDF rendering, SMTP,
# object storage), so the outbox loop counts as stalled only after that.
postgres_health = LoopHealth("postgres", stall_after_seconds=10)
outbox_health = LoopHealth("outbox", stall_after_seconds=CLAIM_LEASE_SECONDS + 30)


def _retention_interval_seconds() -> float:
    # Invalid settings stop the worker at startup (configuration_problems);
    # the default only keeps this module importable for that check.
    try:
        return load_retention_settings().interval_seconds
    except ConfigurationError:
        return 3600.0


# The retention loop sleeps a whole interval between sweeps, so it counts as
# stalled only after it missed one sweep by a clear margin.
retention_health = LoopHealth(
    "retention",
    stall_after_seconds=_retention_interval_seconds() + 300,
)


def _module_loops() -> tuple[BackgroundLoop, ...]:
    # Module loops need only the database URL and the module switches. Invalid
    # values stop the worker at startup in configuration_problems; until then
    # this module stays importable.
    try:
        disabled = load_module_settings().disabled_modules
        return background_loops(os.environ.get("CORE_DATABASE_URL", ""), disabled)
    except (ConfigurationError, RegistrationError):
        return ()


MODULE_LOOPS: tuple[BackgroundLoop, ...] = _module_loops()
MODULE_LOOP_HEALTH = tuple(
    LoopHealth(loop.name, stall_after_seconds=loop.stall_after_seconds)
    for loop in MODULE_LOOPS
)
LOOPS = (postgres_health, outbox_health, *MODULE_LOOP_HEALTH, retention_health)
if len({loop.name for loop in LOOPS}) != len(LOOPS):
    raise RuntimeError("Worker loop names must be unique.")
RETENTION_DELETED = {"outbox_event": 0, "security_rate_attempt": 0}


def record_retention(result: RetentionResult) -> None:
    RETENTION_DELETED["outbox_event"] += result.outbox_events_deleted
    RETENTION_DELETED["security_rate_attempt"] += result.rate_attempts_deleted
    if result.outbox_events_deleted or result.rate_attempts_deleted:
        print(
            structured_event(
                "worker.retention.swept",
                outboxEventsDeleted=result.outbox_events_deleted,
                rateAttemptsDeleted=result.rate_attempts_deleted,
                complete=result.complete,
            ),
            flush=True,
        )


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
    lines.extend(
        [
            "# HELP leonaid_worker_retention_deleted_total Rows deleted by the retention loop since worker start.",
            "# TYPE leonaid_worker_retention_deleted_total counter",
        ]
    )
    lines.extend(
        f'leonaid_worker_retention_deleted_total{{table="{table}"}} {count}'
        for table, count in RETENTION_DELETED.items()
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


class HealthReporter:
    """Connects one module loop to the shared health bookkeeping."""

    def __init__(self, health: LoopHealth) -> None:
        self._health = health

    def succeeded(self) -> None:
        record_success(self._health)

    def failed(self, error: Exception) -> float:
        return record_failure(self._health, error)


async def retention_loop() -> None:
    """Hourly by default; a sweep stopped by its batch cap resumes after 1 s."""
    settings = load_retention_settings()
    while True:
        pool = None
        try:
            pool = await create_pool(os.environ["CORE_DATABASE_URL"], maximum_size=1)
            queue = AsyncpgOutboxQueue(pool)
            rate_limits = AsyncpgSecurityRateLimitRepository(pool)
            while True:
                result = await sweep_operational_retention(
                    queue=queue,
                    rate_limits=rate_limits,
                    settings=settings,
                    now=datetime.now(timezone.utc),
                )
                record_retention(result)
                record_success(retention_health)
                await asyncio.sleep(
                    settings.interval_seconds if result.complete else 1.0
                )
        except Exception as error:
            # Logged by type and location only, never with row data.
            delay = record_failure(retention_health, error)
            await asyncio.sleep(delay)
        finally:
            if pool is not None:
                await pool.close()


async def service_loop() -> None:
    await asyncio.gather(
        durable_worker_loop(),
        database_readiness_loop(),
        *(
            loop.run(HealthReporter(health))
            for loop, health in zip(MODULE_LOOPS, MODULE_LOOP_HEALTH, strict=True)
        ),
        retention_loop(),
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
