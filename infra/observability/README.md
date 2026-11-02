# Operations in the PoC

LeonAid separates process availability, dependency readiness and business
job failures. System administration sees these signals at `/admin/system`;
the underlying contract is `GET /api/v1/admin/operations`.

## Signals

| Signal | Source | Meaning |
| --- | --- | --- |
| `/health/live` | FastAPI | The API process responds |
| `/health/ready` | FastAPI | PostgreSQL, Twenty and RustFS are ready |
| Operations dependencies | Active HTTP probes | Twenty, RustFS and mail are each reachable |
| API metrics | FastAPI process | Requests, server errors and mean latency since process start |
| Outbox/mail metrics | Core PostgreSQL | pending, processing, completed and dead letter |
| Login metrics | AuditEvent | Requests, completions and failures in the last 24 hours |

Mail is not readiness-critical for reading and most business operations. A
mail outage therefore appears as its own operations signal and as a
retryable outbox job, but does not set `/health/ready` to 503.

## Correlation and log contract

A valid browser header `X-Request-ID` is accepted; otherwise FastAPI creates a
UUID. The same ID appears in the HTTP response, in the completed request log
and in the direct probes to Twenty, RustFS and Mailpit or the later mail
service.

Logs are single-line JSON objects. Only technical fields are allowed, such
as:

- event name, timestamp, request, job, action and relevant object ID;
- HTTP method, normalized path, status and latency;
- event/aggregate type, attempt counter and stable error code;
- dependency name and status.

Request or event payloads, query parameters, email, name, session/magic-link
tokens, error details, mail text and document bytes are never logged.
Detailed technical errors stay protected in the respective outbox record and
are shown in the admin interface only as a stable code.

## Retry a dead letter safely

1. Sign in freshly as system admin.
2. Open `/admin/system` and fix the dependency.
3. Choose `Sicher wiederholen` (safe retry) on the affected job.
4. Check that the job disappears from the failure backlog and that the
   `completed` count rises.

The API endpoint accepts only jobs currently marked as `dead_letter`,
requires system admin plus a fresh sign-in and writes operator, timestamp,
counters and an AuditEvent atomically. The business handlers stay idempotent;
a second click on the same state is rejected as a conflict.

## Reproducible evidence

```sh
./leonaid test-operations
```

The test uses fresh real volumes. It stops Twenty, RustFS and Mailpit one at a
time, checks liveness/readiness, creates a real login-mail dead letter with
SMTP switched off and processes it exactly once after the system admin clicks
in Chromium. Known PII, token and document signatures are then checked
against the collected logs.

## Pilot monitoring

For the pilot, the Compose profile `monitoring` extends the existing
operations contract with:

- Prometheus 3.15.1 for scraping and ten versioned P0/P1/P2 rules;
- Alertmanager 0.34.2 for grouping, deduplication and resolved notifications;
- a small LeonAid exporter for backup age, capacity and public TLS, without a
  Docker socket or privileged container;
- an externally configured webhook from a private 0600 file. This channel
  must not depend on the LeonAid mail path.

Both upstream images are pinned by tag and multi-arch digest in
`infra/locks/external-systems.lock`. Prometheus and Alertmanager have no
public host ports. The metrics endpoints of API and worker are reachable only
in the internal `telemetry` network.

The system admin area `/admin/system` reads a semantic status for backup, free
space, TLS and active alerts from the same internal sources. It shows
understandable states, priority and runbook instead of PromQL or raw metrics.
Without a started `monitoring` profile, this area stays explicitly neutral at
„Nicht aktiv“ (not active).

Alert texts consist only of fixed summaries, technical labels and links to
[`RUNBOOKS.md`](RUNBOOKS.md). Maintenance mode suppresses expected
availability, job and API alerts, but not backup, capacity or TLS/security
alerts.

The real end-to-end evidence runs in isolation:

```sh
./leonaid test-pilot-alerting
```

The test validates the production configurations with `promtool` and
`amtool`, stops all four critical services, forces backup and storage alerts,
checks the semantic admin status against the same sources and verifies alert
delivery and recovery for each.
