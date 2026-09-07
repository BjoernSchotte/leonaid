# Surveys — implementation task acceptance checklist

This checklist makes the acceptance gate for each implementation task explicit.
The deliverables and criterion definitions remain authoritative in [PLAN.md](PLAN.md);
the expected results for named test scenarios are in [TEST-SCENARIOS.md](TEST-SCENARIOS.md).
Own license: **UNDEFINED**. Commercial components remain excluded.

A checkbox here means **task acceptance**, not merely code delivery. Open entries
await a task-by-task evidence review; checked entries retain their linked proof.
This does not reset checked delivery or criteria in PLAN.md. Check a task only when every listed criterion
and relevant assertion passes, and link the task-specific proof using
[TASK-ACCEPTANCE.md](TASK-ACCEPTANCE.md).

Integration and E2E references distinguish direct criterion coverage from the
work-package regression gate when a task has no criterion at that test layer.
When a scenario spans multiple tasks, record the assertions that exercise this
task and its integration into the complete user journey. Shared scenarios must
not be reduced to a smoke test. Dependency and rendering reviews remain required
where referenced by the acceptance criteria, even though they are not E2E tests.

## Per-task completion rule

- [ ] Deliver the concrete implementation described by the task.
- [ ] Pass every referenced acceptance criterion with named assertions.
- [ ] Pass the listed integration scenarios against real services.
- [ ] Pass the listed E2E scenarios through the actual user interface.
- [ ] Record rejection, persistence and recovery outcomes required by those scenarios.
- [ ] Link the tested revision, exact commands, exit codes and sanitized artifacts.
- [ ] Verify isolated Docker resources and successful cleanup.

Use this rule separately for each task; do not check these template boxes as
a substitute for completing an individual task.

## SURV-000 — Contracts, dependency selection and test infrastructure

