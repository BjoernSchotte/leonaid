# Pilot operation

Current bilingual operator guide:
[Deutsch](../../apps/docs/src/content/docs/de/ops/how-to/deploy-pilot.md) ·
[English](../../apps/docs/src/content/docs/en/ops/how-to/deploy-pilot.md).
This file remains the detailed pilot contract.

This additive configuration hardens the existing LeonAid core for exactly one
staging or production installation. It builds no images on the server and
publishes only Caddy, on ports 80/443.
The Twenty CRM UI is admin-only and has no public domain: `twenty-server`
publishes its port on `127.0.0.1:TWENTY_ADMIN_PORT` only, and
`./leonaid crm-admin --env-file FILE` prints the SSH tunnel to it.

## Environment boundary

Staging and production each get their own:

- portal domain and Twenty admin port;
- Compose projects, and with them their own networks, volumes and databases;
- RustFS buckets and Restic repositories;
- application, database, Twenty, RustFS and SMTP secrets;
- SMTP accounts and senders.

`LEONAID_DEPLOYMENT_STAGE`, `LEONAID_COMPOSE_PROJECT` and `RUSTFS_BUCKET`
must name the same environment. The deployment doctor blocks mix-ups. An
installation for another club is another, fully separate environment.

## Private configuration

`production.env.example` is only a safe template. The filled-in file:

1. lives outside the Git repository;
2. is owned only by the operations account and has mode `0600`;
3. holds a random, distinct value for every secret name;
4. references only digest-pinned release images;
5. binds `LEONAID_RELEASE_COMMIT` to the approved full Git SHA;
6. uses an external Restic target.

The file must never reach logs or public CI artifacts.
Containers get only the values their process needs. The public evidence
report contains only status values and error codes.

Release, migration, promotion and rollback follow
[`RELEASE-RUNBOOK.md`](RELEASE-RUNBOOK.md). Production accepts only a
manifest that was verified in staging with exactly the same SHA before.
Pilot users, role changes, offboarding, data-minimal feedback and the
support-code flow follow
[`ONBOARDING-SUPPORT-RUNBOOK.md`](ONBOARDING-SUPPORT-RUNBOOK.md).
The daily technical pilot check and the sanitized JSON report follow
[`LIVE-PILOT-RUNBOOK.md`](LIVE-PILOT-RUNBOOK.md).
The technical readiness dossier, the private acceptance record and the
explicit milestone decision follow
[`PILOT-ACCEPTANCE-RUNBOOK.md`](PILOT-ACCEPTANCE-RUNBOOK.md).
Production sender identities, the public DNS check, the bounce/complaint path,
rotation and provider recovery follow
[`MAIL-RUNBOOK.md`](MAIL-RUNBOOK.md).
The one-time Excel intake, dry run, conflict decisions, four-eyes apply
and verify follow [`IMPORT-RUNBOOK.md`](IMPORT-RUNBOOK.md).

## First installation

An empty host is set up once with `pilot-install`; the full server
preparation is described in
[Install on a fresh VPS](../../apps/docs/src/content/docs/en/ops/how-to/install-on-a-vps.md) ·
[Auf einem frischen VPS installieren](../../apps/docs/src/content/docs/de/ops/how-to/install-on-a-vps.md).

```sh
./leonaid pilot-secrets --output /etc/leonaid/production.env
./leonaid pilot-install \
  --env-file /etc/leonaid/production.env \
  --release-manifest /var/lib/leonaid/releases/release-manifest.json \
  --twenty-bootstrap-file /etc/leonaid/twenty-bootstrap.env \
  --password-file /etc/leonaid/secrets/restic-password \
  --credentials-file /etc/leonaid/secrets/restic-backend.env
```

`pilot-install` runs only on a project without volumes and containers, and
only while `TWENTY_INTEGRATION_API_KEY=PENDING_PILOT_INSTALL` is set.
Production Twenty requires verified email addresses and otherwise refuses
every token exchange, so the first administrator could never sign in. For
this reason `pilot-install` first starts only Twenty with
`compose.bootstrap.yml` (verification off, no proxy, no public access),
provisions schema, roles and key, verifies the administrator's address
through Twenty's own mutation `verifyEmailAndGetLoginToken` with a one-time
token, and then starts the full stack with verification active. The first
backup, monitoring with the watchdog heartbeat and the full doctor follow.

`systemd/leonaid-backup.timer` schedules daily backups.
`./leonaid pilot-repair-crm-match-keys` repairs the CRM match keys:
`systemd/leonaid-crm-repair.timer` runs every 15 minutes with a 30-minute
window, `leonaid-crm-repair-full.timer` runs a full repair nightly. In
maintenance mode the command skips with status 0.
Further CRM users verify their address by email through the same SMTP relay
as the core (see `MAIL-RUNBOOK.md`); Twenty sends mail only with
`MAIL_SMTP_MODE=tls`. The `LeonAidWatchdog` alert fires constantly and goes
only to the external URL from `LEONAID_ALERT_HEARTBEAT_URL_FILE`; if the pings
stop, the external service raises the alarm.

## Campaign pages (CMS)

