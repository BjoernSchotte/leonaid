# SURV-100 — Isolated backup operator regression

The complete existing backup regression passes against real services and a fresh
restore target. This delivers the backup portion of **100.3l / 100.S2k**. Together
with the [seed evidence](SURV-100-SEED.md), two of the three required operator
suites now pass; upgrade/rollback and the combined task remain open.

Command: `sh tools/backup/test.sh "$PWD"`, with `LEONAID_BACKUP_KEEP=false`. The
run exited **0** after **1629.297 seconds**. Its recorded source checkpoint is
`631a8c3f0d436d2b2a2b3b53224c0845fa5c1072`; the tested isolation harness is
identified by its exact hash in the [command evidence](assets/SURV-100-backup-regression.json).
The original data, credential-rejection, browser and timing assertions are
preserved. Changes concern project ownership, private operator files, network
overlays and cleanup.

The exercise verified:

- An encrypted Restic backup with manifest validation. A wrong password fails;
  the repository contains no occurrence of the seeded plaintext marker.
- Production backup policy rejects a local repository, and an incorrect restore
  confirmation is rejected. The synthetic exercise explicitly permits its own
  private local repository.
- Source containers, volumes and networks are removed before reserving the
  restore target's networks. Restoration creates fresh target volumes.
- Before/after inventories compare equal: **60 Core tables, 99 Twenty tables,
  three RustFS objects**, and Twenty's retained storage. The existing inventory
  comparison covers relational content and object bytes, including PDF hashes,
  sessions, audit and outbox data.
- The restored golden snapshot passes the existing verifier. One actual Chromium
  journey passes in **3.0 seconds** using an existing session, with the expected
  dashboard values, no page errors and no serious or critical Axe violations.
- The existing timing checks pass: the harness reports **286 seconds RPO** and
  **597 seconds RTO**, below its 24-hour and two-hour limits. These are measurements
  of this synthetic exercise.

The [restored administration screenshot](assets/SURV-100-backup-restored-admin.png)
was visually inspected: the authenticated dashboard shows the expected 90 percent
goal, 25 boxes / 600 items and EUR 504 invoiced. It is execution evidence, not a
replacement screenshot baseline.

Both projects receive unique checksum/PID names, reserve unused networks and
publish no host ports. The harness checks source and target identities before
mutation, gives the restore its own state file, propagates cleanup errors and
verifies all three resource inventories. A separate post-run check confirms zero
owned containers, volumes and networks for both projects. Other worktrees are
outside the cleanup scope.

The survey recovery fixture here has an empty erasure ledger. This evidence does
not accept the nonempty erasure, independent source-host-loss or latest-checkpoint
requirements under SURV-090. The dedicated proofs and remaining recovery tasks
retain that scope. No implementation-task checkbox is changed by this delivery.
