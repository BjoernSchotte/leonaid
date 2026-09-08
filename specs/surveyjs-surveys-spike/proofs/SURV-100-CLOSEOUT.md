# Functional spike closeout

Date: 2026-09-08. The closeout uses existing test infrastructure and the final
Codex in-app-browser walkthrough. The publication-refresh fix changes only the
two analysis host keys; the existing four complete E2E journeys verify it.
No new dependency, abstraction or product feature was added.

## Accepted scope and explicit deployment deferral

The user agreed to finish the functional spike and move independent physical
source-host-loss recovery and independently retained newest-deletion-cutoff
provenance to deployment-specific acceptance before production use. The original
090.2, 090.2b and 090.T1 obligations are retained as deferred, not checked off as
passed. Their local implementation and local recovery coverage remain required.

The [real cross-revision recovery](SURV-090-CROSS-REVISION.md) proves the exact
preceding/current revisions, encrypted backup, offline missing-checkpoint
rejection, deletion reapplication, denied retrieval and independent cleanup.
Both revisions use installation identity migration 0034. This is not a promise
for arbitrary earlier backups or a substitute for independent host-loss proof.

## Automated evidence

Source checkpoint: `913c2f751136bee433c3f4ef139c6ec628a5da95`.
Tested merge: `8ce63d96f424da32b0ce4e28633611904b8b5cd2`.
The GitHub compare API reports no changed files between those two commits.

- [Main CI](https://github.com/BjoernSchotte/leonaid/actions/runs/34271899823):
  Build, Lint and types, Unit, Contract, Security, Integration, Golden Journey
  and all five E2E groups pass. Optional artifact probe and cold pilot jobs were
  skipped; their separate recorded operator proofs are not new CI results.
- [Dependency/SBOM CI](https://github.com/BjoernSchotte/leonaid/actions/runs/34271899875):
  frozen locks, dependency drift rejection and actual image SBOM generation pass.
- [Generated API client](https://github.com/BjoernSchotte/leonaid/actions/runs/34271899966):
  real-API contract check passes.
- [Survey CI](https://github.com/BjoernSchotte/leonaid/actions/runs/34271899791):
  all eight groups pass. All 39 manifest checks pass twice, yielding 78 zero
  exits. The structured reports were checked for the exact tested commit,
  manifest hash, ordered check IDs, both pass numbers and zero exit codes.
  [Bounded machine-readable review](assets/SURV-100-closeout.json).

The existing scoped regression evidence covers all 42 legacy suite obligations;
the main CI repetition above and the survey aggregate add current integration
coverage. Corrected Caddy image/security/SBOM paths are included. Detailed
operator and both-architecture scanner evidence remains in
[SURV-100-CADDY](SURV-100-CADDY.md), with no new scanner exception.

After the browser found the publication-refresh bug, the corrected working tree
passed `./leonaid test-surveys-e2e`: all four complete author-to-erasure journeys,
exit 0, 515.72 seconds. The new assertion checks Version 1 before reload.
`bun run typecheck:web` and the Docker web build also exit 0. Prettier subsequently
changed test formatting only. [Browser evidence and exact source hashes](assets/SURV-095-in-app-browser.json)
separate this changed-source verification from the preceding full CI checkpoint.
The commit created by this closeout will trigger a fresh CI run; that future run
is not pre-labelled as passing.

## Manual and artifact review

The [in-app walkthrough](SURV-095-IN-APP-BROWSER.md) records actions and outcomes,
including real downloads and a newly rendered five-page PDF. The other browser
and failure matrices retain their automated coverage; they are not all claimed
as manual tests. Its disposable environment exited 0, and ten independent
resource inventories were empty.

Final task reconciliation covers all 104 original IDs: 101 accepted in the
agreed scope and three explicitly deferred deployment obligations. All C-01–C-15
capabilities retain their four-layer fixture evidence. The artifact review found
no private values or invalid local Markdown targets; exact counts are recorded
in the structured closeout review. Eight historical published PDFs remain
byte-identical to their prior parsed review, separate from the newly rendered
five-page synthetic download. Private test credentials, raw logs, Mailpit
links and local screenshots/downloads are not part of the published evidence.

## Production boundary

Do not infer production readiness from the functional spike. Before production,
prove the independent recovery deployment and its freshest authenticated cutoff,
set operational retention and distribution policies, and measure representative
workloads. Package publishing still needs an explicit name, release/versioning
contract and own OSS license. The own license decision remains **UNDEFINED**.

## Acceptance decision

Tasks 100.1, 100.3, 100.3i, 100.4 and 100.T1, criteria 100.A3/100.A5 and
scenarios 100.S1/100.S2/100.S2h/100.S3 are accepted for the agreed functional
scope. Historical isolated cleanup, packed-consumer, dependency/asset and
regression evidence is reconciled with the complete CI checkpoint and targeted
changed-source check above. The original full independent recovery scope remains
unaccepted and must be proved for deployment. No test was marked passed merely
because its scope was deferred.
