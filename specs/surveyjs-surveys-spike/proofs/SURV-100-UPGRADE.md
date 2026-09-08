# SURV-100 — Isolated upgrade and rollback operator regression

The complete existing upgrade regression passes against real services, including
both deliberate failure paths and final cleanup. Together with the
[seed](SURV-100-SEED.md) and [backup](SURV-100-BACKUP.md) runs, this accepts
**100.3l / 100.S2k**, the three named operator suites within 100.A3.
Other regression and delivery requirements remain open.

Command: `sh tools/upgrade/test.sh "$PWD"`, with
`LEONAID_UPGRADE_KEEP=false`. The run exited **0** after **5534.656 seconds**.
Its source checkpoint is `5649ed76ee3f88505567cfc8cedad5a90124d711`;
the [command evidence](assets/SURV-100-upgrade-regression.json) records exact hashes
of the three tested files. The original business sequence is preserved, with
reviewed changes to isolation, backup/maintenance overlay bindings and cleanup.

The exercise verified:

- Real Twenty **2.23.2 → 2.24.0** and RustFS **1.0.0-beta.10 → 1.0.0-beta.11**
  upgrades, immutable release manifest promotion and a 13-event release ledger.
- Encrypted Restic backup, manifest verification, maintenance write rejection
  and stopped writers during maintenance.
- Intentional Core migration failure, detection and restoration of the old
  version; then a second upgrade, intentional corruption of the golden fixture
  across four systems, rejection by the original verifier and another fresh restore.
- Five golden snapshots (before/after upgrade, migration-failure restore,
  second production upgrade and final rollback) have the same SHA-256.
  The deliberately mutated snapshot differs.
- Actual dashboard contracts and SurveyJS validation/aggregation adapters pass
  across upgrade and restore phases. Partial answers are accepted, invalid
  completed answers rejected, and aggregates retain answered/unanswered counts.
- Three dashboard browser checks and nine full journey checks pass: Chromium,
  Firefox and WebKit before upgrade, after upgrade and after final rollback.
  The final three-browser journey completes in **42.7 seconds**.
- The after-upgrade and rollback normalized journey summaries are byte-identical.
  That comparison retains business counts, companies, invoice numbers and PDF
  sizes. Each phase separately verifies stored PDF hashes, byte-identical browser
  downloads and matching email attachments; cross-phase PDF hash equality is
  not asserted.

The [restored administration screenshot](assets/SURV-100-upgrade-restored-admin.png)
was visually inspected. It shows the authenticated dashboard at 90 percent,
12 orders, 34 boxes / 816 items, EUR 720 invoiced and EUR 360 outstanding,
matching the fixture after its first journey round.

Source and rollback projects use unique checksum/PID identities, unused reserved
networks, no published host ports and separate restore-state files per generation.
Only one full owned stack runs at a time. The rollback overlay now connects the
validator to the API network, and the real adapter probe verifies reachability.
Preflight rejects occupied identities; cleanup failures propagate. Both the
controller and a second independent inspection confirm zero owned containers,
volumes and networks for both projects.

Shell syntax, Ruff and the complete configured Mypy scope pass (278 Python
source files). No existing business assertion, browser budget or baseline was
relaxed. The survey recovery fixture has an empty erasure ledger: this does not
accept SURV-090 independent host-loss, nonempty erasure or latest-cutoff recovery.
