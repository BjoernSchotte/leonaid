# Cross-revision encrypted backup and restore

The real local run creates the backup with source revision
`875221c1054314e83a1737e0384ee2dbad3fd398` and restores it with
`cf20bec5faeb49c11a7f6f78fde54c9bd28dc061`. The historical source is a separate
967-file Git archive. Current target images are built separately and pinned by
their actual image IDs; the target does not reuse source application images.

## Observed result

The complete process exits **0** after **1,954.151 seconds**:

1. The old application creates a real answer and a stored export. Its backup
   command creates an encrypted Restic snapshot and reads all data during the
   integrity check: one snapshot, two packs, no errors.
2. The old application deletes the survey and exact export version after the
   backup. Its recovery command exports the newer authenticated checkpoint.
3. Source containers, volumes and networks are removed. A separate Docker
   inventory confirms all three are absent before target restoration.
4. Current restore tools recover the old database and object files. A missing
   checkpoint blocks application startup. The probe confirms the original SQL
   answer and exact object are present offline, so an early unrelated failure
   cannot satisfy this rejection case.
5. A fresh target restores the same backup with the valid historical checkpoint.
   The current recovery command reapplies one erasure before starting services.
   Actual SQL and object checks confirm the erased content is absent. The old
   authenticated session, public route and export download cannot retrieve it.
6. All seven built target service image IDs match the separately built current
   images. The foundation Chromium test passes. Final independent inventories
   find no source/target containers, volumes, networks or project image tags:
   **20 empty inventories**. All 845 captured current runtime/harness inputs
   remain unchanged throughout the run.

No host ports are published by the source fixture; this was additionally checked
against all 14 containers present during startup. Both Compose projects use
explicit unused network ranges. Only synthetic test data is used.

## Acceptance boundary

This proves the exact preceding source revision and current restore revision
above. Both use the recovery-identity schema introduced by migration 0034; it
does not establish compatibility with arbitrary older schemas or make
pre-identity survey backups supported. No separate claim about preserving
unrelated application records is inferred from the survey erasure assertions.

The checkpoint and required cutoff were explicitly retained before removing the
source project. Physical source-host loss, independent newest-cutoff provenance
and detection of a missing latest checkpoint remain open. Consequently this
proof does not close 090.2, 090.2b, 090.T1 or full disaster-recovery acceptance.

[Structured results](assets/SURV-090-cross-revision.json) bind the exact revisions,
input hashes and target image identities to this run.

The [exact tested harness](assets/SURV-090-cross-revision.sh) is retained as a
historical proof artifact, not a general compatibility promise. It takes the
current checkout and separate historical checkout as its two arguments; both
need private test environment files. It disables host ports and uses separately
owned source/target projects. Its revision labels describe this recorded run
and must not be reused to claim evidence for another checkout.