The [write-contract inventory](WRITE-CONTRACTS.md) records all 21 transport
operations, authorization, revision/replay scope and persistence behavior.
**000.T1a / 000.S1a** prove their strict negative transport boundary against real
stored data; [evidence](proofs/SURV-000.md#complete-write-transport-inventory).
This does not close the full contracts/persona/capability acceptance below.

- [x] **000.T1b** Prove concurrent identical requests and later replay for all 21 survey write operations, with observed overlapping persistence-lock waits, exact database/outbox deltas, actual stored-value and response-model validation and unchanged complete row contents on replay/conflict. Handle reused resume credentials atomically with a documented 409 and no duplicate participation, including competing starts across surveys. Acceptance: **000.A1, duplicate-operation portion**. Integration: **000.S1b**; full cross-operation/competing-revision and capability coverage remains required. [Live evidence](proofs/SURV-000.md#concurrent-replay-for-every-write).

- [ ] **000.1** Define versioned DTOs and ports for drafts, publication, participation, saves, completion, aggregates and exports; specify errors, revision conflicts and idempotency.

  Acceptance criteria: **000.A1**.
  Integration / supporting checks: **000.S1**.
  E2E — work-package regression gate: **000.S4**.

Role/entity/migration mapping is documented in [ROLES-AND-DATA.md](ROLES-AND-DATA.md); the broader contract acceptance remains open.

- [ ] **000.2** Map existing roles and resource scopes to survey capabilities; define database entities, constraints and migration sequence.

  Acceptance criteria: **000.A1, 000.A2**.
  Integration / supporting checks: **000.S1, 000.S2**.
  E2E — work-package regression gate: **000.S4**.

- [x] **000.3** Pin compatible SurveyJS 3 core/React versions and permissive editor/chart/XLSX dependencies; inventory transitive software and asset licenses, including OFL notices. [Current evidence](proofs/SURV-000.md#complete-runtime-dependency-disposition).

  Acceptance criteria: **000.A4**.
  Integration / supporting checks: **000.S3**.
  E2E — work-package regression gate: **000.S4**.

- [x] **000.4** Build deterministic Krapfentaxi/golf fixtures and persona seeds in the existing testkit; add isolated Docker test entrypoints and artifact collection. [Fixture evidence](proofs/SURV-000.md#persona-and-fixture-foundation).

  Acceptance criteria: **000.A2, 000.A3**.
  Integration / supporting checks: **000.S2**.
  E2E: **000.S4**.

Foundation browser gate **000.T2 / 000.A3 / 000.S4** is accepted: an ordinary
member reaches the member UI and published public survey shell, and an intentional
browser assertion failure returns exit 1 with sanitized diagnostics and complete
owned-stack teardown. See [the two-run proof](proofs/SURV-000.md#foundation-browser-failure-diagnostics).
Task **000.4** is accepted after the full persona/fixture review and current permissions run. [Fixture evidence](proofs/SURV-000.md#persona-and-fixture-foundation).

The source-reviewed profile, limits, validation and host-rendering boundary are in [PROFILE-CONTRACT.md](PROFILE-CONTRACT.md). Full **000.A1** acceptance remains open.

- [ ] **000.5** Specify the initial capability profile, limits and client/server semantics; record chosen token mapping and SSR/hydration probe strategy.

  Acceptance criteria: **000.A1**.
  Integration / supporting checks: **000.S1**.
  E2E — work-package regression gate: **000.S4**.

## SURV-010 — Vertical autosave and authoritative validation proof

[Task and scenario reconciliation with current live evidence](proofs/SURV-010.md#task-and-scenario-reconciliation).

- [x] **010.1** Implement minimal definition loading, participation creation, revisioned snapshot saving, restoration and completion through the real API/database.

  Acceptance criteria: **010.A2, 010.A3, 010.A5**.
  Integration / supporting checks: **010.S2, 010.S3**.
  E2E: **010.S4**.

- [x] **010.2** Compare the explicit Python rule model with an isolated SurveyJS-Core validation adapter; select and document the option that proves equivalent initial-profile semantics.

  Acceptance criteria: **010.A1**.
  Integration / supporting checks: **010.S1**.
  E2E — work-package regression gate: **010.S4, 010.S5**.

- [x] **010.3** Implement required/type/bounds/choice/matrix validation, relevance evaluation and hidden-answer cleanup; distinguish incomplete answers from invalid values. Wire the selected shared-Core adapter into the actual save/completion path after host definition approval; bound calls and reject adapter failures without partial writes.

  Acceptance criteria: **010.A1, 010.A2, 010.A4**.
  Integration / supporting checks: **010.S1, 010.S2**.
  E2E: **010.S5**.

- [x] **010.4** Wire answer events and debounced text updates to persistence; implement a short configurable timeout classification proof.

  Acceptance criteria: **010.A3, 010.A4, 010.A5**.
  Integration / supporting checks: **010.S3**.
  E2E: **010.S4, 010.S5**.

## SURV-020 — Neutral package and independent demo

[Per-task acceptance and assertion mapping](proofs/SURV-020.md#delivery-and-acceptance); [current-source reconciliation](proofs/SURV-020.md#companion-task-reconciliation).

- [x] **020.1a** Configure a bounded host logo independently of questionnaire JSON; retain respondent state across host changes and display the asset in both hosts and on completion. [Live evidence](proofs/SURV-020.md#bounded-host-logo-integration).

  Acceptance: allowed local assets load; invalid/external paths create no image request; desktop/mobile layout remains bounded; persisted answers and revision survive reload/restart.
  Integration / E2E: **020.S6**, packed independent consumer and real LeonAid services.

- [x] **020.1** Create separate editor, runner, analytics, contracts and styles entrypoints with host-supplied adapters and translation/theme configuration.

  Acceptance criteria: **020.A1, 020.A2, 020.A3**.
  Integration / supporting checks: **020.S1, 020.S2**.
  E2E: **020.S3**.

- [x] **020.2** Build a standalone demo consuming a packed artifact outside workspace resolution; provide a minimal real backend adapter for its integration proof.

  Acceptance criteria: **020.A1, 020.A3**.
  Integration / supporting checks: **020.S1**.
  E2E: **020.S3**.

- [x] **020.3** Implement scoped SurveyJS token styling and the chosen browser hydration mode; investigate SSR and record the observed compatibility boundary.

  Acceptance criteria: **020.A3, 020.A4**.
  Integration / supporting checks — work-package regression gate: **020.S1, 020.S2**.
  E2E: **020.S3, 020.S4**.

- [x] **020.3a** Keep all progress steps visible in narrow host containers with usable controls. Acceptance: real three-page surveys at 320/390/1440 pixels expose every step without clipping, preserve answers through forward/back navigation, and complete through the real API. Integration/E2E: **020.S7**; isolated branding harness. [Live evidence](proofs/SURV-020.md#responsive-progress-navigation).

- [x] **020.4** Add bundle/import and license checks, third-party notices and explicit OFL asset handling.

  Acceptance criteria: **020.A2**.
  Integration / supporting checks: **020.S2**.
  E2E — work-package regression gate: **020.S3, 020.S4**.

## SURV-030 — Lifecycle, migrations and immutable versions

- [ ] **030.1** Implement schema migrations, repositories and lifecycle use cases for draft, active, ended, archived and deleted surveys.

  Acceptance criteria: **030.A1, 030.A4**.
  Integration / supporting checks: **030.S1, 030.S5**.
  E2E: **030.S4, 030.S6**.

- [ ] **030.2** Implement revisioned draft editing, immutable publication, version-bound participation and duplication without recipients or answers.

  Acceptance criteria: **030.A2, 030.A3**.
  Integration / supporting checks: **030.S2, 030.S3**.
  E2E — work-package regression gate: **030.S4, 030.S6**.

- [ ] **030.3** Enforce allowed transitions, transactional survey-end cutoff and restore behavior in server policies and database transactions.

  Acceptance criteria: **030.A1, 030.A2, 030.A4**.
  Integration / supporting checks: **030.S1, 030.S2, 030.S5**.
  E2E: **030.S4, 030.S6**.

## SURV-040 — Visual questionnaire editor

- [x] **040.1** Implement page/question creation, reordering, movement, duplication and removal with stable IDs and keyboard alternatives to dragging.

  Acceptance criteria: **040.A1, 040.A3, 040.A4**.
  Integration / supporting checks: **040.S1**.
  E2E: **040.S3, 040.S4**.

- [x] **040.2** Implement property panels for initial question types, presentation, required flags, bounds and guided conditions; add live preview.

  Acceptance criteria: **040.A2, 040.A3, 040.A4**.
  Integration / supporting checks: **040.S2**.
  E2E: **040.S3, 040.S4**.

- [x] **040.3** Implement undo/redo, revision-aware draft autosave, save/conflict indicators and safe JSON import/export with diagnostics.

  Acceptance criteria: **040.A1, 040.A2, 040.A5**.
  Integration / supporting checks: **040.S1, 040.S2**.
  E2E: **040.S5**.

- [x] **040.4** Preserve safe unknown regions read-only; enforce capability-profile publication validation without silently discarding unsupported data.

  Acceptance criteria: **040.A1, 040.A2**.
  Integration / supporting checks: **040.S1, 040.S2**.
  E2E — work-package regression gate: **040.S3, 040.S4, 040.S5**.

- [x] **040.5** Add blank/Krapfentaxi/golf template selection with independent editable drafts and exact creation retry. Acceptance: **C-11**, real template creation/edit/reload/publication and zero-response checks. Integration/E2E: **040.S6**, including persisted definitions and response counts. [Live evidence](proofs/SURV-040.md#template-creation-and-editor-regression).

Tasks 040.1–040.4 are reconciled with the existing accepted main-plan criteria
and the complete passing editor regression in that same proof.

## SURV-050 — Public runner, ordered saves and recovery

- [x] **050.1** Implement the full multipage runner, page-transition flush, debounced text saves, save status and in-memory retry queue.

  Acceptance criteria: **050.A3, 050.A5**. [Accepted evidence](proofs/SURV-050.md#analysis-consumer-acceptance).
  Integration / supporting checks — work-package regression gate: **050.S1, 050.S2**.
  E2E: **050.S3, 050.S5**.

- [x] **050.1a** Display the published version's configured completion text as plain text, falling back to host copy when empty. Acceptance: desktop/mobile completion and reload show the participation's original text after a newer publication; a new participant receives the new text; answers/status remain correct. Integration/E2E: **050.S6**. [Live evidence](proofs/SURV-050.md#published-completion-text).

- [x] **050.2** Implement revision checks, idempotency, response ordering, multi-tab conflicts and atomic completion, including retry after a lost completion acknowledgement.

  Acceptance criteria: **050.A1, 050.A4**. [Accepted evidence](proofs/SURV-050.md#process-restart-and-untransmitted-tab-loss).
  Integration / supporting checks: **050.S1**.
  E2E: **050.S4**.

- [x] **050.3** Implement backend timeout default/override settings, effective per-participation configuration, classification worker and consistent read-time classification.

  Acceptance criteria: **050.A2, 050.A5**. [Accepted evidence](proofs/SURV-050.md#analysis-consumer-acceptance).
  Integration / supporting checks: **050.S2**.
  E2E: **050.S5**.

- [x] **050.4** Implement protected resume access and restoration; suppress save events caused solely by restoring existing data.

  Acceptance criteria: **050.A3, 050.A4, 050.A5**. [Accepted evidence](proofs/SURV-050.md#analysis-consumer-acceptance).
  Integration / supporting checks — work-package regression gate: **050.S1, 050.S2**.
  E2E: **050.S3, 050.S4, 050.S5**.

## SURV-060 — LeonAid module, permissions and invitations

- [ ] **060.1** Add Umfragen navigation, lifecycle screens, action linking, explicit standalone ownership and backend timeout controls.

  Acceptance criteria: **060.A4, 060.A5**.
  Integration / supporting checks — work-package regression gate: **060.S1, 060.S2**.
  E2E: **060.S4, 060.S5**.

- [x] **060.2** Enforce distinct design/publish/read/aggregate/export/invite/delete capabilities across API routes, lists, counts and UI actions.

  Acceptance criteria: **060.A1, 060.A4**.
  Integration / supporting checks: **060.S1**.
  E2E: **060.S4**.

- [x] **060.2a** Exercise all nine individual grants and owner/manager/member/outsider/admin personas across standalone, joined-action and foreign resources. Verify scoped lists/counts/search/pagination, populated reads, own/foreign export jobs and denied writes without SQL changes.

  Acceptance criteria: **060.A1, static API matrix portion**.
  Integration: **060.S1a**, [live evidence](proofs/SURV-060.md#persona-resource-api-matrix).
  [Consolidated acceptance](proofs/SURV-060.md#consolidated-surv-060-acceptance).

  E2E — work-package regression gate: **060.S4b** (browser persona/resource matrix).

- [x] **060.2b** Give publication-only members a validated publication review and submit action without granting draft editing. Bind publication to the reviewed revision and retain the exact operation after lost acknowledgement.

  Acceptance criteria: **060.A1/A4, publisher-only portion**.
  Integration/E2E: **060.S4a**, [live evidence](proofs/SURV-060.md#publisher-only-review-and-publication).
  [Consolidated acceptance](proofs/SURV-060.md#consolidated-surv-060-acceptance).

- [x] **060.2c** Exercise all 14 personas against the four active-survey resource scopes in desktop/mobile browsers; verify scoped list links, controls and direct response-selection navigation, with direct API checks from the same session.

  Acceptance criteria: **060.A4, active-survey portion**.
  E2E: **060.S4b**, [live evidence](proofs/SURV-060.md#active-survey-browser-permission-matrix).
  [Consolidated acceptance](proofs/SURV-060.md#consolidated-surv-060-acceptance).

  Integration / supporting checks: **060.S1a** (API persona/resource matrix).

- [x] **060.2d** Exercise successful lifecycle handoffs between separate design, publish, archive and delete accounts; preserve completed answers through restore and prove requester-specific permanent erasure.

  Acceptance criteria: **060.A1/A4, lifecycle role journeys**.
  Integration/E2E: **060.S4c**, [live evidence](proofs/SURV-060.md#separate-role-lifecycle-journeys).
  [Consolidated acceptance](proofs/SURV-060.md#consolidated-surv-060-acceptance).

- [x] **060.2e** Prove that existing sessions immediately lose revoked survey grants, expired action scope and suspended-account access. Reject foreign child IDs even for an administrator with access to both surveys; preserve the survey SQL fingerprint.

  Acceptance criteria: **060.A1, dynamic authority and child-resource boundaries**.
  Integration: **060.S1b**, [live evidence](proofs/SURV-060.md#changed-authority-and-child-resource-boundaries).
  Regression: **060.S4a–060.S4c**. [Consolidated acceptance](proofs/SURV-060.md#consolidated-surv-060-acceptance).

  E2E — work-package regression gate: **060.S4a–060.S4c**.

- [x] **060.2f** Verify populated invitation list/revocation scopes, successful single-grant invitation journeys and completed deletion status/replay ownership.

  Acceptance criteria: **060.A1, 060.A4**.
  Integration/E2E: **060.S4d**, [live evidence](proofs/SURV-060.md#invitation-and-deletion-special-scopes).
  [Consolidated acceptance](proofs/SURV-060.md#consolidated-surv-060-acceptance).

- [x] **060.3** Implement anonymous links, revocable attributable invitations, secure resume sessions and synthetic invitation delivery through outbox/worker/Mailpit.

  Acceptance criteria: **060.A2, 060.A3**.
  Evidence: [060.A3 / 060.S3 accepted](proofs/SURV-060.md#personal-invitations); [060.A2 / 060.S2 accepted](proofs/SURV-060.md#invitation-credential-and-expired-resume-acceptance).
  Integration / supporting checks: **060.S2**.
  E2E: **060.S3**.

  Integration/E2E retry correction: **060.S3a**, [real-response proof](proofs/SURV-060.md#real-response-invitation-retry-and-test-policy-correction). No fabricated HTTP response is accepted as current retry evidence.

- [x] **060.4** Add preview/test participation isolation so author testing does not contaminate collected responses or analysis.

  Acceptance criteria: **060.A5**.
  Integration / supporting checks — work-package regression gate: **060.S1, 060.S2**.
  E2E: **060.S5**.

## SURV-070 — Aggregates, charts and filters

- [x] **070.1** Implement immutable analysis snapshots, status/version filters and per-question relevance/answer denominators.

  Acceptance criteria: **070.A1, 070.A2, 070.A3**. [Accepted evidence](proofs/SURV-070.md#analysis-ui-and-neutral-result-components).
  Integration / supporting checks: **070.S1, 070.S2**.
  E2E: **070.S3**.

- [x] **070.2** Implement distributions, rating summaries, NPS and matrix aggregates with explicit handling of missing, hidden and invalid values.

  Acceptance criteria: **070.A1, 070.A3**. [Accepted evidence](proofs/SURV-070.md#analysis-ui-and-neutral-result-components).
  Integration / supporting checks: **070.S1**.
  E2E: **070.S3**.

- [x] **070.3** Build custom charts and accessible tables, plus separately authorized free-text/individual-response views.

  Acceptance criteria: **070.A2, 070.A3, 070.A4**. [Accepted evidence](proofs/SURV-070.md#authorized-raw-response-browser-views).
  Integration / supporting checks: **070.S2**.
  E2E: **070.S3, 070.S4**.

## SURV-080 — CSV, XLSX and Typst exports

Browser criteria **080.A4 / 080.S4** and **080.A6 / 080.S6** are
[accepted](proofs/SURV-080.md#populated-browser-exports-and-permission-revocation).
Task 080.1 also has accepted A1/A2 integration evidence below; the other tasks
remain open until their remaining criteria pass.

- [x] **080.1** Implement response CSV/XLSX and analysis XLSX from a shared AnalysisSnapshot, with stable columns, metadata, denominators and formula-safe text. [Accepted evidence](proofs/SURV-080.md#worker-recovery-and-tabular-task-acceptance).

  Acceptance criteria: **080.A1, 080.A2, 080.A4, 080.A6**.
  Integration / supporting checks: **080.S1, 080.S2**.
  E2E: **080.S4, 080.S6**.

- [x] **080.2** Implement server chart rendering and a dedicated Typst analysis template; support Unicode, long text and pagination. [Accepted evidence](proofs/SURV-080.md#consolidated-render-acceptance).

  Acceptance criteria: **080.A1, 080.A4, 080.A5**.
  Integration / supporting checks: **080.S1, 080.S5**.
  E2E: **080.S4**.

- [x] **080.3** Implement durable export jobs, private object storage, retry/error states, authorized downloads and revocation/deletion invalidation. [Accepted evidence](proofs/SURV-080.md#terminal-job-state-acceptance).

  Acceptance criteria: **080.A3, 080.A4, 080.A6**.
  Integration / supporting checks: **080.S3**.
  E2E: **080.S4, 080.S6**.

## SURV-090 — Deletion, recovery and operational limits

- [ ] **090.1** Implement trash/restore, configurable retention and retryable permanent deletion of definitions, responses, invitations and export objects.

  Acceptance criteria: **090.A1, 090.A2, 090.A5**.
  Integration / supporting checks: **090.S1, 090.S2**.
  E2E: **090.S5**.

- [ ] **090.1a** Deliver explicit permanent-erasure confirmation, durable reloadable status and administrative retry controls; prove the open-respondent trash/restore journey.

  Acceptance criteria: **090.A5**, plus pending, failure, retry and completed states and authorized status access.
  Integration / supporting checks: **090.S2**, persistent deletion-job state and object cleanup.
  E2E: **090.S5**, including confirmation, reload and retry controls.
  Existing [implementation evidence](proofs/SURV-090.md#manual-erasure-status-and-open-respondent-browser-acceptance) must be reconciled with these task-level assertions before this acceptance box is checked.

- [ ] **090.2** Implement content-free deletion records and restore-time reapplication; integrate the existing backup/recovery workflow using isolated synthetic data.

  Acceptance criteria: **090.A3**.
  Integration / supporting checks: **090.S3**.
  E2E — work-package regression gate: **090.S5**.

- [ ] **090.2a** Prove encrypted Restic backup, manifest validation and fresh-target restore with a post-backup deletion; block startup without a checkpoint, erase restored content with a valid checkpoint and preserve source image identities during no-build restoration.

  Acceptance criteria: **090.A3, operator integration portion**.
  Integration / supporting checks: **090.S3**, restricted to the operator assertions above; [existing evidence](proofs/SURV-090.md#full-restic-backup-and-fresh-target-restore).
  E2E — work-package regression gate: **090.S5**. The operator CLI proof does not replace browser coverage or complete the parent recovery criterion.
  Leave task acceptance open until its existing evidence is reconciled assertion by assertion.

- [ ] **090.2b** Retain the latest authenticated deletion checkpoint independently and prove the required recovery cutoff across source loss, including interrupted publication and stale-file rejection.

  Acceptance criteria: **090.A3, checkpoint continuity portion**; preserve the complete parent recovery contract.
  Integration / supporting checks: **090.S3** and **090.S3a–090.S3f**. Require trustworthy cutoff provenance after unexpected host loss and preceding-backup compatibility; accepted sub-scenarios alone do not close this task.
  E2E — work-package regression gate: **090.S5**. Restored participation/export access denial belongs to the direct recovery integration assertions.

- [x] **090.2c** Publish authenticated checkpoints into a separately retained filesystem archive. Serialize publication/fetch, preserve prior erasures and reject interrupted, stale, corrupted or missing-current states; retrieve without a database and prove real Restic recovery after source-project removal.

  Acceptance criteria: **090.A3, archive primitive portion**.
  Integration / supporting checks: **090.S3a**, [live evidence](proofs/SURV-090.md#independent-checkpoint-archive-and-interrupted-publication).
  Parent 090.2 and PLAN task 090.2b remain open for continuous independent retention, cutoff provenance and the remaining operator recovery contract.

  E2E — work-package regression gate: **090.S5**; this task's direct acceptance is established by the integration assertions above.

- [x] **090.2d** Archive committed manual deletion intent before successful API acknowledgement and before production worker erasure; preserve exact retry identity during outages and restore an old backup after source-project loss using only automatically retained material. [Live evidence](proofs/SURV-090.md#automatic-archive-acknowledgement-and-worker-gate).

  Acceptance criteria: **090.A3, acknowledgement portion**.
  Integration / supporting checks: **090.S3b**.
  Retention interruption is covered by 090.2e. Parent recovery acceptance remains open for independent host-loss cutoff and the operator compatibility contract.

  E2E — work-package regression gate: **090.S5**; this task's direct acceptance is established by the integration assertions above.

- [x] **090.2e** Prove interruption of a retention-originated publication after its database transaction commits and the pending archive document is durable. Recover through a zero-candidate sweep, preserving original deletion/outbox identities, then restart the production worker and verify eventual erasure plus inactive-answer preservation. [Live evidence](proofs/SURV-090.md#retention-publication-interruption-and-recovery).

  Acceptance criteria: **090.A3, retention continuity portion**.
  Integration / supporting checks: **090.S3c**; existing retention browser regression.
  Full recovery acceptance remains open for independent host-loss cutoff and operator compatibility.

  E2E — work-package regression gate: **090.S5**; this task's direct acceptance is established by the integration assertions above.

- [x] **090.2f** Remove live-source availability from restore-only pilot preflight, explicitly report unperformed live checks, and retain environment/backup/decision validation. Require an immutable validator image in pilot Compose and release manifests, with no production build.

  Acceptance criteria: **090.A3, operator preflight portion**.
  Integration: **090.S3d**, [live evidence](proofs/SURV-090.md#offline-pilot-preflight-and-validator-release-binding).
  Nonempty restoration/input rejection are covered by 090.2g and interrupted
  reapplication by 090.2h. Independent cutoff provenance and preceding-release compatibility remain open.

  E2E — work-package regression gate: **090.S5**; this task's direct acceptance is established by the integration assertions above.

- [x] **090.2g** Prove nonempty survey recovery through `pilot-restore` after real encrypted backup, permanent deletion and source-project removal. Reject missing, tampered, wrong-key, wrong-installation and stale checkpoints on fresh targets, checking exact restored SQL answers and export objects offline. Valid recovery must erase all survey content before no-build startup and deny old authenticated/public access.

  Acceptance criteria: **090.A3, nonempty pilot-wrapper and input-rejection portion**.
  Integration: **090.S3e**, [live evidence](proofs/SURV-090.md#pilot-restore-with-post-backup-survey-erasure).
  Operator/API/database/storage checks; this is not browser E2E or complete
  unexpected-host-loss recovery. Checkpoint and cutoff are explicitly retained.

  E2E — work-package regression gate: **090.S5**. The direct recovery proof above
  exercises the operator CLI and real services; it does not replace browser coverage.

- [x] **090.2h** Add authenticated resume for a quarantined pilot restore after the imports finish and before application startup begins.

  Acceptance: a forced interruption after committed erasures leaves application services stopped; `--resume` verifies configuration, backup, volume and phase identity, reruns erasure without reimport, preserves an independent SQL sentinel and denies old access after startup. Changed or unsafe receipts, replaced volumes, backwards cutoff and concurrent restore attempts sharing the operator lock directory fail closed.
  Integration: **090.S3f**; [Live evidence](proofs/SURV-090.md#interrupted-pilot-reapplication-and-authenticated-resume). Focused receipt/lock tests supplement the real encrypted-backup pilot journey. Parent 090.2 / 090.A3 still require host-loss cutoff provenance and preceding-backup compatibility.

  E2E — work-package regression gate: **090.S5**; this task's direct acceptance is established by the integration assertions above.

- [x] **090.3** Enforce documented payload, public-request and export limits; audit operations without answer content or resume credentials.

  Acceptance criteria: **090.A4**.
  Integration / supporting checks: **090.S4**.
  E2E — work-package regression gate: **090.S5**.

- [x] **090.3a** Enforce durable public request quotas across survey IDs and
  client-controlled cookie/User-Agent rotation. Prove concurrent exhaustion,
  HTTP 429/Retry-After, unchanged persisted survey state and expiry recovery.

  Acceptance criteria: **090.A4, public-request portion only**.
  Integration: **090.S4a**, [live evidence](proofs/SURV-090.md#public-request-quota-acceptance).
  Parent 090.3 is accepted with the other limit/log sub-tasks.

  E2E — work-package regression gate: **090.S5**; this task's direct acceptance is established by the integration assertions above.

- [x] **090.3b** Enforce the raw request-body byte limit before JSON parsing;
  prove exact and excessive definition/answer payloads, chunked excess,
  unchanged persisted state and captured-log marker exclusion.

  Acceptance criteria: **090.A4, payload and participation-log portion**.
  Integration: **090.S4b**, [live evidence](proofs/SURV-090.md#payload-boundaries-and-participation-log-acceptance).
  Parent 090.3 is accepted with the other limit/log sub-tasks.

  E2E — work-package regression gate: **090.S5**; this task's direct acceptance is established by the integration assertions above.

- [x] **090.3c** Bound new export-job admission across surveys per requester;
  prove exhaustion, independent users, authorization/replay precedence,
  absence of rejected job/outbox writes and expiry selection. Parse all four
  real worker products and scan export logs for private markers.

  Acceptance criteria: **090.A4, export portion**; completes parent 090.3
  with 090.3a/b. Integration: **090.S4c**.
  [Consolidated evidence](proofs/SURV-090.md#export-admission-and-log-acceptance).

  E2E — work-package regression gate: **090.S5**; this task's direct acceptance is established by the integration assertions above.

## SURV-100 — Full acceptance and spike outcome

- [ ] **100.1** Wire the aggregate survey test command and CI lane, deterministic isolation/cleanup and failure artifact handling.

  Acceptance criteria: **100.A1, 100.A2, 100.A3, 100.A5**.
  Integration / supporting checks: **100.S1, 100.S2, 100.S3**.
  E2E: **100.S4**.

- [ ] **100.2** Execute complete author → invite/public participation → abandon/resume → analyze → export → archive/delete journeys for both sample surveys.

  Acceptance criteria: **100.A2, 100.A4**.
  Integration / supporting checks: **100.S3**.
  E2E: **100.S4**.

Browser delivery and **100.A2 / 100.T2 / 100.S4** are accepted after all four
complete journeys and independent parsing/erasure verification. [Live evidence](proofs/SURV-100.md#complete-desktop-and-mobile-survey-journeys).
Task-level **100.2** acceptance remains open solely for its broader **100.A4**
capability/task reconciliation gate; successful journeys do not close that audit.

- [ ] **100.3** Verify the packed independent consumer and run affected existing identity, policy, public and integration regression suites.

  Acceptance criteria: **100.A3, 100.A5**.
  Integration / supporting checks: **100.S2, 100.S3**.
  E2E — work-package regression gate: **100.S4**.

- [x] **100.3a** Resolve React compatibility peers versus runtime pins and prove the packed consumer against its real backend.

  Acceptance criteria: partial contribution to **100.A5**; **100.3** remains open.
  Integration / supporting checks: pin gate, six peer-policy tests, frozen workspace
  lock and installed packed-consumer version assertions.
  E2E: all four `surveys-package.spec.mjs` cases, including backend restart.
  [Evidence](proofs/SURV-100.md#react-peer-policy-and-packed-consumer).

- [x] **100.3b** Run the affected pilot deploy/release/backup/restore regression with unique owned resources, free loopback ports and separate source/target subnets; verify cleanup.

  Acceptance criteria: partial contribution to **100.A3**; **100.3** remains open.
  Integration / supporting checks: full `tools/pilot_deployment/test.sh`, including
  actual immutable-image deployment, encrypted backup and no-build restore.
  E2E scope: operator CLI and real HTTP/TLS services, not browser journeys.
  The fixture has zero erasures and does not accept survey disaster recovery.
  [Evidence](proofs/SURV-100.md#isolated-pilot-operator-regression).

- [x] **100.3c** Isolate and execute `./leonaid test-identity`, `test-policy`, `test-public-actions` and `test-public-orders` without shared project cleanup or host-port bindings. [Live evidence](proofs/SURV-100.md#isolated-identity-policy-and-public-regressions).

  Acceptance criteria: **100.A3, four named regressions**. Every original assertion must pass; failed teardown must return failure and leave unrelated resources untouched.
  Integration / E2E: **100.S2b**, including real service contracts and existing desktop/mobile/multi-browser checks where defined by the individual suite. Full `test-integration` and **100.3** remain open.

- [x] **100.3d** Isolate and execute the complete existing Compose regression using a unique project, unused explicit subnets and two free loopback ports. Acceptance: **100.A3, Compose regression portion**; validate the real default service inventory including `survey-validator`, readiness, host routing, PostgreSQL/RustFS persistence across restart, Twenty schema stability, optional profiles and complete owned cleanup. Integration: **100.S2c**; E2E scope is operator CLI and real HTTP/TLS, not browser interaction. [Live evidence](proofs/SURV-100.md#isolated-compose-regression). Full **100.3 / 100.A3** remains open.
- [x] **100.3e** Isolate and execute the seven core, schema, outbox, OpenAPI, Twenty metadata, CRM gateway and CRM import regressions. Acceptance: **100.A3, seven named suites only**; reserve all owned networks before starting any service, resolve real subnet allocation collisions, preserve the original service/data assertions and verify complete owned cleanup. Integration/operator E2E: **100.S2d**; browser journeys remain separate. [Live evidence](proofs/SURV-100.md#reserved-networks-and-seven-backend-regressions). Full **100.3 / 100.A3** remains open.
- [x] **100.3f** Isolate and execute the existing invitation, session, matching, assignment, activity and action regressions. Acceptance: **100.A3, six named suites only**; preserve real API/SQL/SMTP/CRM assertions and complete browser journeys, reserve owned networks before startup, publish no host ports and verify cleanup. Integration/E2E: **100.S2e**; the remaining legacy suites and full **100.3 / 100.A3** stay open. [Live evidence](proofs/SURV-100.md#six-isolated-browser-regressions).

- [ ] **100.4** Produce the outcome report with observed capability coverage, open defects, performance/size observations and remaining production work; keep publication and own license undecided.

  Acceptance criteria: **100.A4, 100.A5**.
  Integration / supporting checks: **100.S3**.
  E2E — work-package regression gate: **100.S4**.

## Final reconciliation

- [x] Every implementation task in PLAN.md has exactly one entry above (69 implementation IDs reconciled; this is a documentation inventory check, not implementation acceptance).
- [ ] Every completed task links to its task-level proof; no inferred passing status.
- [ ] Changes to tasks, criteria or scenarios update this matrix in the same commit.
- [ ] Remaining open tasks are listed in the spike report and prevent full completion.
