# Backup, restore and disaster recovery

Current bilingual task guide:
[Deutsch](../../apps/docs/src/content/docs/de/ops/how-to/backup-and-restore.md) ·
[English](../../apps/docs/src/content/docs/en/ops/how-to/backup-and-restore.md).
This file remains the detailed recovery contract.

This runbook is the operational contract for the LeonAid PoC. It covers the
core PostgreSQL database, the Twenty PostgreSQL database, Twenty local files
and the complete RustFS data volume. Restic encrypts every recovery point
before transport. The target must be outside the LeonAid VPS.

Not backed up: Twenty's Valkey store (service `twenty-redis`, a rebuildable
cache/queue), Mailpit (local test system), container images and plaintext
secrets.

## Targets and retention

| Metric                                     |           PoC target |
| ------------------------------------------ | -------------------: |
| RPO                                        |     at most 24 hours |
| RTO to verified member interface           |      at most 2 hours |
| Daily recovery points                      |                    7 |
| Weekly recovery points                     |                    5 |
| Monthly recovery points                    |                   12 |
| Yearly recovery points                     |                    3 |

`backup.sh` applies this rotation after every successful backup and then runs
`restic check --read-data`. Production schedules the command at least daily
and alerts when it is missing or fails. A complete fresh-volume restore is
repeated at least quarterly and before schema-changing upgrades.

## Prerequisites and separate secrets

Required:

- a restic target independent of LeonAid, for example S3-compatible object
  storage or SFTP on another host;
- a local file with a random restic password, mode `600`;
- optionally a `KEY=VALUE` file, mode `600`, with the credentials of the
  remote backend;
- the normal, unversioned `.env.local`;
- the separately managed Twenty integration key.

The restic password, remote access, `.env.local` and the Twenty key must be in
neither the backup repository nor the Git repository. They belong in the
secret manager and its independent emergency copy.

Local paths are rejected outright for production backups. Only the isolated
project prefix `leonaid-poc112-*` can model the external storage in the
recovery test with `LEONAID_BACKUP_ALLOW_LOCAL_TEST=true`.

## Run a backup

A pilot installation uses only the manifest-bound operator command. It runs
the full pilot doctor before and after the backup and replaces the
configured doctor manifest only after a successful restic data check:

```sh
./leonaid pilot-backup \
  --env-file /etc/leonaid/production.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --password-file /secure/leonaid/restic-password \
  --credentials-file /secure/leonaid/restic-backend.env
```

The manifest path must match `LEONAID_BACKUP_MANIFEST_PATH` from the
environment file exactly.

The following generic command remains for local PoC development:

```sh
export LEONAID_COMPOSE_PROJECT=leonaid
export LEONAID_BACKUP_REPOSITORY='s3:s3.eu-central-1.example.invalid/leonaid'
export LEONAID_BACKUP_PASSWORD_FILE='/secure/leonaid/restic-password'
export LEONAID_BACKUP_CREDENTIALS_FILE='/secure/leonaid/restic-backend.env'
./leonaid backup
```

The command:

1. validates project, external target and password file;
2. briefly stops proxy, APIs, worker, frontends and Twenty writers;
3. creates custom-format dumps of both running PostgreSQL instances;
4. archives Twenty files and the RustFS volume in the same recovery point;
5. writes manifest, sizes and SHA-256 checksums;
6. encrypts and transfers with the pinned restic image;
7. rotates, checks all stored bytes and starts the writers again.

The short write stop is the PoC consistency boundary between LeonAid, Twenty
and RustFS. A failed backup also restarts the stopped services through the
exit trap.

## Restore into a fresh environment

The restore never overwrites an existing Compose environment. Target names
must match `leonaid-restore-<name>`, must not own any containers or volumes
and require an exact confirmation.

The pilot restore uses a separate target environment with the same external
repository and only already approved images. Nothing is built on the target:

```sh
./leonaid pilot-restore \
  --env-file /etc/leonaid/production.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --target-env-file /etc/leonaid/restore-drill-2026-07.env \
  --password-file /secure/leonaid/restic-password \
  --credentials-file /secure/leonaid/restic-backend.env \
  --confirm RESTORE:leonaid-restore-drill-2026-07
```

The following generic restore remains for local PoC development:

