---
title: Services, ports, and operator commands
description: Compact reference for the Compose runtime, exposed ports, and operational commands.
docId: DOC-P027
audience: [ops]
diataxis: reference
contentRevision: 5
reviewedRevision: 5
verifiedAgainst: afa78a892a766115c5b0c3d33f0af8ac4c751c13
reviewer: Björn Schotte
---

| Service                       | Responsibility                            | Authoritative persistence          |
| ----------------------------- | ----------------------------------------- | ---------------------------------- |
| Caddy                         | sole web entry point and TLS              | Caddy data for public certificates |
| FastAPI Core + worker         | auth, policies, domain operations, outbox | Core PostgreSQL                    |
| Web / PWA / Public / Campaign | admin, acquisition, and public UIs        | no authoritative domain data       |
| Twenty Server/Worker          | companies and people                      | Twenty PostgreSQL and files        |
| RustFS                        | private immutable document bytes          | RustFS volume                      |
| Mail relay                    | LeonAid and Twenty CRM mail               | external provider; local Mailpit   |

Locally only Caddy publishes `127.0.0.1:8443` for HTTPS and
`127.0.0.1:8080` for diagnostic HTTP. If either port is taken, `bootstrap`
picks the first free pair from 28080 once and stores it as `LEONAID_HTTP_PORT`
and `LEONAID_HTTPS_PORT` in `.env.local`. For LAN access set
`LEONAID_BIND_ADDRESS=0.0.0.0` and `LEONAID_LAN_HOST` to the host's LAN
name, e.g. `myhost.local` (not an IP: browsers send no TLS SNI for it); the dev stack is then reachable from the LAN.
`LEONAID_REMOTE_HOST` adds a second name for the same stack, e.g. the host's
Tailscale or VPN name `myhost.tailnet.ts.net`; keep `127.0.0.1` when unused.
Apply changes with `./leonaid dev`. The pilot overlay exposes only 80/443.
Databases, Redis, S3, and internal APIs stay inside Compose networks. In
the pilot, only the worker and the Twenty worker join the `mail-egress`
network, the only route to the external SMTP relay.

Key commands are `bootstrap`, `doctor`, `dev`, `check`, `backup`, `restore`,
`pilot-doctor`, `pilot-deploy`, `pilot-release`, `pilot-backup`,
`pilot-restore`, `pilot-repair-crm-match-keys`, `test-handoff`, `test-backup`, and `test-upgrade`. Run
`./leonaid help` for the current complete list; the CLI is authoritative when
this reference differs.

## Worker retention

The worker runs a `retention` loop next to `outbox`, `survey_sweep`, and the
PostgreSQL probe. Once per `OUTBOX_RETENTION_INTERVAL_SECONDS` (default
`3600`) it deletes outbox jobs that completed successfully more than
`OUTBOX_RETENTION_DAYS` (default `30`) ago, and rate-limit attempts older than
two days. It never deletes pending, processing, or dead-letter jobs, nor
completed jobs that an invoice delivery, a survey export, or a survey
erasure still references. For a sent mail it deletes the job but keeps the
`mail_delivery` record as evidence, without the link to the job. It deletes in batches of
`OUTBOX_RETENTION_BATCH_SIZE` (default `500`) rows, at most
`OUTBOX_RETENTION_MAX_BATCHES` (default `20`) batches per sweep, and skips
rows that another session holds locked. Invalid values stop the worker at
start with `worker.configuration.invalid`. The metric
`leonaid_worker_retention_deleted_total{table=...}` counts deleted rows; the
outbox counters on `/admin/system` therefore show completed jobs of the
retention window only. `docker compose run --rm worker python -m
leonaid.entrypoints.worker.outbox retention-sweep` runs one sweep by hand.

## Runtime limits and identity

Every long-running service has a memory, CPU, and process limit
(`mem_limit`, `cpus`, `pids_limit`) and rotated logs (`local` driver, 5 × 10 MB).
The limits are ceilings, not reservations. The pilot set, including the
monitoring profile, fits an 8 GB VPS and leaves about 1.4 GiB for the operating
system and Docker.

| Service                     | Observed (idle) | Memory limit | CPUs | PIDs |
| --------------------------- | --------------- | ------------ | ---- | ---- |
| twenty-server               | 610–780 MiB     | 1600 MiB     | 2    | 512  |
| twenty-worker               | 630–670 MiB     | 1400 MiB     | 1.5  | 512  |
| worker (incl. Typst)        | 70 MiB          | 768 MiB      | 1.5  | 256  |
| api                         | 115 MiB         | 384 MiB      | 1.5  | 256  |
| core-postgres               | 27 MiB          | 384 MiB      | 1.5  | 256  |
| twenty-postgres             | 35 MiB          | 384 MiB      | 1.5  | 256  |
| twenty-redis                | 15–31 MiB       | 256 MiB      | 0.5  | 64   |
| rustfs                      | 40 MiB          | 256 MiB      | 1    | 256  |
| survey-validator            | 21 MiB          | 256 MiB      | 1    | 64   |
| proxy (Caddy)               | 16 MiB          | 128 MiB      | 1    | 128  |
| public                      | 29 MiB          | 128 MiB      | 1    | 64   |
| web, pwa                    | 16–17 MiB each  | 64 MiB each  | 0.5  | 64   |
| **Core sum**                | ~2.5 GiB        | **5.9 GiB**  |      |      |
| prometheus                  | —               | 256 MiB      | 0.5  | 128  |
| pilot-exporter              | —               | 128 MiB      | 0.5  | 64   |
| alertmanager                | —               | 64 MiB       | 0.25 | 64   |
| **Pilot sum with monitoring** |               | **6.4 GiB**  |      |      |

The optional campaign site (`emdash` profile) adds 384 MiB. Redis gets
`--maxmemory 192mb`: with `noeviction` it rejects writes before the container
limit kills it. If a service is OOM-killed (`docker inspect` shows
`OOMKilled: true`), raise its limit and lower another one so that the sum
still fits the host.

The Core image runs as the fixed user `10001:10001`. `api`, `worker`, `web`,
`pwa`, `public`, and `survey-validator` run with a read-only root filesystem, a
small `tmpfs` at `/tmp`, no Linux capabilities, and `no-new-privileges`.
`pilot-doctor` rejects a pilot configuration without these settings. Releases
before this change ran the Core as root and wrote the survey erasure archive
as root. The one-shot service `core-volume-init` therefore hands that volume
over to `10001:10001` before every `api`/`worker` start; existing installs need
no manual step. `pilot-exporter` runs as the account that calls `./leonaid`,
because it reads that account's `0600` backup manifest.
