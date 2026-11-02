---
title: Services, ports, and operator commands
description: Compact reference for the Compose runtime, exposed ports, and operational commands.
docId: DOC-P027
audience: [ops]
diataxis: reference
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: 387fe4766a067c6c8ff40079cc4f197824599259
reviewer: Björn Schotte
---

| Service                       | Responsibility                            | Authoritative persistence          |
| ----------------------------- | ----------------------------------------- | ---------------------------------- |
| Caddy                         | sole web entry point and TLS              | Caddy data for public certificates |
| FastAPI Core + worker         | auth, policies, domain operations, outbox | Core PostgreSQL                    |
| Web / PWA / Public / Campaign | admin, acquisition, and public UIs        | no authoritative domain data       |
| Twenty Server/Worker          | companies and people                      | Twenty PostgreSQL and files        |
| RustFS                        | private immutable document bytes          | RustFS volume                      |
| Mail relay                    | login, invitation, and invoice mail       | external provider; local Mailpit   |

Locally only Caddy publishes `127.0.0.1:8443` for HTTPS and
`127.0.0.1:8080` for diagnostic HTTP. If either port is taken, `bootstrap`
picks the first free pair from 28080 once and stores it as `LEONAID_HTTP_PORT`
and `LEONAID_HTTPS_PORT` in `.env.local`. For LAN access set
`LEONAID_BIND_ADDRESS=0.0.0.0` and `LEONAID_LAN_HOST` to the host's LAN
name, e.g. `myhost.local` (not an IP: browsers send no TLS SNI for it); the dev stack is then reachable from the LAN.
`LEONAID_REMOTE_HOST` adds a second name for the same stack, e.g. the host's
Tailscale or VPN name `myhost.tailnet.ts.net`; keep `127.0.0.1` when unused.
Apply changes with `./leonaid dev`. The pilot overlay exposes only 80/443.
Databases, Redis, S3, and internal APIs stay inside Compose networks.

Key commands are `bootstrap`, `doctor`, `dev`, `check`, `backup`, `restore`,
`pilot-doctor`, `pilot-deploy`, `pilot-release`, `pilot-backup`,
`pilot-restore`, `test-handoff`, `test-backup`, and `test-upgrade`. Run
`./leonaid help` for the current complete list; the CLI is authoritative when
this reference differs.

## Worker retention

The worker runs a `retention` loop next to `outbox`, `survey_sweep`, and the
PostgreSQL probe. Once per `OUTBOX_RETENTION_INTERVAL_SECONDS` (default
`3600`) it deletes outbox jobs that completed successfully more than
`OUTBOX_RETENTION_DAYS` (default `30`) ago, and rate-limit attempts older than
two days. It never deletes pending, processing, or dead-letter jobs, nor
completed jobs that a sent mail, an invoice delivery, a survey export, or a
survey erasure still references. It deletes in batches of
`OUTBOX_RETENTION_BATCH_SIZE` (default `500`) rows, at most
`OUTBOX_RETENTION_MAX_BATCHES` (default `20`) batches per sweep, and skips
rows that another session holds locked. Invalid values stop the worker at
start with `worker.configuration.invalid`. The metric
`leonaid_worker_retention_deleted_total{table=...}` counts deleted rows; the
outbox counters on `/admin/system` therefore show completed jobs of the
retention window only. `docker compose run --rm worker python -m
leonaid.entrypoints.worker.outbox retention-sweep` runs one sweep by hand.
