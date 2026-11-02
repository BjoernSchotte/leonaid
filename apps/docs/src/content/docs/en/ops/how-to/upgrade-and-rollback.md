---
title: Upgrade and roll back
description: Update pinned Core, Twenty, and RustFS versions behind a maintenance boundary with a tested recovery path.
docId: DOC-P024
audience: [ops]
diataxis: how-to
contentRevision: 6
reviewedRevision: 6
verifiedAgainst: 75efa66ef1cf6e5264d268f447f3148e62798202
reviewer: Björn Schotte
---

## Review pins and vulnerability findings

Renovate (`renovate.json`) opens grouped update PRs every Monday for
container images, `uv.lock`, `bun.lock`, and GitHub Actions digests. Security
fixes arrive at once in separate PRs. Twenty, PostgreSQL, Valkey, and RustFS
get their own PRs with the label `needs-upgrade-runbook`; follow the steps
below for them. Nothing merges automatically.

`infra/locks/external-systems.lock` records `reviewedAt` and `nextReviewOn`.
`./leonaid check` fails once `nextReviewOn` has passed. To re-review, compare
every pinned tag with its latest upstream release and advisories, upgrade or
consciously keep it, and run `./leonaid check` and `tools/ci/security.sh`.
Then set `reviewedAt` to the review date and `nextReviewOn` to at most three
months later. The checker refuses more than six months.

The security CI job (`tools/ci/security.sh`) blocks every fixable HIGH or
CRITICAL finding:

- Trivy scans the checkout, all LeonAid images, and every third-party runtime
  image listed in `infra/security/image-scan-scope.json`. Each system in the
  lock must be either scanned or excluded there with a reason.
- OSV-Scanner audits `uv.lock` and `bun.lock`.

If no fix exists yet, add a waiver to
`infra/security/vulnerability-allowlist.json` with the advisory id, the
affected targets, a reason, the reviewer, `reviewedOn`, and `expires` (at most
90 days later). An expired waiver fails `./leonaid check` and the security
job. Then upgrade and delete the waiver, or review it again.

## Upgrade

First update `infra/locks/external-systems.lock`, `infra/locks/images.env`, and
`infra/upgrade/compatibility-matrix.json`. Read release notes and migrations,
run `./leonaid check` and `./leonaid test-upgrade`, and record the maintenance
window, owner, and a fresh recovery point.

1. Run `infra/upgrade/maintenance.sh enable` and verify that writes return
   `503 maintenance_mode` with `Retry-After`.
2. Create and verify an encrypted backup.
   Then run `infra/upgrade/twenty-queue-store.sh migrate` (part of
   `pilot-release`). It drains the queues of a Redis 7.4 store with the old
   Twenty worker and empties the volume, because Valkey cannot load it.
3. Update RustFS and start Twenty once to initialise its prerequisites.
   Starting the target services makes Compose recreate `core-postgres` and
   `twenty-postgres` with the new PostgreSQL image on the same volumes. A minor release within major
   version 16 keeps the data format, so no dump or `pg_upgrade` runs.
   `./leonaid test-upgrade` proves this from the previous pinned release.
4. Stop Twenty Server and run its official `command:prod
run-instance-commands` and `command:prod upgrade` commands through the
   pinned Compose service. Both must exit with zero.
5. Apply the declared Twenty schema with `tools/twenty/provision.py apply`
   (locally `./leonaid provision-twenty`) before Core starts. Core writes and
   reads the provisioned CRM match key field; without it, CRM writes fail.
6. Backfill the CRM match keys of existing companies and people with
   `python -m leonaid.entrypoints.crm_match_keys` in the Core image (locally
   `./leonaid repair-crm-match-keys`). The run is idempotent and changes only
   records whose stored key differs from their name.
7. Migrate Core explicitly, start services, and verify images, schemas, health
   checks, the Golden contract, and the browser journey.
8. Disable maintenance only after those checks pass.

## Roll back

After the first schema write, rollback means restore. Never start an older
image against a forward-migrated database. Keep writes blocked, stop the
failed project, and restore the same recovery point into a new, explicitly
confirmed project. Redis 7.4 cannot read Valkey's data files either, so an
older release never starts on a migrated queue volume; the restored project
starts with an empty one.

## Twenty 2.24 to 2.54

Twenty 2.54 closes several security advisories, among them an unauthenticated
invitation takeover in versions up to 2.47. Its upgrade sequence contains
every instance and workspace command since 1.21, so `command:prod upgrade`
migrates a 2.24 database in one step; no intermediate release is needed.
`./leonaid test-upgrade` proves exactly this jump with Golden Data. Twenty
2.54 drops the `isCustom` column of views and now builds indexes and checks
foreign keys of a schema change in background jobs. It refuses further schema
changes until they finish; `tools/twenty/provision.py` waits and repeats the
refused request. The environment variables that LeonAid sets are unchanged.

## RustFS beta.11 to 1.0.4

RustFS 1.0.4 is the first stable release line and fixes the curl, OpenSSL
and Brotli findings of the beta.11 image. It runs on the existing RustFS
volume; no data migration or export is needed. It reads the beta.11 object,
version, bucket and IAM data in place and only adds pool identity, bucket
incarnation and scanner state files under `.rustfs.sys`. The IAM migration in
the 1.0 release notes converts MinIO data (`.minio.sys`) and does not run on a
RustFS volume. The image user (uid 10001), the entrypoint, the `/data` path
and the environment variables that LeonAid sets are unchanged.

`pilot-release` takes the backup, enables maintenance and then recreates
`rustfs` on the new image before Twenty and Core migrate. `./leonaid
test-upgrade` and `./leonaid test-pilot-release` start beta.11 with Golden
Data, hash every object version before and after the image swap and fail if
one key, version, delete marker, ETag, metadata entry or SHA-256 differs. They
check this twice: on the upgraded staging project and on the production
attempt restored from the recovery point.

After 1.0.4 has run on the volume, do not start beta.11 again. Roll back by
restoring the full RustFS volume together with Core PostgreSQL from the
recovery point.
