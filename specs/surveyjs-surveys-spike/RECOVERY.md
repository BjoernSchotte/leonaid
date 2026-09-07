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

## Remaining integration before acceptance

- Wire the primitive into the existing Restic-backed restore operator before its
  application-start step, with fail-closed missing/stale checkpoint handling.
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

Until these items pass, 090.2 and 090.A3 remain open. The generic restore command
has not yet gained an automatic survey-erasure gate; the primitive and its tests
must not be presented as completed production disaster recovery.
