# Survey erasure recovery contract

Status: **partial implementation; not an accepted operator workflow**. Own license:
**UNDEFINED**. See [SURV-090 evidence](proofs/SURV-090.md).

A database backup can predate a survey's deletion. Restoring the database and
object storage therefore requires a newer, independently retained erasure
checkpoint before application writers or public access resume. An old backup's
own erasure table is insufficient for deletions that happened after that backup.

## Implemented primitive

`tools/surveys/recovery.py` provides export/reapply operator primitives using the
configured Core database, object storage and session-encryption secret:

```sh
python tools/surveys/recovery.py export --output /recovery/erasure-checkpoint.json
python tools/surveys/recovery.py reapply \
  --checkpoint /recovery/erasure-checkpoint.json \
  --required-through 2026-09-07T12:00:00+00:00
```

The timestamp is an illustrative explicit operator input, not a fixed default.
The caller must choose the cutoff from independently established recovery state;
copying a timestamp from an arbitrary old checkpoint does not prove freshness.
No environment secret belongs in command arguments, logs or retained proof files.

Export takes a short transaction advisory lock also used when committing new
manual or retention erasure requests. It reads all retained deletion records and
records the cutoff while that lock is held. Atomic file replacement, mode 600 and
file/directory fsync prevent a successful command from leaving a partial file.

The JSON envelope contains a strict versioned checkpoint and an HMAC-SHA256.
Its authentication key is derived with a survey-recovery-specific context from
the existing external session-encryption secret. The checkpoint contains the
stable installation UUID, export timestamp and only these record fields:

- Survey, requesting actor and original event UUIDs.
- Hash of the operation identifier and expected revision.
- Original request timestamp.

It contains no survey title, definition, answer, recipient, credential, export
bytes or plaintext operation ID. Completion timestamps are deliberately omitted:
a completed source deletion must still run again against older restored data.

Reapplication authenticates the envelope, matches the restored installation,
requires coverage of the supplied cutoff, rejects future/naive timestamps and
refuses checkpoints that omit or alter deletion records already in the database.
Input reads and verification are bounded at 32 MiB. This is the current supported
checkpoint size; larger installations need a separately tested streaming format.

All revocations are committed before object erasure starts. The existing eraser
then removes exact export versions and relational content. Failure leaves
retryable records and returns a nonzero generic diagnostic. Reapplication is
repeatable, including when a prior run already finished. Application services
must remain stopped until the entire command succeeds.

The stable identity starts with migration 0034. Compatibility with backups from
before that identity existed is not yet implemented; do not silently assign a
new identity or bypass an identity mismatch. Key rotation must preserve a
matching verified checkpoint and the external key needed to authenticate it.

## Independently retained filesystem archive

The `publish` and `fetch` commands add a POSIX filesystem archive. Provision an
existing private directory on storage retained independently of the source database
and object volumes. The filesystem must honor `flock`, atomic rename and file and
directory `fsync`. The command does not create a missing archive directory; directory
existence alone is not proof that an intended external mount is present. Mount
verification and keeping that storage outside the source host's failure domain remain
operator deployment responsibilities.

```sh
python tools/surveys/recovery.py publish --archive /recovery/survey-erasure
python tools/surveys/recovery.py fetch \
  --archive /recovery/survey-erasure \
  --installation-id "$SURVEY_RECOVERY_INSTALLATION_ID" \
  --required-through "$LEONAID_SURVEY_ERASURE_REQUIRED_THROUGH" \
  --output /recovery/verified-erasure.json
```

The installation UUID is recorded independently when the installation is provisioned;
the required-through value remains the independently established recovery cutoff.
`fetch` needs the archive and authentication secret, but no database connection or
network. Use its output as `LEONAID_SURVEY_ERASURE_CHECKPOINT` for the existing restore
gate, and continue only after exit zero. Failure preserves an existing output file;
that old file must not be mistaken for a successful new fetch.

