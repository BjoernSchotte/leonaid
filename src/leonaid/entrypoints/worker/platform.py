"""Durable-worker process shell with dependency-aware health endpoints."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import asyncpg

from leonaid.adapters.operations import structured_event
from leonaid.adapters.postgres.outbox import AsyncpgOutboxQueue
from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.security import AsyncpgSecurityRateLimitRepository
from leonaid.application.delivery_day_mails import (
    SWEEP_BATCH,
    SWEEP_INTERVAL_SECONDS,
)
from leonaid.bootstrap.worker import (
    SPONSOR_SEARCH_SYNC_STATUS,
    background_loops,
    build_delivery_day_mail_sweep,
    build_geocoding_job,
    build_worker,
)
from leonaid.entrypoints.worker.health import LoopHealth, error_location
from leonaid.bootstrap.registry import RegistrationError
from leonaid.configuration import (
    ConfigurationError,
    load_link_settings,
    load_map_settings,
    load_module_settings,
    load_retention_settings,
)
from leonaid.entrypoints.worker.outbox import configuration_problems
from leonaid.entrypoints.worker.retention import (
    RetentionResult,
    delivery_read_audits,
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


# Lookups per run; a full batch runs the next one after a second.
GEOCODING_BATCH = 30
# Worst case of one run: every lookup waits for its timeout (10 s) plus the
# one-second gap of the public Nominatim.
GEOCODING_RUN_SECONDS = GEOCODING_BATCH * 11


def _geocoding_interval_seconds() -> float:
    try:
        return load_map_settings().geocoding_interval_seconds
    except ConfigurationError:
        return 60.0


geocoding_health = LoopHealth(
    "geocoding",
    stall_after_seconds=_geocoding_interval_seconds() + GEOCODING_RUN_SECONDS + 60,
)
GEOCODING_LOOKUPS = {"total": 0}

# The sweep runs every five minutes; one run is one short transaction.
delivery_day_mail_health = LoopHealth(
    "delivery_day_mail",
    stall_after_seconds=SWEEP_INTERVAL_SECONDS + 120,
)
DELIVERY_DAY_MAILS_QUEUED = {"total": 0}


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
LOOPS = (
    postgres_health,
    outbox_health,
    *MODULE_LOOP_HEALTH,
    retention_health,
    geocoding_health,
    delivery_day_mail_health,
)
if len({loop.name for loop in LOOPS}) != len(LOOPS):
    raise RuntimeError("Worker loop names must be unique.")
RETENTION_DELETED = {
    "outbox_event": 0,
    "security_rate_attempt": 0,
    "delivery_read_audit": 0,
}


def record_retention(result: RetentionResult) -> None:
    RETENTION_DELETED["outbox_event"] += result.outbox_events_deleted
    RETENTION_DELETED["security_rate_attempt"] += result.rate_attempts_deleted
    RETENTION_DELETED["delivery_read_audit"] += result.read_audits_deleted
    if (
        result.outbox_events_deleted
        or result.rate_attempts_deleted
        or result.read_audits_deleted
    ):
        print(
            structured_event(
                "worker.retention.swept",
                outboxEventsDeleted=result.outbox_events_deleted,
                rateAttemptsDeleted=result.rate_attempts_deleted,
                readAuditsDeleted=result.read_audits_deleted,
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
    lines.extend(
        [
            "# HELP leonaid_worker_geocoding_lookups_total Geocoder lookups since worker start.",
            "# TYPE leonaid_worker_geocoding_lookups_total counter",
            f"leonaid_worker_geocoding_lookups_total {GEOCODING_LOOKUPS['total']}",
            "# HELP leonaid_worker_delivery_day_mails_queued_total Delivery-day mail jobs queued by the sweep since worker start.",
            "# TYPE leonaid_worker_delivery_day_mails_queued_total counter",
            f"leonaid_worker_delivery_day_mails_queued_total {DELIVERY_DAY_MAILS_QUEUED['total']}",
        ]
    )
    sponsor_search = SPONSOR_SEARCH_SYNC_STATUS
    if sponsor_search.configured:
        age = sponsor_search.last_success_age_seconds(datetime.now(timezone.utc))
        lines.extend(
            [
                "# HELP leonaid_worker_sponsor_search_last_success_age_seconds Seconds since a pass of the sponsor search sync last completed.",
                "# TYPE leonaid_worker_sponsor_search_last_success_age_seconds gauge",
                f"leonaid_worker_sponsor_search_last_success_age_seconds {age:.3f}",
                "# HELP leonaid_worker_sponsor_search_crm_errors_total Runs of the sponsor search sync that a CRM error ended, since worker start.",
                "# TYPE leonaid_worker_sponsor_search_crm_errors_total counter",
                f"leonaid_worker_sponsor_search_crm_errors_total {sponsor_search.crm_errors_total}",
            ]
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


async def pause(stopping: asyncio.Event, seconds: float) -> None:
    """Sleep, but wake at once when the worker is told to stop."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stopping.wait(), seconds)