`pilot-install` installs without the CMS and refuses
`LEONAID_CMS_ENABLED=true`. The campaign pages follow on the running
installation; the full procedure is in
[Install on a fresh VPS](../../apps/docs/src/content/docs/en/ops/how-to/install-on-a-vps.md#set-up-the-campaign-pages) ·
[Auf einem frischen VPS installieren](../../apps/docs/src/content/docs/de/ops/how-to/install-on-a-vps.md#aktionsseiten-einrichten).

```sh
# 1. LEONAID_CMS_ENABLED=true in production.env, then at once:
./leonaid pilot-cms-provision \
  --env-file /etc/leonaid/production.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --release-manifest /var/lib/leonaid/releases/release-manifest-cms.json \
  --system-admin-email admin@club.org
# 2. Exit 75 (PENDING): the System Admin completes the EmDash setup at
#    https://<admin host>/_emdash/admin/setup within 15 minutes.
# 3. The same command again (no --system-admin-email): campaign schema, OK.
# 4. pilot-backup (now with the CMS data), then pilot-deploy with the CMS
#    manifest.
```

The steps are database role, database and EmDash migrations (operator in
the campaign-site image), media bucket with its own scoped key (RustFS),
the one-time setup grant for the named System Admin, and the campaign
schema under closed CMS traffic (`tools/pilot_release/migrate-cms.sh
install`). Every run reads the state of each step first: a repeat changes
nothing, and a failed run continues at the open step. Until all four steps
are done, `pilot-deploy`, `pilot-release` and `pilot-doctor` refuse
`LEONAID_CMS_ENABLED=true`. From the first step on, every backup holds the
CMS database and its setup state (manifest schema 2); `pilot-restore`
recovers them with the target's verified campaign-site image.

## Compose and release check

Before a start, the effective configuration is generated and checked:

```sh
docker compose \
  --project-name leonaid-staging-club-111 \
  --env-file /etc/leonaid/staging.env \
  --file infra/compose/compose.yml \
  --file infra/pilot/compose.yml \
  config --format json
```

The contract blocks builds on the target system, unpinned images,
live-code mounts, additional host ports, public data networks,
loopback URLs, Mailpit and default secrets. The operator starts or
updates the environment only with the bound release manifest:

```sh
./leonaid pilot-deploy \
  --env-file /etc/leonaid/staging.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --release-manifest .local/pilot/evidence/release-2026.1.0.json
```

Before the start, the command verifies the checkout, the manifest, the
effective Compose images and all decisions due for `pilot-deploy`. It uses
only `up --no-build --pull missing`, waits for all health checks and then
runs the full deployment doctor. Drift between manifest and Compose never
reaches the start.

The full technical promotion with a fresh backup, maintenance mode,
explicit Twenty/core migrations and a sequential release ledger runs
through:

```sh
./leonaid pilot-release \
  --env-file /etc/leonaid/staging.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --release-manifest /var/lib/leonaid/evidence/release-2026.1.0.json \
  --ledger /var/lib/leonaid/evidence/release-ledger.jsonl \
  --password-file /secure/leonaid/restic-password \
  --credentials-file /secure/leonaid/restic-backend.env \
  --evidence-id PILOT-RELEASE-STAGING-2026-01
```

The evidence ID references the private functional browser and document
evidence for the same manifest SHA; it does not replace it.
Production is blocked before any mutation as long as exactly this SHA is not
recorded as `staging_verified` in the ledger.

## Backup and restore

Production backups also run only through a doctor-protected operator
command:

```sh
./leonaid pilot-backup \
  --env-file /etc/leonaid/production.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --password-file /secure/leonaid/restic-password \
  --credentials-file /secure/leonaid/restic-backend.env
```

A recovery drill needs a fresh `leonaid-restore-*` project, a separate
target environment and the exact confirmation. The target start does not
build:

```sh
./leonaid pilot-restore \
  --env-file /etc/leonaid/production.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --target-env-file /etc/leonaid/restore-drill-2026-07.env \
  --password-file /secure/leonaid/restic-password \
  --credentials-file /secure/leonaid/restic-backend.env \
  --confirm RESTORE:leonaid-restore-drill-2026-07
```

Source and target environment must reference the same external Restic
repository. Existing target containers or volumes, or a confirmation that
does not match, block the restore before any mutation.

## Deployment doctor

For a pure diagnosis, and afterwards before every further production gate:

```sh
./leonaid pilot-doctor \
  --env-file /etc/leonaid/staging.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --gate pilot-deploy
```

The doctor checks, without printing secrets:

- private file permissions, separate secrets, stage/project/bucket boundaries;
- approved commit, digests, Compose ports, networks and mounts;
- external backup target, manifest inventory and a backup age of at most 26 hours;
- at least 5 GiB of free storage;
- DNS resolution, hostname-validated TLS and at least 14 days of
  remaining certificate validity;
- HSTS, CSP and other security headers;
- portal, API/database readiness (includes Twenty's `/healthz`) and mail provider;
- warns (exit status unchanged) when `MAIL_SMTP_MODE` is not `tls`, because
  Twenty then sends no mail;
- clock skew against the `Date` header of the external mail provider;
- all functional decisions due for the selected gate.

Exit `0` means ready, `1` a technical blocker, `2` open decisions and
`3` a functional STOP decision. `--json` returns the same status in
machine-readable form. `--deployment-only` exists only for diagnosis and
tests; production commands always use the full doctor.

## TLS, headers and renewal

Caddy obtains and renews publicly trusted certificates automatically.
Port 80 stays reachable for ACME and the permanent HTTPS redirect. HSTS is
applied to the production domains only after the successful staging
evidence. The Caddy data and config volumes stay persistent; a certificate
error is a doctor blocker.

The real staging evidence, still open, must cover the public DNS records, the
full chain of trust, security headers and an observed renewal or a
documented renewal dry run.

## Abort and clean-up

Diagnose first:

```sh
docker compose \
  --project-name leonaid-staging-club-111 \
  --env-file /etc/leonaid/staging.env \
  --file infra/compose/compose.yml \
  --file infra/pilot/compose.yml \
  ps
```

A failed first empty staging start may be removed, including volumes, using
the exact project name. Deleting volumes in production is forbidden; there a
rollback follows only the backup/restore runbook from PILOT-041.