Publication serializes readers/writers and verifies both current and pending states.
It rejects changed or omitted known erasures, a backwards cutoff, conflicting data
at an equal cutoff and another installation or key. It durably writes, in order:

1. `pending.json`, the complete authenticated candidate.
2. A retained document named by its SHA-256 digest.
3. `current.json`, the complete authenticated current checkpoint.
4. Removal of `pending.json`, followed by directory fsync.

All written files use mode 600. A pending document blocks fetch even when the new
current file already exists. After an interrupted publisher, a successful retry must
retain every erasure in both previous and pending states. A missing current file in
an archive with retained history cannot silently initialize a new, older history.
Corruption/authentication failures block publication and retrieval; never clear an
incomplete or damaged archive merely to make a restore proceed.

Each document retains the existing 32 MiB bound. Historical documents are retained;
this primitive supplies no pruning or periodic scheduler. Archive-wide rollback by
a storage administrator is outside its integrity model: the independent required
cutoff is still necessary, and authentication does not establish absolute freshness.

The `archive` mode of `tools/surveys/restic_recovery.sh` exercises actual PostgreSQL
publication into a separate named volume, abrupt publisher exits, stale-cutoff
rejection, removal of all source-project containers/volumes and network-disabled
fetch followed by the real Restic restore. This models source-project loss on one
Docker host; it does not prove loss of that host or cover erasures accepted after
the last published cutoff. See the linked SURV-090 evidence for accepted scope.

## Automatic acknowledgement and cleanup gate

The API composition root and production outbox worker use an authenticated archive
publisher configured through `LEONAID_SURVEY_ERASURE_ARCHIVE_DIR`. The directory must
be absolute and already exist. Compose mounts `survey-erasure-archive` at
`/recovery/survey-erasure` for both services. The default project-local volume supports
development only: deployments must override it with separately retained storage and
verify the actual mount before claiming independence from the source host.

A permanent-deletion request first commits the content-free ledger and outbox identity.
Before returning success, the API publishes the complete committed ledger. Archive
failure returns HTTP 503 with the stable `survey_erasure_archive_unavailable` code;
the committed intent remains and blocks restoration/recreation. Retrying the exact
operation ID and revision resumes the acknowledgement without creating another event.
Deletion-status reads also require a successful archive check. Authorization and
operation-conflict checks precede publication.

The production eraser independently checks publication before removing object or
database content, including when the API previously acknowledged the request. The
retention sweep publishes after committing its batch and before reporting success;
subsequent sweeps also cover locally committed intents left by a previous failure.
Configured API startup checks the ledger before readiness. Offline authenticated
checkpoint reapplication deliberately uses the eraser without this publisher: the
restore gate has already verified the external checkpoint and must work offline.

Publication holds the erasure advisory transaction lock through snapshot creation
and archive I/O, before the worker acquires survey cleanup locks. Concurrent database
publishers therefore cannot write an older snapshot after a newer one. Filesystem
publication runs outside the asynchronous event loop. Missing configuration fails
closed for production deletion; optional low-level adapter injection is reserved for
offline recovery and controlled fixtures.

An unchanged ledger verifies the current authenticated checkpoint and its retained
bytes without generating another historical file. A pending publication is completed
on retry. This avoids growth on every five-second retention sweep or status request.
It does **not** advance the checkpoint's recovery cutoff: an explicit `publish` remains
available when the operator needs a newly established cutoff. Continuous host-loss
cutoff provenance is still a separate acceptance requirement below.

## Restore operator gate

`tools/backup/restore.sh` invokes `tools/backup/survey-erasure-gate.sh` after
both database restores and before application startup. Each `pg_restore` aborts
on errors. For a database containing the survey schema, supply both external
environment inputs (also inherited by `./leonaid pilot-restore`):