async def durable_worker_loop(stopping: asyncio.Event) -> None:
    """Claims jobs until SIGTERM; the job in hand always finishes first."""
    while not stopping.is_set():
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
            while not stopping.is_set():
                handled = await worker.run_once()
                record_success(outbox_health)
                if not handled:
                    await pause(stopping, 0.25)
        except Exception as error:
            delay = record_failure(outbox_health, error)
            await pause(stopping, delay)
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
                    read_audits=delivery_read_audits(pool),
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


async def geocoding_loop() -> None:
    """Coordinates for upcoming deliveries while ``delivery.tours`` is on.

    Every interval (default 60 s) one bounded run; a full batch continues
    after a second. Logged by count only, never with an address.
    """
    settings = load_map_settings()
    while True:
        pool = None
        geocoder = None
        try:
            pool = await create_pool(os.environ["CORE_DATABASE_URL"], maximum_size=2)
            job, geocoder = build_geocoding_job(pool, settings)
            while True:
                looked_up = await job.run_once(
                    now=datetime.now(timezone.utc), limit=GEOCODING_BATCH
                )
                record_success(geocoding_health)
                if looked_up:
                    GEOCODING_LOOKUPS["total"] += looked_up
                    print(
                        structured_event("worker.geocoding.ran", lookups=looked_up),
                        flush=True,
                    )
                await asyncio.sleep(
                    1.0
                    if looked_up == GEOCODING_BATCH
                    else settings.geocoding_interval_seconds
                )
        except Exception as error:
            delay = record_failure(geocoding_health, error)
            await asyncio.sleep(delay)
        finally:
            if geocoder is not None:
                await geocoder.close()
            if pool is not None:
                await pool.close()


async def delivery_day_mail_loop() -> None:
    """Queues the mails of today's deliveries (``delivery_day_mail_sweep``).

    Every five minutes one bounded run; a full batch continues after a
    second. Several workers may run this loop: an advisory lock lets one of
    them sweep. Logged by count only, never with an order or an address.
    """
    links = load_link_settings().links
    while True:
        pool = None
        try:
            pool = await create_pool(os.environ["CORE_DATABASE_URL"], maximum_size=1)
            sweep = build_delivery_day_mail_sweep(pool, links)
            while True:
                queued = await sweep.run_once(now=datetime.now(timezone.utc))
                record_success(delivery_day_mail_health)
                if queued:
                    DELIVERY_DAY_MAILS_QUEUED["total"] += queued
                    print(
                        structured_event(
                            "worker.delivery_day_mail.queued", jobs=queued
                        ),
                        flush=True,
                    )
                await asyncio.sleep(
                    1.0 if queued >= SWEEP_BATCH else SWEEP_INTERVAL_SECONDS
                )
        except Exception as error:
            delay = record_failure(delivery_day_mail_health, error)
            await asyncio.sleep(delay)
        finally:
            if pool is not None:
                await pool.close()


async def service_loop() -> None:
    """Runs every loop; SIGTERM drains the outbox worker and stops the rest.

    The sweeps (readiness, module loops, retention, geocoding, delivery-day
    mails) work in short database
    transactions, so cancelling them rolls back at most one batch. Only the
    outbox worker holds a job that must not be cut off; it stops claiming and
    finishes the job in hand (compose.yml stop_grace_period covers the
    longest bounded handler).
    """
    stopping = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stopping.set)
    worker = asyncio.create_task(durable_worker_loop(stopping))
    sweeps = [
        asyncio.create_task(database_readiness_loop()),
        *(
            asyncio.ensure_future(loop.run(HealthReporter(health)))
            for loop, health in zip(MODULE_LOOPS, MODULE_LOOP_HEALTH, strict=True)
        ),
        asyncio.create_task(retention_loop()),
        asyncio.create_task(geocoding_loop()),
        asyncio.create_task(delivery_day_mail_loop()),
    ]
    # The loops never return on their own: the first one to finish is the
    # drained worker after SIGTERM, or a loop that crashed.
    await asyncio.wait([worker, *sweeps], return_when=asyncio.FIRST_COMPLETED)
    stopping.set()
    for sweep in sweeps:
        sweep.cancel()
    results = await asyncio.gather(worker, *sweeps, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException) and not isinstance(
            result, asyncio.CancelledError
        ):
            raise result
    print(structured_event("worker.stopped"), flush=True)


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
