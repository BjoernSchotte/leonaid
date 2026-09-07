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
restore still requires a fresh target; the standalone reapply command can retry
cleanup on the quarantined target with its exact environment and all writers off.

A legacy database with no survey tables skips this module-specific gate only
when neither input is supplied. A database with survey tables but no stable
identity does not bypass it; preceding survey-schema backups remain unsupported.
Empty survey tables still require a checkpoint: later deletions may have left
records that prevent recreation even when no response needs immediate erasure.

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

- Exercise the separate pilot Doctor/release-manifest wrapper with survey
  recovery inputs; the generic no-build restore path is proven above.
- Couple accepted deletion requests to independent durable retention, including
  requests after the most recent publication and unexpected source-host loss. The
  filesystem publisher and source-project-loss restore prove the archive primitive;
  a manually invoked publisher does not yet establish continuous coverage.
- Define and prove how the operator obtains the required cutoff and detects a
  missing latest checkpoint. Authentication proves provenance and integrity,
  not that the supplied file is the newest file ever exported.
- Prove interrupted reapplication, key/identity errors through that wrapper and
  migration compatibility with supported preceding backup revisions.

Until these items pass, 090.2 and 090.A3 remain open. The automatic gate and its
tests must not be presented as completed production disaster recovery.