```sh
export LEONAID_SURVEY_ERASURE_CHECKPOINT=/recovery/erasure-checkpoint.json
export LEONAID_SURVEY_ERASURE_REQUIRED_THROUGH=2026-09-07T12:00:00+00:00
```

These are illustrative values. The cutoff must be independently established as
described above. The checkpoint is mounted read-only into a one-off API image;
the command does not start dependencies or application writers. Development
restores build that image; `LEONAID_RESTORE_NO_BUILD=true` uses the configured
image and only pulls it if missing. An incompatible image fails closed.

The gate also runs with `LEONAID_RESTORE_START_APP=false`. Missing input,
authentication/identity/freshness errors or failed cleanup return nonzero while
the restored database and storage remain available for offline investigation.
Do not manually start application services after such failure. A new complete
restore still requires a fresh target. The quarantined target can instead resume
through the authenticated operator path described below.

A legacy database with no survey tables skips this module-specific gate only
when neither input is supplied. A database with survey tables but no stable
identity does not bypass it; preceding survey-schema backups remain unsupported.
Empty survey tables still require a checkpoint: later deletions may have left
records that prevent recreation even when no response needs immediate erasure.

## Resuming a quarantined pilot restore

After both databases and storage have been imported, the restore records a private,
authenticated receipt beside the target environment file as
`<target-env-file>.restore-state.json`. Keep that receipt with the exact target
configuration and confirmed backup manifest. It contains hashes and resource/phase
metadata, never answers or credentials. The authentication key derives from the
existing session-encryption secret with a restore-specific context. Atomic replacement
and file/directory fsync protect receipt writes.

For a failed or interrupted erasure gate, rerun the original `./leonaid pilot-restore`
command with the same arguments and add `--resume`. Supply a valid checkpoint and
the same or a later independently established required-through cutoff. Resume checks
the receipt before touching restored data and reruns the complete erasure gate;
it does not download the backup again or reimport database/storage contents.
`LEONAID_RESTORE_START_APP=false` completes verification while leaving application
services stopped; a subsequent verified resume may start them.

Resume requires all of the following:

- The receipt authenticates against the unchanged target configuration, source and
  target project names, repository and confirmed manifest. A normal fresh restore
  also verifies that the actual Restic manifest matches the manifest supplied to
  the pilot command before creating target volumes.
- All four restored data volumes retain their recorded name, creation time, driver
  and project ownership. Only Core PostgreSQL, Twenty PostgreSQL and RustFS
  containers may exist for the target, including stopped containers.
- The recorded phase is `restored` or `verified`. Before starting any application,
  the command durably changes it to `starting`; successful startup records `complete`.
  Neither of these latter phases can resume through this path.
- The required-through cutoff cannot precede or remove the receipt's recorded
  cutoff. Checkpoint signature, installation identity, freshness and complete
  erasure coverage are still checked by the erasure gate.

An advisory lock in the operator temporary directory serializes the entire restore
command per target name, including invocations from different worktrees using that
same directory. Keep the operator account and temporary-directory configuration
consistent. This is not a distributed lock for different hosts/accounts or temporary
directories controlling one Docker daemon. Use `restore.sh` or the
pilot CLI entry point; `restore-body.sh` is its internal locked implementation.

An interruption before completed data imports and receipt creation requires a fresh
target. An interruption after application startup begins, a changed configuration,
a missing/modified receipt or replaced volumes requires investigation and a fresh
restore; do not edit the receipt or remove application containers to bypass this
boundary. A receipt proves this workflow's identity and phase, not the integrity of
arbitrary administrator changes to database contents or the newest recovery cutoff.

## Proven complete generic restore invocation

`tools/surveys/restic_recovery.sh` runs the existing encrypted backup command,
its rotation policy and `check --read-data`, then deletes a survey and explicitly
exports its newer checkpoint. It removes all source-project containers and
volumes before running the actual fresh-target restore command twice: first
without a checkpoint (blocked, restored data inspected offline), then after
removing those target volumes with a valid checkpoint (full application startup).

