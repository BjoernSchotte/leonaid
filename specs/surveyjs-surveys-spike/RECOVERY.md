# Survey erasure recovery contract

Status: **partial implementation; not an accepted operator workflow**. Own license:
**UNDEFINED**. See [SURV-090 evidence](proofs/SURV-090.md).

A database backup can predate a survey's deletion. Restoring the database and
object storage therefore requires a newer, independently retained erasure
checkpoint before application writers or public access resume. An old backup's
own erasure table is insufficient for deletions that happened after that backup.

## Implemented primitive

`tools/surveys/recovery.py` provides two offline operator primitives using the
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

## Remaining integration before acceptance

- Prove the complete Restic-backed operator invocation, including its
  application-start step and no-build release-image path, beyond the shared-gate
  integration test.
- Retain current checkpoints independently of the source database and its old
  recovery point, with a demonstrated source-loss recovery procedure. A local
  export alone does not provide that continuity.
- Define and prove how the operator obtains the required cutoff and detects a
  missing latest checkpoint. Authentication proves provenance and integrity,
  not that the supplied file is the newest file ever exported.
- Exercise the existing backup rotation, manifest validation and fresh-target
  restore path together with survey erasure. The current isolated survey proof
  restores actual PostgreSQL/RustFS data but does not replace those operator tests.
- Prove interrupted reapplication, key/identity errors through that wrapper and
  migration compatibility with supported preceding backup revisions.

Until these items pass, 090.2 and 090.A3 remain open. The automatic gate and its
tests must not be presented as completed production disaster recovery.
