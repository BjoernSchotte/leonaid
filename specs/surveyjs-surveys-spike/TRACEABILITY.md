# Task and capability traceability

**100.A4 is accepted** at source checkpoint `b450783`, with the explicit open
obligations below. The [104-task inventory](proofs/assets/SURV-100-task-traceability.json)
contains 95 accepted tasks with scoped evidence and 9 open tasks after the
[operator](proofs/SURV-100-UPGRADE.md) and
[privacy/testkit/Golden Journey](proofs/SURV-100-PRIVACY-TESTKIT-GOLDEN.md) follow-ups. The original review
introduced follow-ups 100.3i, 100.3k and 100.3l; 100.3k and 100.3l are now accepted.
It does not accept the whole spike or uncommitted implementation changes.

## Remaining obligations

- **090.2:** Independent host-loss cutoff provenance and preceding-backup compatibility remain unproven.
- **090.2b:** An independently retained current cutoff must survive unexpected source-host loss; primitive and source-project-loss proofs are insufficient.
- **090.T1:** Requires the still-open full 090.A3 recovery criterion.
- **100.1:** 100.A1 is accepted by the complete two-pass CI at e030836. Final cross-harness cleanup reconciliation, affected regressions and delivery gates remain incomplete.
- **100.3:** Remaining existing regressions and final packed/delivery review remain incomplete.
- **100.3i:** Corrected source-built Caddy images passed bounded candidate checks; application/CI, release/restore and SBOM integration remain open. No VEX exception is approved or delivered.
- **100.3m:** Feature flags readiness, UI screenshot mismatch and UX heading/performance failures need diagnosis and complete successful reruns.
- **100.4:** Task/capability reconciliation is accepted; final delivery review and outcome report remain open.
- **100.T1:** 100.A1 and 100.A4 are accepted. Final cross-harness cleanup, existing regressions, delivery review and independent-host recovery prerequisites remain incomplete.

## Accepted task evidence

