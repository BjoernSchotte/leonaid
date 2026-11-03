---
title: Services, ports, and operator commands
description: Compact reference for the Compose runtime, exposed ports, and operational commands.
docId: DOC-P027
audience: [ops]
diataxis: reference
contentRevision: 15
reviewedRevision: 15
verifiedAgainst: e222cf15eaacce659fa705321133f151d7e8d63f
reviewer: Björn Schotte
---

| Service                       | Responsibility                            | Authoritative persistence          |
| ----------------------------- | ----------------------------------------- | ---------------------------------- |
| Caddy                         | sole web entry point and TLS              | Caddy data for public certificates |
| FastAPI Core + worker         | auth, policies, domain operations, outbox | Core PostgreSQL                    |
| Web / PWA / Public / Campaign | admin, acquisition, and public UIs        | no authoritative domain data       |
| Twenty Server/Worker          | companies and people; admin-only UI       | Twenty PostgreSQL and files        |
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
Apply changes with `./leonaid dev`. The pilot overlay exposes only 80/443
publicly. The Twenty CRM has no public domain: `twenty-server` publishes its
port only on the host's loopback address, `127.0.0.1:TWENTY_ADMIN_PORT`
(default 3020), and joins the `crm-data` network and its own `crm-admin`
network, never the proxy's `edge` network. Its `SERVER_URL` and
`AUTH_COOKIE_ALLOWED_ORIGINS` are `http://localhost:TWENTY_ADMIN_PORT`. `./leonaid crm-admin --env-file FILE`
checks the loopback binding and prints the `ssh -N -L PORT:127.0.0.1:PORT`
command that the system administrator runs on a workstation before opening
`http://localhost:PORT`.
Databases, the Valkey queue store, S3, and internal APIs stay inside Compose
networks. In the pilot, only the worker and the Twenty worker join the `mail-egress`
network, the only route to the external SMTP relay. Twenty sends mail only with
`MAIL_SMTP_MODE=tls` (implicit TLS on port 465), because its SMTP client cannot
enforce STARTTLS. With `starttls` the Twenty containers start with the logger
mail driver and send nothing; `pilot-doctor` warns but does not block.

Key commands are `bootstrap`, `doctor`, `dev`, `check`, `backup`, `restore`,
`pilot-doctor`, `pilot-deploy`, `pilot-release`, `pilot-backup`,
`pilot-restore`, `pilot-repair-crm-match-keys`, `crm-admin`, `test-handoff`, `test-backup`, and `test-upgrade`. Run
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

## Module switches

Business modules are on by default. `LEONAID_DISABLED_MODULES` in the
installation's env file switches modules off, comma-separated, for example
`LEONAID_DISABLED_MODULES=surveys`. Switchable modules are `surveys`, `tasks`, `materials`, `knowledge` and `inbox`
(knowledge and inbox need tasks and materials); core areas such as mail and invoicing cannot be switched off. The API,
the worker and the public sites (`public`, `campaign-site`) read the same
value; restart them after a change. With `inbox` switched off, the public
pages show no inquiry form.

A switched-off module keeps all its data. It shows no navigation, its API
routes are not registered and answer 404, and the web pages fall back to the
overview. The worker runs none of its loops and leaves its jobs pending:
they are neither attempted nor dead-lettered, and they run once the module
is on again. An unknown or non-switchable ID, or switching off a module that
another enabled module requires, stops the API at start and the worker with
`worker.configuration.invalid`.

## Material upload cleanup

An interrupted material upload can leave a private object-storage version
that no material references. Repeating the upload adopts it. To remove one
such version for good, run `docker compose exec api python -m
leonaid.entrypoints.material_cleanup` with the exact material, upload and
storage version; it checks first and deletes only with `--apply`. The
procedure is in `tools/materials/README.md`.

## Job runtime and error details

A module may bound the runtime of its outbox handlers. The worker caps every
bound at 80 % of `OUTBOX_CLAIM_LEASE_SECONDS` (default `300`). Survey export
rendering is bounded at 240 s. A job that exceeds its bound is cancelled and
retried with the error code `job_timeout`. Jobs store only the safe error
code as their error detail, never exception text. Every job log line
(`outbox.job.*`) carries `durationMs` when the job finished, failed or lost
its claim.

The outbox card on `/admin/system` also shows the next pending attempt
and how long the oldest due job has waited (API fields `nextPendingAttemptAt`
and `oldestDuePendingAgeSeconds`). Jobs of switched-off modules are left out
of both values, because they wait on purpose. A growing wait with a running
worker points to a stuck or overloaded queue.

## Runtime limits and identity

Every long-running service has a memory, CPU, and process limit
(`mem_limit`, `cpus`, `pids_limit`) and rotated logs (`local` driver, 5 × 10 MB).
The limits are ceilings, not reservations. The pilot set, including the
monitoring profile, fits an 8 GB VPS and leaves about 1.6 GiB for the operating
system and Docker. The deployment contract (`pilot-doctor`, `pilot-deploy`)
rejects limits whose sum leaves less than 1.5 GiB. "Peak" is the highest working set
measured under load (upgrade, installation, CRM import of 3000 rows, golden
journey, backup and restore; measured on 2 November 2026 with Twenty 2.54).
"Idle" ranges from the 5th percentile to the median of all samples.

