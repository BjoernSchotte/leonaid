---
title: Upgrade and roll back
description: Update pinned Core, Twenty, and RustFS versions behind a maintenance boundary with a tested recovery path.
docId: DOC-P024
audience: [ops]
diataxis: how-to
contentRevision: 5
reviewedRevision: 5
verifiedAgainst: 2fe1a1b7930207925afe13bab77da89d37111c56
reviewer: Björn Schotte
---

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