The successful target runs with `LEONAID_RESTORE_NO_BUILD=true`. All six built
services use the exact source image IDs, checked against running containers.
Relational content and the original exact object version are absent; old session
and public access are denied; a Chromium foundation journey passes. Both projects
publish no host ports and their containers/volumes are removed and checked.
See [the complete run evidence](proofs/SURV-090.md#full-restic-backup-and-fresh-target-restore).

This proves the generic command, not the separate pilot Doctor/release-manifest
wrapper. Local encrypted Restic storage and an explicitly exported file model
independent recovery material; loss of that entire host and automatic retention
of the newest checkpoint are not established by this test.

## Remaining integration before acceptance

The pilot Doctor treats `pilot-restore` as an offline preflight. It checks the
environment, immutable Compose image inventory, source-project/backup metadata,
backup age, local disk and required decision register. It does not require the
lost source installation's DNS, TLS, API, CRM or mail endpoints to respond. JSON
reports mark these live checks `not_checked_restore`; successful preflight does
not assert target readiness or authenticate the actual backup/checkpoint bytes.
Other deployment gates still perform their live probes. The restore operator must
still validate and restore the actual backup, apply the survey erasure gate and
prove target readiness before admitting access.

The pilot overlay now binds `survey-validator` through the required
`LEONAID_SURVEY_VALIDATOR_IMAGE`, disables target-side builds and includes it in
the release manifest. Missing, mutable or changed validator images fail the
applicable configuration/manifest check. Older image inventories need an explicit
compatible release checkout; do not remove the validator from a current manifest
to force a restore through validation.

- The complete pilot deploy/release/backup/restore regression passes with the
  validator and an authenticated empty checkpoint
  ([baseline evidence](proofs/SURV-100.md#isolated-pilot-operator-regression)).
  The subsequent [nonempty pilot proof](proofs/SURV-090.md#pilot-restore-with-post-backup-survey-erasure)
  backs up an actual answer and export, deletes them, removes source containers
  and volumes, and restores through `pilot-restore`. Five fresh targets reject
  missing, modified, wrong-key, wrong-installation and stale checkpoints while
  the exact restored answer/object remain offline. The valid checkpoint erases
  those records and the exact object version before no-build startup. Its
  checkpoint and cutoff are explicitly retained; this does not establish
  automatic newest-checkpoint provenance across unexpected host loss.
- Prove unexpected source-host loss. Retention-originated interrupted publication
  and recovery by a zero-candidate sweep now have
  [live evidence](proofs/SURV-090.md#retention-publication-interruption-and-recovery).
  Manual acknowledgement and production worker archive gates also have
  [live evidence](proofs/SURV-090.md#automatic-archive-acknowledgement-and-worker-gate),
  including real Restic recovery using only automatically retained material after
  source-project removal. Independently placed storage and complete host-loss
  coverage remain deployment/recovery acceptance requirements.
- Define and prove how the operator obtains the required cutoff and detects a
  missing latest checkpoint. Authentication proves provenance and integrity,
  not that the supplied file is the newest file ever exported.
- Interrupted reapplication through the wrapper has
  [live evidence](proofs/SURV-090.md#interrupted-pilot-reapplication-and-authenticated-resume).
  The [cross-revision Restic proof](proofs/SURV-090-CROSS-REVISION.md) restores an
  actual backup from `875221c` with current `cf20bec` images, reapplies its
  post-backup erasure and proves inaccessible content after startup. Both
  revisions use migration 0034; this does not prove older-schema migrations.
  Prove remaining migration compatibility with supported preceding backup revisions. Key/identity and
  stale/tampered/missing-input rejections are covered by the nonempty pilot proof.

Until these items pass, 090.2 and 090.A3 remain open. The automatic gate and its
tests must not be presented as completed production disaster recovery.