| Task | Recorded proof |
| --- | --- |
| 000.1 | [evidence](proofs/SURV-000-CONTRACT-REVIEW.md) |
| 000.2 | [evidence](proofs/SURV-000-CONTRACT-REVIEW.md) |
| 000.3 | [evidence](proofs/SURV-000-CONTRACT-REVIEW.md), [evidence](proofs/SURV-000.md#complete-runtime-dependency-disposition) |
| 000.4 | [evidence](proofs/SURV-000-CONTRACT-REVIEW.md), [evidence](proofs/SURV-000.md#persona-and-fixture-foundation), [evidence](proofs/SURV-000.md#foundation-browser-failure-diagnostics) |
| 000.5 | [evidence](proofs/SURV-000-CONTRACT-REVIEW.md) |
| 000.T1 | [evidence](proofs/SURV-000-CONTRACT-REVIEW.md) |
| 000.T1a | [evidence](proofs/SURV-000.md#complete-write-transport-inventory) |
| 000.T1b | [evidence](proofs/SURV-000.md#concurrent-replay-for-every-write) |
| 000.T1c | [evidence](proofs/SURV-000.md#competing-revisions-for-every-revision-bearing-write) |
| 000.T2 | [evidence](proofs/SURV-000.md#foundation-browser-failure-diagnostics) |
| 010.1 | [evidence](proofs/SURV-010.md#task-and-scenario-reconciliation) |
| 010.2 | [evidence](proofs/SURV-010.md#task-and-scenario-reconciliation), [evidence](proofs/SURV-010.md#isolated-validation-candidate-selection), [evidence](proofs/SURV-010.md#shared-core-backend-integration) |
| 010.3 | [evidence](proofs/SURV-010.md#task-and-scenario-reconciliation), [evidence](proofs/SURV-010.md#shared-core-backend-integration) |
| 010.4 | [evidence](proofs/SURV-010.md#task-and-scenario-reconciliation) |
| 010.T1 | [evidence](proofs/SURV-010.md#task-and-scenario-reconciliation), [evidence](proofs/SURV-010.md#shared-core-backend-integration) |
| 010.T2 | [evidence](proofs/SURV-010.md#task-and-scenario-reconciliation) |
| 020.1 | [evidence](proofs/SURV-020.md#delivery-and-acceptance), [evidence](proofs/SURV-020.md#host-translated-editor-and-entrypoint-acceptance) |
| 020.1a | [evidence](proofs/SURV-020.md#bounded-host-logo-integration) |
| 020.2 | [evidence](proofs/SURV-020.md#delivery-and-acceptance), [evidence](proofs/SURV-020.md) |
| 020.3 | [evidence](proofs/SURV-020.md#delivery-and-acceptance) |
| 020.3a | [evidence](proofs/SURV-020.md#responsive-progress-navigation) |
| 020.4 | [evidence](proofs/SURV-020.md#delivery-and-acceptance), [evidence](proofs/SURV-020.md) |
| 020.T1 | [evidence](proofs/SURV-020.md#delivery-and-acceptance), [evidence](proofs/SURV-020.md) |
| 020.T2 | [evidence](proofs/SURV-020.md#delivery-and-acceptance) |
| 030.1 | [evidence](proofs/SURV-030.md#migration-and-lifecycle-task-reconciliation) |
| 030.2 | [evidence](proofs/SURV-030.md#populated-invitation-duplication) |
| 030.3 | [evidence](proofs/SURV-030.md#migration-and-lifecycle-task-reconciliation) |
| 030.T1 | [evidence](proofs/SURV-030.md#migration-and-lifecycle-task-reconciliation) |
| 030.T1a | [evidence](proofs/SURV-030.md#migration-and-lifecycle-task-reconciliation), [evidence](proofs/SURV-030.md#observed-lifecycle-lock-orders) |
| 030.T2 | [evidence](proofs/SURV-030.md#migration-and-lifecycle-task-reconciliation), [evidence](proofs/SURV-060.md) |
| 040.1 | [evidence](proofs/SURV-040.md#template-creation-and-editor-regression) |
| 040.2 | [evidence](proofs/SURV-040.md#template-creation-and-editor-regression) |
| 040.3 | [evidence](proofs/SURV-040.md#template-creation-and-editor-regression) |
| 040.4 | [evidence](proofs/SURV-040.md#template-creation-and-editor-regression) |
| 040.5 | [evidence](proofs/SURV-040.md#template-creation-and-editor-regression) |
| 040.T1 | [evidence](proofs/SURV-040.md#template-creation-and-editor-regression) |
| 040.T2 | [evidence](proofs/SURV-040.md#template-creation-and-editor-regression) |
| 050.1 | [evidence](proofs/SURV-050.md#analysis-consumer-acceptance) |
| 050.1a | [evidence](proofs/SURV-050.md#published-completion-text) |
| 050.2 | [evidence](proofs/SURV-050.md#analysis-consumer-acceptance), [evidence](proofs/SURV-050.md#process-restart-and-untransmitted-tab-loss) |
| 050.3 | [evidence](proofs/SURV-050.md#analysis-consumer-acceptance) |
| 050.4 | [evidence](proofs/SURV-050.md#analysis-consumer-acceptance) |
| 050.T1 | [evidence](proofs/SURV-050.md#analysis-consumer-acceptance) |
| 050.T2 | [evidence](proofs/SURV-050.md#analysis-consumer-acceptance) |
| 060.1 | [evidence](proofs/SURV-060.md#consolidated-surv-060-acceptance), [evidence](proofs/SURV-060.md) |
| 060.2 | [evidence](proofs/SURV-060.md#consolidated-surv-060-acceptance) |
| 060.2a | [evidence](proofs/SURV-060.md#consolidated-surv-060-acceptance), [evidence](proofs/SURV-060.md#persona-resource-api-matrix) |
| 060.2b | [evidence](proofs/SURV-060.md#consolidated-surv-060-acceptance), [evidence](proofs/SURV-060.md#publisher-only-review-and-publication) |
| 060.2c | [evidence](proofs/SURV-060.md#consolidated-surv-060-acceptance), [evidence](proofs/SURV-060.md#active-survey-browser-permission-matrix) |
| 060.2d | [evidence](proofs/SURV-060.md#consolidated-surv-060-acceptance), [evidence](proofs/SURV-060.md#separate-role-lifecycle-journeys) |
| 060.2e | [evidence](proofs/SURV-060.md#consolidated-surv-060-acceptance), [evidence](proofs/SURV-060.md#changed-authority-and-child-resource-boundaries) |
| 060.2f | [evidence](proofs/SURV-060.md#consolidated-surv-060-acceptance), [evidence](proofs/SURV-060.md#invitation-and-deletion-special-scopes) |
| 060.3 | [evidence](proofs/SURV-060.md#consolidated-surv-060-acceptance), [evidence](proofs/SURV-060.md#personal-invitations), [evidence](proofs/SURV-060.md#invitation-credential-and-expired-resume-acceptance), [evidence](proofs/SURV-060.md#real-response-invitation-retry-and-test-policy-correction) |
| 060.4 | [evidence](proofs/SURV-060.md#consolidated-surv-060-acceptance), [evidence](proofs/SURV-060.md#preview-isolation-and-timeout-snapshot-acceptance) |
| 060.T1 | [evidence](proofs/SURV-060.md#consolidated-surv-060-acceptance) |
| 060.T2 | [evidence](proofs/SURV-060.md#consolidated-surv-060-acceptance) |
| 070.1 | [evidence](proofs/SURV-070.md#analysis-gate-reconciliation), [evidence](proofs/SURV-070.md#analysis-ui-and-neutral-result-components) |
| 070.2 | [evidence](proofs/SURV-070.md#analysis-gate-reconciliation), [evidence](proofs/SURV-070.md#analysis-ui-and-neutral-result-components), [evidence](proofs/SURV-070.md) |
| 070.3 | [evidence](proofs/SURV-070.md#analysis-gate-reconciliation), [evidence](proofs/SURV-070.md#authorized-raw-response-browser-views) |
| 070.T1 | [evidence](proofs/SURV-070.md#analysis-gate-reconciliation), [evidence](proofs/SURV-070.md#immutable-analysis-snapshots) |
| 070.T2 | [evidence](proofs/SURV-070.md#analysis-gate-reconciliation), [evidence](proofs/SURV-070.md#authorized-raw-response-browser-views) |
| 080.1 | [evidence](proofs/SURV-080.md#worker-recovery-and-tabular-task-acceptance) |
| 080.2 | [evidence](proofs/SURV-080.md#consolidated-render-acceptance) |
| 080.3 | [evidence](proofs/SURV-080.md#terminal-job-state-acceptance) |
| 080.T1 | [evidence](proofs/SURV-080.md#terminal-job-state-acceptance), [evidence](proofs/SURV-080.md#permission-boundary-acceptance) |
| 080.T2 | [evidence](proofs/SURV-080.md#consolidated-render-acceptance) |
| 090.1 | [evidence](proofs/SURV-090.md#deletion-task-and-scenario-reconciliation), [evidence](proofs/SURV-090.md#deterministic-deletion-interleavings) |
| 090.1a | [evidence](proofs/SURV-090.md#deletion-task-and-scenario-reconciliation), [evidence](proofs/SURV-090.md#manual-erasure-status-and-open-respondent-browser-acceptance) |
| 090.2a | [evidence](proofs/SURV-090.md#deletion-task-and-scenario-reconciliation), [evidence](proofs/SURV-090.md#full-restic-backup-and-fresh-target-restore), [evidence](proofs/TASK-STATUS-RECONCILIATION.md) |
| 090.2c | [evidence](proofs/SURV-090.md#deletion-task-and-scenario-reconciliation), [evidence](proofs/SURV-090.md#independent-checkpoint-archive-and-interrupted-publication) |
| 090.2d | [evidence](proofs/SURV-090.md#deletion-task-and-scenario-reconciliation), [evidence](proofs/SURV-090.md#automatic-archive-acknowledgement-and-worker-gate) |
| 090.2e | [evidence](proofs/SURV-090.md#deletion-task-and-scenario-reconciliation), [evidence](proofs/SURV-090.md#retention-publication-interruption-and-recovery) |
| 090.2f | [evidence](proofs/SURV-090.md#deletion-task-and-scenario-reconciliation), [evidence](proofs/SURV-090.md#offline-pilot-preflight-and-validator-release-binding) |
| 090.2g | [evidence](proofs/SURV-090.md#deletion-task-and-scenario-reconciliation), [evidence](proofs/SURV-090.md#pilot-restore-with-post-backup-survey-erasure) |
| 090.2h | [evidence](proofs/SURV-090.md#deletion-task-and-scenario-reconciliation), [evidence](proofs/SURV-090.md#interrupted-pilot-reapplication-and-authenticated-resume) |
| 090.3 | [evidence](proofs/SURV-090.md#deletion-task-and-scenario-reconciliation), [evidence](proofs/SURV-090.md#export-admission-and-log-acceptance) |
| 090.3a | [evidence](proofs/SURV-090.md#deletion-task-and-scenario-reconciliation), [evidence](proofs/SURV-090.md#public-request-quota-acceptance) |
| 090.3b | [evidence](proofs/SURV-090.md#deletion-task-and-scenario-reconciliation), [evidence](proofs/SURV-090.md#payload-boundaries-and-participation-log-acceptance) |
| 090.3c | [evidence](proofs/SURV-090.md#deletion-task-and-scenario-reconciliation), [evidence](proofs/SURV-090.md#export-admission-and-log-acceptance) |
| 090.T2 | [evidence](proofs/SURV-090.md#deletion-task-and-scenario-reconciliation), [evidence](proofs/SURV-090.md#manual-erasure-status-and-open-respondent-browser-acceptance) |
| 100.2 | [complete journeys](proofs/SURV-100.md#complete-desktop-and-mobile-survey-journeys), [two CI repetitions](proofs/SURV-100-CI-REPEAT.md), [task/capability review](#review-decision) |
| 100.1a | [evidence](proofs/SURV-100-BROWSER-DIAGNOSTICS.md) |
| 100.2a | [evidence](proofs/SURV-100-DROPDOWN.md) |
| 100.3a | [evidence](proofs/SURV-100.md#react-peer-policy-and-packed-consumer) |
| 100.3b | [evidence](proofs/SURV-100.md#isolated-pilot-operator-regression) |
| 100.3c | [evidence](proofs/SURV-100.md#isolated-identity-policy-and-public-regressions) |
| 100.3d | [evidence](proofs/SURV-100.md#isolated-compose-regression) |
| 100.3e | [evidence](proofs/SURV-100.md#reserved-networks-and-seven-backend-regressions) |
| 100.3f | [evidence](proofs/SURV-100.md#six-isolated-browser-regressions) |
| 100.3g | [evidence](proofs/SURV-100.md#six-more-isolated-regressions) |
| 100.3h | [evidence](proofs/SURV-100-DOCUMENT-MAIL.md) |
| 100.3j | [evidence](proofs/SURV-100-OPERATIONS.md) |
| 100.3k | [evidence](proofs/SURV-100-PRIVACY-TESTKIT-GOLDEN.md) |
| 100.3l | [seed](proofs/SURV-100-SEED.md), [backup](proofs/SURV-100-BACKUP.md), [upgrade/rollback](proofs/SURV-100-UPGRADE.md) |
| 100.T2 | [evidence](proofs/SURV-100-DROPDOWN.md), [evidence](proofs/SURV-100.md#complete-desktop-and-mobile-survey-journeys) |

## Capability review

The [C-01–C-15 index](CAPABILITIES.md#5-capability-to-fixture-evidence-index)
and [consolidated contract review](proofs/SURV-000-CONTRACT-REVIEW.md#c-01c-15-fixture-reconciliation)
map every initial capability to actual fixtures and recorded authoring, execution,
validation and reporting evidence. The profile remains bounded; this does not
claim support for arbitrary SurveyJS JSON or commercial components.

## Review decision

The criterion is a reconciliation requirement: each capability must link to
actual test/proof evidence, and every task must be either accepted with evidence
or explicitly open and prevent a full-completion claim. It does not require all
tasks to pass before their open status can be truthfully reconciled.

The review matched all 104 implementation/test IDs and their checked states
against PLAN.md, inspected their criterion and proof references, and reviewed
all 15 capability rows against the
[consolidated fixture/assertion review](proofs/SURV-000-CONTRACT-REVIEW.md#c-01c-15-fixture-reconciliation).
The 392 original task/capability file and fragment links resolved; added review
links are verified with this increment. Link existence is supporting evidence,
not the basis for an implementation claim.

The underlying review covers page/question editing and restored progress,
text/choice/rating/date/matrix semantics, conditions and hidden-answer cleanup,
partial/final validation, presentation, independent templates, protected JSON
imports, draft retry/history, keyboard/translation and browser-mount behavior.
It preserves the distinctions between editor, runtime, authoritative validation
and analysis/export. The shared Core, export pipeline and independent packed
consumer are also included in the complete 38-check, two-pass CI evidence.

The published sources under `apps`, `packages`, `src` and `migrations` have no
diff from the consolidated review's checkpoint `419738d` to `b450783`, and no
uncommitted changes in those paths at this review. Thus the reviewed assertions
still address the same application/package implementation. This does not make
all test harnesses unchanged: queued regression, cleanup and rating-helper
changes retain their separate unaccepted scope.

Historical proof paragraphs are interpreted chronologically. For example,
SURV-040's template-creation proof explicitly closes a gap that earlier survey
duplication evidence did not cover; SURV-080's terminal-job-state acceptance
supersedes its preceding paragraph leaving 080.3 open. Scoped legacy-suite
acceptance never closes the parent regression criterion. The export render
review covers its recorded synthetic corpus and consumers, not arbitrary fonts,
all accessibility tools or general performance certification.

**100.2 is accepted** because its complete desktop/mobile author-to-deletion
journeys already satisfy 100.A2 and this reconciliation now satisfies 100.A4.
The aborted local rerun stopped during image building, produced no browser result,
and does not validate the stronger uncommitted rating helper. Its repetition
remains required for that change. Earlier intermittent failures are retained in
the history, alongside the subsequent two complete successful CI executions.

**100.S3 remains open for its separate 100.A5 delivery requirement.** Likewise,
100.1, 100.3, 100.4 and 100.T1 retain their remaining criteria. The eleven open
tasks above, plus their open scenarios and criteria, prevent a full-completion
claim. The outcome document remains provisional. Own license stays **UNDEFINED**,
commercial SurveyJS components are excluded, and no package publication or
production-readiness claim follows from this review.
