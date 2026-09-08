# SURV-100 — Strict cleanup across all Restic recovery modes

All three complete Restic modes pass with the updated cleanup implementation.
This closes the identified Restic cleanup defect and supplies a scoped contribution
to **100.S1 / 100.1**. It does not accept the repeated aggregate, other harnesses,
SURV-090 independent host-loss recovery or the complete spike.

| Command | Exit | Duration |
| --- | --- | --- |
| `sh tools/surveys/restic_recovery.sh "$PWD" manual` | 0 | 1782.298 s |
| `sh tools/surveys/restic_recovery.sh "$PWD" archive` | 0 | 2005.203 s |
| `sh tools/surveys/restic_recovery.sh "$PWD" durable` | 0 | 1869.274 s |

The [reviewed command evidence](assets/SURV-100-restic-cleanup.json) records each
source checkpoint, exact tested file hashes and captured assertions. All modes
used the same harness, restore operator and recovery probe bytes. The manual run
started at `fb9ac9d`; archive and durable started at `8a9e107`.

Cleanup now propagates teardown and inventory-read errors. It verifies both
projects' containers, volumes and networks, and separately verifies removal of
the retained archive volume. Preflight rejects occupied project resources and
unreadable inventories before taking ownership. The existing recovery business
sequence is unchanged apart from three stronger resource-absence checks.

Each complete run creates a real response and export, makes an encrypted Restic
backup and reads all data for integrity verification. After a post-backup erasure,
it removes the source project and restores onto fresh target volumes. Missing
checkpoint input blocks application startup; a separate probe confirms the old
SQL answer and exact export object are actually restored while writers remain
offline. A new restore with the valid checkpoint reapplies the erasure, starts
the application without rebuilding its service images, and rejects old-session
and public access to the erased survey/export. Each mode also passes its actual
Chromium foundation check and preserves every built service image identity.

Archive mode additionally rejects stale input and abrupt publication exits at
both `after-pending` and `after-current`, then fetches the authenticated checkpoint
after source-project removal. Durable mode verifies API acknowledgement and
production-worker behavior through archive outages, exact retry/outbox identity,
and recovery using automatically published material without a separate manual
post-deletion export. An unchanged ledger creates no new archive version.

The harness and its controller both verify successful resource removal. A second
inspection after all three terminal results independently checks 21 inventories:
containers, volumes and networks for each of six projects, plus each run's archive
volume name. All are empty. Runs use unique owned project identities, independently
reserved unused subnets and no published host ports; foreign stacks are untouched.

A separate real-Docker failure probe executes the same cleanup function with its
archive volume held by a container. Cleanup exits 1 and the volume remains; after
releasing that container, the same cleanup exits 0 and the volume is absent.
This demonstrates failure propagation, not only successful teardown. Shell syntax
validation also passes. Raw runtime logs and credentials are not published.

These tests model source-project loss on one Docker host. They do not establish
physical source-host loss, independently trustworthy newest-cutoff provenance or
the remaining preceding-backup compatibility contract. The existing **100.A1**
CI repetition remains valid at its recorded revision; **100.S1** stays open until
the final cross-harness cleanup and repeated aggregate are reconciled.