```sh
export LEONAID_BACKUP_SOURCE_PROJECT=leonaid
export LEONAID_RESTORE_PROJECT=leonaid-restore-drill-2026-07
export LEONAID_RESTORE_CONFIRM='RESTORE:leonaid-restore-drill-2026-07'
export LEONAID_BACKUP_REPOSITORY='s3:s3.eu-central-1.example.invalid/leonaid'
export LEONAID_BACKUP_PASSWORD_FILE='/secure/leonaid/restic-password'
export LEONAID_BACKUP_CREDENTIALS_FILE='/secure/leonaid/restic-backend.env'
./leonaid restore
```

The command checks restic and manifest checksums, builds fresh volumes,
restores Twenty/RustFS, starts fresh PostgreSQL containers, loads both dumps
with abort on error and then starts the complete core stack.

If the restored database contains the survey module,
`LEONAID_SURVEY_ERASURE_CHECKPOINT` must also point, before the restore, to an
independently stored, authenticated erasure directory.
`LEONAID_SURVEY_ERASURE_REQUIRED_THROUGH` gives the independently determined
required freshness point as an ISO 8601 time with time zone. Both variables
also apply to `pilot-restore`. An old directory from the restored backup is
not enough for later erasures.

The restore re-applies the erasures before the application starts. Missing,
invalid or outdated evidence and failed erasures abort the restore; the
application services stay stopped. This also applies with
`LEONAID_RESTORE_START_APP=false`. After a failure, they must not be started
manually before the check has been repeated successfully.
The [recovery contract](../../specs/surveyjs-surveys-spike/RECOVERY.md)
describes the inputs, repetition and still open evidence for independent
storage, older survey schemas and the complete operator path.

## Full recovery

1. Provide a replacement host with Docker/Compose, this verified commit and
   the pinned images.
2. Load `.env.local`, restic access and the Twenty integration key from the
   separate secret manager. Do not create new LeonAid encryption keys;
   otherwise existing sessions or protected data become unreadable.
3. Run the restore with a new, exactly confirmed target name.
4. Check `./leonaid doctor` and `docker compose ps`.
5. Internally, check `/_health`, `/health/ready`, Twenty `/healthz` and
   RustFS `/health` first.
6. Check the data inventory, golden smoke test and invoice PDF SHAs; then
   check sign-in, action, order, document download and CRM link with test
   accounts.
7. Only then switch DNS to the replacement IP, check TLS/proxy from outside
   and enable writes. A low DNS TTL is set before planned drills; the actual
   switchover time is recorded in the incident.
8. Keep the old host isolated, protect the recovery point and logs against
   deletion and document the cause.

The automated evidence is:

```sh
./leonaid test-backup
```

It starts with fresh systems, deletes the source after the encrypted backup
and compares the restore logically and byte for byte. The local repository in
the test is explicitly only an isolated model; each operator must also prove
the physical off-VPS location through their remote configuration and
infrastructure.

The pilot gate combines this full restore with a real network-bound S3
backend:

```sh
./leonaid test-pilot-backup
./leonaid test-pilot-deployment
```

The additional isolated RustFS has its own network, volume and rotatable S3
credentials. Restic initializes a real S3 repository there, reads all
encrypted data for the integrity check and restores it into a fresh target.
Wrong password, a real network interruption, an incomplete latest snapshot
and the rotation of the S3 credentials are checked fail-closed. This
technical remote contract does not replace the still outstanding operator
evidence that the selected production repository is physically outside the
pilot VPS.

`test-pilot-deployment` also proves the complete operator path: doctor,
backup, freshly published manifest and build-free restore into an independent
pilot target. Unique probe data is found again byte for byte in both
PostgreSQL databases and in both file volumes. The test removes the source,
target and backup projects including networks and volumes, also on failure.

<a id="schemaändernde-migrationen"></a>

## Schema-changing migrations

Schema-changing migrations may run only on disposable PoC databases or after
a successful `./leonaid backup`. Before the production migration, the
recovery point is checked with `restic check --read-data` and restored at
least into a fresh staging environment.

Every destructive forward migration references this section and also
describes its concrete data transfer in the module. The CI migration test
still proves both the build from empty and the upgrade of a versioned
predecessor snapshot.