| Service                       | Observed (idle) | Peak (load) | Memory limit | CPUs | PIDs |
| ----------------------------- | --------------- | ----------- | ------------ | ---- | ---- |
| twenty-server                 | 330–680 MiB     | 1223 MiB    | 1728 MiB     | 2    | 512  |
| twenty-worker                 | 590–640 MiB     | 960 MiB     | 1400 MiB     | 1.5  | 512  |
| worker (incl. Typst)          | 70 MiB          | 94 MiB      | 512 MiB      | 1.5  | 256  |
| api                           | 105–110 MiB     | 151 MiB     | 384 MiB      | 1.5  | 256  |
| core-postgres                 | 20–22 MiB       | 70 MiB      | 384 MiB      | 1.5  | 256  |
| twenty-postgres               | 29–65 MiB       | 139 MiB     | 384 MiB      | 1.5  | 256  |
| twenty-redis (Valkey)         | 4–15 MiB        | 30 MiB      | 512 MiB      | 0.5  | 64   |
| rustfs                        | 22–23 MiB       | 49 MiB      | 256 MiB      | 1    | 256  |
| survey-validator              | 14–17 MiB       | 27 MiB      | 128 MiB      | 1    | 64   |
| proxy (Caddy)                 | 13–18 MiB       | 31 MiB      | 128 MiB      | 1    | 128  |
| public                        | 23–25 MiB       | 75 MiB      | 128 MiB      | 1    | 64   |
| web, pwa                      | 13–14 MiB each  | 20 MiB      | 64 MiB each  | 0.5  | 64   |
| **Core sum**                  | ~1.7 GiB        | 2.4 GiB¹    | **5.9 GiB**  |      |      |
| prometheus                    | 59–63 MiB       | 69 MiB      | 256 MiB      | 0.5  | 128  |
| pilot-exporter                | 18–19 MiB       | 30 MiB      | 128 MiB      | 0.5  | 64   |
| alertmanager                  | 22–25 MiB       | 27 MiB      | 64 MiB       | 0.25 | 64   |
| **Pilot sum with monitoring** |                 |             | **6.4 GiB**  |      |      |

¹ Highest sum of all working sets at the same moment, not the sum of the peaks.

The optional campaign site (`emdash` profile) adds 384 MiB. If a service is
OOM-killed (`docker inspect` shows `OOMKilled: true`), raise its limit and
lower another one so that the sum still fits the host.

Node sizes the V8 heap from the container limit unless told otherwise.
`twenty-server` therefore sets `NODE_OPTIONS=--max-old-space-size=1024` and
`twenty-worker` sets `--max-old-space-size=768`. Measured heap peaks: 742 of
the 1072 MiB heap limit (69 %) for `twenty-server` and 560 of 816 MiB (69 %)
for `twenty-worker`. The `twenty-server` peak comes with every start: before
`node dist/main`, `yarn command:prod upgrade` runs with up to 1085 MiB RSS
plus the yarn wrapper, so the limit is 1728 MiB. Never lower a Twenty memory
limit without checking this value; otherwise Twenty stops with "JavaScript
heap out of memory". The deployment contract requires at least 256 MiB
between `--max-old-space-size` and `mem_limit`. `twenty-worker`
starts `node dist/queue-worker/queue-worker` directly, without the yarn
wrapper processes (about 200 MiB). Both Twenty services run with `init: true`,
so `docker stop` lets Twenty finish its active jobs and exit cleanly.

`twenty-redis` runs Valkey 9.1, a BSD-licensed server for the Redis protocol.
The service keeps its name because Twenty reads `REDIS_URL`. It gets
`--maxmemory 384mb` with `noeviction`, which BullMQ requires: when full, it
rejects writes with an error before the container limit kills it. Twenty keeps
up to 1000 completed and 1000 failed jobs per queue (4 hours and 7 days); a
large CRM import fills the store by about 20 MiB per minute. Valkey cannot
load the data files of Redis 7.4. `pilot-release` (and locally the first
`up` of a `./leonaid` command) therefore runs
`infra/upgrade/twenty-queue-store.sh migrate` once: it stops `twenty-server`,
lets the old `twenty-worker` finish all waiting, active and delayed jobs (at
most `LEONAID_QUEUE_DRAIN_TIMEOUT` seconds, default 300), and then empties the
volume. The job history and the cache are lost; cron jobs are registered again
when `twenty-server` starts. If jobs are still pending after the timeout, the
command stops and leaves the volume unchanged; set
`LEONAID_QUEUE_DISCARD_PENDING=true` only if those jobs may be dropped.
`pilot-deploy` refuses an unmigrated store.

The Core image runs as the fixed user `10001:10001`. `api`, `worker`, `web`,
`pwa`, `public`, and `survey-validator` run with a read-only root filesystem, a
small `tmpfs` at `/tmp`, no Linux capabilities, and `no-new-privileges`.
`pilot-doctor` rejects a pilot configuration without these settings. Releases
before this change ran the Core as root and wrote the survey erasure archive
as root. The one-shot service `core-volume-init` therefore hands that volume
over to `10001:10001` before every `api`/`worker` start; existing installs need
no manual step. `pilot-exporter` runs as the account that calls `./leonaid`,
because it reads that account's `0600` backup manifest.
