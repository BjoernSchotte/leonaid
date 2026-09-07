# SURV-090 — Deletion, recovery and operational limits

Status: **in progress**. Own license remains **UNDEFINED**. 090.1, 090.A1, 090.A2 / 090.S2 and 090.A5 / 090.T2 are accepted. The retention section adds proven behavior for
090.1 and the inactivity-preservation part of 090.A3. The complete work package
remains open. The recovery section proves checkpoint reapplication
after an actual DB/object restore. The generic Restic operator is now proven
below; checkpoint continuity remains open.

## Durable erasure and process-crash recovery

Source revision: `8432163` (the unchanged implementation and probe content that
passed the run below, committed after execution). Runtime pins are recorded in
`infra/locks/images.env` and the Dockerfiles used by the harness. Python uses the
pinned UV Python 3.13 image; PostgreSQL 16.9 and RustFS 1.0.0-beta.11 are the actual
persistence services. This test uses only synthetic data.

Command, from the checkout root:

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" deletion
```

Successful isolated project: `leonaid-surveys-833458328-86796`; command exit **0**.
The harness selected seven unused subnets, published no host ports, removed its
containers/networks/volumes and verified that no project containers or volumes
remained. The Chromium foundation journey passed (one case, 1.2 seconds). This
browser check proves the existing member/public foundation only; it is **not**
delete-button E2E acceptance.

### Implemented behavior

- `POST /api/v1/surveys/{survey_id}/delete-permanently` requires an authenticated
  actor with the existing delete capability, a trashed survey and its current
  revision. It atomically commits an erasure record and an empty-payload outbox
  event. The response is `no-store` and contains only identity, status and times.
- The erasure record retains opaque survey/actor/event IDs, an operation-ID hash,
  revision and timestamps. It stores no definition, title, answer, recipient,
  credential or plaintext operation ID. An active original requester can replay
  the exact operation to observe completion after the survey row is gone.
- Once intent is committed, authoring/restoration and re-creation of the same
  survey ID are refused. A database trigger independently prevents inserting or
  updating that survey ID. Inactivity does not request erasure.
- The durable worker takes the same survey advisory/row locks as export and
  authoring operations. It removes exact recorded object versions and checks each
  export's deterministic key for an upload that crashed before its DB commit.
  Only after storage succeeds does it remove export jobs and the survey's
  relational content. The completed content-free record remains.
- A storage exception leaves the intent and database references available for
  retry. Provider diagnostics are replaced by the generic
  `survey_deletion_failed` error. A late export event with no remaining job does
  nothing, including when deletion wins after its initial identity lookup.

### Named assertions and results

`tools/surveys/deletion_live.py` runs these stages through the real API, outbox,
PostgreSQL and RustFS adapters:

1. **prepare:** unauthenticated, non-trash and stale-revision deletion requests
   are rejected; rejected requests create no erasure record. A fixture includes
   published definitions, populated completed responses, a recipient invitation
   and an aggregate snapshot. Two real CSV exports are produced: one committed
   normally and one uploaded through the production renderer/storage path before
   an injected exception rolls back its database transaction. Both exact file
   versions exist before deletion.
2. **prepare:** the valid request commits one pending record; exact replay returns
   the same result and another operation ID conflicts. Restore and downloads are
   denied. The ledger's exact column allowlist and hashed operation ID are
   inspected; seeded sensitive text is absent from the ledger.
3. **crash:** claim the exact deletion event and execute a real S3 version DELETE.
   Verify that the version is absent, then terminate the worker process with
   `os._exit(73)` before its database transaction commits. The harness requires
   exactly that exit code.
4. **recover:** verify the durable event is still processing on attempt 1, the
   intent is incomplete, both export-job records remain, and exactly one of the
   two original file versions is now absent. Advance this synthetic event's
   claim timestamp beyond the production lease and let the real queue reclaim
   it. Attempt 2 completes successfully.
5. **recover:** assert zero targeted rows in `survey`, `survey_draft`,
   `survey_version`, `survey_participation`, `survey_operation`,
   `survey_invitation`, `survey_grant`, `survey_analysis_snapshot` and
   `survey_export_job`; both exact versions and their current keys are absent.
   The grant table is checked for absence but this fixture does not seed a grant.
6. **recover:** exact API replay reports completion; API reads/recreation fail,
   and direct SQL recreation hits the erasure guard. Releasing the delayed
   export event completes harmlessly without recreating a job.

Sanitized result: [SURV-090-deletion.json](assets/SURV-090-deletion.json).
No raw temporary state, credentials, answer payloads or unrestricted logs are
included in the retained artifact.

The first run (`leonaid-surveys-833458328-86337`) failed in the probe's ledger
column assertion: iterating an asyncpg Record yields values, not column names.
The assertion was corrected to `ledger.keys()` after that process terminated.
The successful fresh-stack run above exercised the corrected probe. Production
code was unchanged between those two runs.

Additional successful checks: scoped Ruff check and MyPy for the new adapter,
authoring repository, HTTP transport and worker composition; OpenAPI/client
regeneration; `bun run --cwd apps/web typecheck`; `git diff --cached --check`.
These checks do not replace the live erasure assertions.

## Acceptance ledger

| Item | Result | Evidence / remaining work |
| --- | --- | --- |
| 090.A2 / 090.S2 | Passed | Actual version deletion, process termination, lease reclaim and complete relational/object cleanup above. |
| 090.1 | Passed | Durable erasure/reclaim, retention, manual status/retry UI and the deterministic A1 interleavings below satisfy A1/A2/A5. |
| 090.2 / 090.A3 | Open | The authenticated checkpoint gate and full generic Restic/fresh-target restore are proven below (090.2a); independent latest-checkpoint continuity remains open (090.2b). |
| 090.3 / 090.A4 | Open | Full limits and log-marker acceptance remains. |
| 090.A1 | Passed | Six observed-lock interleavings cover autosave, completion and export before/after deletion below. |
| 090.T1 | Open | A2 subset passed; remaining integration criteria are not waived. |
| 090.T2 / 090.A5 | Passed | Open-browser rejected save, closed restore, invitation/download denial and manual erasure/status/retry journeys below. |

Operational boundaries: this proof keeps one configured object-storage bucket.
A historical bucket migration or externally created extra object versions is
not covered. The schema downgrade deliberately refuses to discard the deletion
ledger; the backup/recovery work must preserve and reapply it. Retry exhaustion
uses the existing durable outbox's dead-letter handling; user-facing status and
retry controls still need the module integration. No complete retention or
backup-restoration claim is made here.


## Configurable retention and member-backend acceptance

Source revision: `c27e2d9` (unchanged source/probe content committed after the
successful executions). Decisions are recorded in
[DECISIONS.md](../DECISIONS.md#retention-scheduling-semantics). Own license stays
**UNDEFINED**; no dependency was added.

Commands from the checkout root:

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" retention
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" deletion
```

- Retention run: `leonaid-surveys-833458328-91543`, exit **0**; two Chromium
  journeys passed in 3.7 seconds, including the mobile settings journey.
- Shared-deletion regression: `leonaid-surveys-833458328-92130`, exit **0**;
  actual object DELETE, exit 73, reclaimed attempt 2 and all original cleanup
  assertions passed; foundation Chromium journey passed in 2.0 seconds.
- Both runs used distinct allocated subnets, no published host ports and fresh
  volumes. The harness removed its resources and verified no remaining project
  containers/volumes. No other worktree's resources were changed.

### Proven assertions

- [x] **Policy integration:** `retention_live.py prepare` verifies both settings
  default to null, unauthorised members receive 403, zero/negative/over-limit
  periods receive 422 without mutation, stale revisions receive 409 and exact
  operation replay is idempotent. Updating only the inactivity timeout preserves
  omitted retention fields; explicit null disables each stage independently.
- [x] **Lifecycle integration:** the real sweep moves old ended and archived
  surveys into trash with an explicit one-second policy, while disabled trash
  retention creates no deletion record. A busy advisory lock is skipped within
  the five-second assertion bound; the next sweep handles that survey. Restore
  starts a new retention clock; archive/unarchive preserve it. These assertions
  use actual PostgreSQL state and synthetic timestamp advancement.
- [x] **Inactivity separation:** an active survey's 90-day-old in-progress answer
  becomes partial but its seeded answer remains identical. With automatic
  retention disabled all five fixture surveys remain. After retention runs,
  the active survey and draft still exist; respondent inactivity never selected
  them for deletion.
- [x] **Worker integration:** after `prepare` enables one-second trash retention,
  the harness starts the real production worker process. `recover` waits at most
  60 seconds and verifies two due surveys were erased, their deletion records
  completed and exactly one completed erasure event exists per survey. No direct
  sweep invocation or hand-written queue claim substitutes for this phase.
- [x] **Backend E2E:** `surveys-retention.spec.mjs` opens mobile navigation as the
  admin, sets 30/7 days in the real module, saves, and checks API persistence as
  2,592,000/604,800 seconds. Reload retains both values. Clearing and saving both
  fields persists nulls. A non-admin opens the supported survey-module route,
  cannot see the settings, and gets 403 from their API. API responses are no-store.
- [x] **Visual observation:** the retained 390-pixel mobile form was manually
  inspected: labels, explanatory text and save control are readable and the
  automated horizontal-overflow assertion passes. This is a review of the new
  settings form, not a complete application visual/accessibility certification.

Artifacts: [integration results](assets/SURV-090-retention.json),
[browser results](assets/SURV-090-retention-browser.json),
[mobile form](assets/SURV-090-retention-mobile.png).
Private test sessions and raw traces were not copied into these artifacts.

Ruff checks passed for the affected Python files; MyPy passed for the retention,
delete and authoring adapters plus HTTP/worker entrypoints; web TypeScript checking
and OpenAPI/client generation passed. The full live runtime also verifies the
worker import after the correction described below.

### Failed attempts and corrections

- `...-89816` failed at worker startup because `asyncpg.Pool[Any]` was evaluated
  at import time. A separate container import reproduced the exception. Adding
  postponed annotation evaluation fixed the production module.
- `...-90161` passed API/production-worker checks, then the browser probe failed
  because it had not opened mobile navigation. The probe was corrected.
- `...-90841` additionally passed the admin's complete mobile settings journey,
  then used the wrong starting page for an ordinary member. The general admin
  landing page redirects that persona to the PWA by design; the survey module
  remains accessible at `/admin/surveys`. Using that supported entry fixed the
  probe without adding rights or changing production access policy.
- Each failed process was confirmed terminal before edits and a fresh isolated
  run was started. The final successful run above covers all corrected assertions.

### Remaining scope

This accepts the configurable-retention portion of 090.1 and proves that
inactivity alone deletes nothing. **090.A3 remains open** because it also requires
real backup restoration and deletion-record reapplication. Full autosave,
completion and erasure interleavings, log/limit acceptance, manual erasure/status
controls and the open-respondent deletion E2E journey are still required.
The migration's backfill of already closed rows has not yet received a dedicated
upgrade-fixture proof; the runs above prove migration from empty volumes and
post-migration lifecycle clocks. Real operational retention periods remain a
separate deployment decision.


## Offline erasure reapplication after an actual backup restore

Implementation revision: `875221c`. The live run used its checkpoint/reapply
behavior; the final shared 32 MiB export/import boundary guard was added after
that run and independently covered by the unit boundary test. No backup, restore,
erasure, authentication or access behavior changed after the live run.

Command:

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" recovery
```

Successful final project: `leonaid-surveys-833458328-96383`, exit **0**. An earlier
run, `leonaid-surveys-833458328-95232`, also passed the initial restore/reapply
probe; the final run additionally exercises the actual checkpoint-export CLI,
mode 600 and old-session/public-route access after restart. Both projects used
fresh isolated resources and no published host ports. Containers, networks and
volumes were removed; the harness verified no remaining project containers or
volumes. The foundation Chromium journey passed after application restart.

The test restores a real custom-format PostgreSQL dump with `pg_restore
--exit-on-error` and a real archive of the stopped RustFS volume. It replaces only
the fresh test project's data. It does **not** invoke the existing Restic wrapper
or simulate loss of the machine that holds the latest checkpoint.

### Proven assertions

- [x] **Backup predates deletion:** `recovery_live.py seed` creates a published
  survey, a populated response, a frozen analysis selection and an actual CSV
  export through the production outbox/storage adapters. With survey writers and
  RustFS stopped, the harness captures the database and complete object volume.
- [x] **Newer deletion record:** after the backup, the real API trashes and
  permanently deletes the survey. The worker removes its row and exact file
  version. The checkpoint export includes this newer deletion and no seeded
  answer text. The CLI writes the authenticated file atomically with mode 600.
- [x] **Actual resurrection while offline:** after restoring both artifacts,
  `restored` verifies the survey is active, its deletion record is absent and the
  original exact object version exists with the original SHA-256 and answer text.
  API, public surface, proxy and worker remain stopped at this stage.
- [x] **Tamper rejection before mutation:** a checkpoint with its record removed
  but its old authentication value exits 1 with a generic diagnostic. A second
  inspection confirms the restored survey/object state is still unchanged.
- [x] **Reapplication and repeat:** the authenticated checkpoint passes the
  installation/cutoff checks, commits erasure intent and removes the restored
  survey, response, snapshot/export relations and exact file through the existing
  eraser. The CLI runs twice successfully. A checkpoint that omits a deletion
  already known by the database is rejected by the adapter.
- [x] **Access after restart:** the application starts only after successful
  reapplication. The old authenticated session gets 404 for survey and export
  download; the public definition route also returns 404. The deleted data is
  not recovered through the old session.

Sanitized results: [SURV-090-recovery.json](assets/SURV-090-recovery.json).
Actual database dumps, RustFS archives, checkpoint identities/authentication
values and test-session credentials are not included in the committed artifact.

`tests/unit/test_survey_recovery.py`: **12 passed** (0.07 seconds, exit 0), covering
roundtrip field allowlisting, record removal/alteration, unexpected answer fields,
wrong signature/key/installation, stale/naive/future cutoffs, duplicate identities
and the exact shared document-size boundary. MyPy passed for the application
contract and both adapters. Scoped Ruff checks and `git diff --check` passed on the final source.

### Acceptance boundary

This is evidence for 090.2 and 090.A3, not full acceptance of either. The current
implementation is an offline primitive whose caller must keep application writers
stopped. [RECOVERY.md](../RECOVERY.md) specifies the implemented contract and
remaining requirements. The existing `tools/backup/restore.sh` does not yet invoke
it automatically. Independently retaining the newest checkpoint across source
loss, proving the operator-selected freshness cutoff and covering the existing
Restic/fresh-target/rotation workflow remain open. Do not use this result to claim
complete production disaster recovery or close SURV-090.

## Shared restore-operator gate

This section supersedes the preceding statement that the generic restore does
not invoke reapplication. `tools/backup/restore.sh` now calls
`tools/backup/survey-erasure-gate.sh` after both `pg_restore` operations and
before its application-start branch. Both restores now use `--exit-on-error`.
The gate is unconditional with respect to `LEONAID_RESTORE_START_APP`; a caller
requesting database-only restoration cannot receive success without passing it.

Command: `rtk proxy sh tools/surveys/infrastructure.sh "$PWD" recovery`.
Project `leonaid-surveys-833458328-99651`, exit **0**; Chromium foundation case
passed in **1.6 seconds**. The implementation and probe content committed with
this section were unchanged during that run. The harness used fresh subnets,
no host ports and verified removal of its containers and volumes after teardown.

- [x] The shared production shell gate rejects a missing checkpoint, missing
  cutoff, tampered authenticated envelope and an authentic checkpoint whose
  timestamp does not cover the requested cutoff. Each command exits exactly 1.
- [x] After each rejection, assertions verify API, public, proxy and worker are
  stopped. The restored active survey and original exact export version/hash
  still exist; rejection did not mutate them or expose them through those services.
- [x] The gate builds the development API image and mounts the checkpoint
  read-only into its no-dependency one-off command. Valid reapplication succeeds
  twice and removes the resurrected relational content and exact object version.
- [x] After restarting application services, the old session cannot read the
  survey/export, the public definition returns 404, and the foundation browser
  journey passes. This is not the still-open manual deletion UI journey.

Sanitized result: [SURV-090-recovery-gate.json](assets/SURV-090-recovery-gate.json).
Scoped Ruff, shell syntax checks for the modified scripts and `git diff --check`
passed. Existing backup/upgrade/pilot test fixtures now export an independent
temporary checkpoint before their restore and explicitly supply its cutoff.
Those three complete suites were **not run in this increment**; their helper
wiring received syntax/source review only. Their synthetic workflows perform no
survey mutations after that capture; this does not solve production continuity.

The shared gate is exercised against actual restored PostgreSQL/RustFS data;
the complete Restic restore invocation, fresh target, legacy-schema branch and
no-build release-image path remain unproven here. Latest-checkpoint/source-loss
continuity and migration compatibility remain open as specified in
[RECOVERY.md](../RECOVERY.md). **090.2 and 090.A3 remain unchecked.**

## Full Restic backup and fresh-target restore

Accepted subtask: **090.2a**. The full 090.2 / 090.A3 scope still includes
independent latest-checkpoint continuity; 090.2b records that remaining work.
This run supersedes earlier sections' missing generic Restic/fresh-target proof.

Command from the checkout root:

```sh
rtk proxy sh tools/surveys/restic_recovery.sh "$PWD"
```

The source/probe changes committed with this section ran unchanged from start
to completion. Source project `leonaid-poc112-surveys-833458328-3251`; target
`leonaid-restore-surveys-833458328-3251`. Exit **0**. Chromium foundation journey:
**1 passed, 1.0 seconds**. Runtime images use the repository's existing pinned
build inputs and `infra/locks/images.env`.

### Assertions and actual operator behavior

- [x] Create a published survey and populated synthetic response, then generate
  a real CSV export using the production API/outbox/PostgreSQL/RustFS adapters.
- [x] Run `tools/backup/backup.sh` with its existing writer-stop boundary. Restic
  encrypts the four cross-system backup components and manifest, executes the
  7-daily/5-weekly/12-monthly/3-yearly policy and completes `check --read-data`
  with no errors. This runs the policy on one snapshot; it does not simulate
  years of retention or replace the separate rotation contract tests.
- [x] After that backup, use the real API/worker to permanently delete the survey
  and file. Export a newer authenticated checkpoint explicitly to a separate
  temporary location, with mode 600 and the fixture's post-deletion,
  pre-CLI-export cutoff. Remove the source containers and volumes and assert absence.
- [x] Invoke the actual `tools/backup/restore.sh` against a fresh target without
  the required checkpoint. Restic restore and manifest byte/hash validation
  succeed; the survey gate exits exactly 1 before application startup.
- [x] Inspect that rejected restore: the old active survey, absent deletion
  record, original exact object version, SHA-256 and seeded answer bytes are
  really present. API, public, proxy and worker are not running. An earlier
  manifest/restore failure cannot substitute for this assertion.
- [x] Remove the rejected target volumes and rerun the actual restore with the
  valid checkpoint and `LEONAID_RESTORE_NO_BUILD=true`. The gate reapplies erasure
  before the command starts the full stack; all services reach their health gates.
- [x] Verify the target's API, worker, web, PWA, public and survey-validator image
  IDs equal the recorded source IDs. No target-side build or mutable image
  substitution supplies the successful application.
- [x] After startup, inspect absence of survey, draft, version, participation,
  analysis snapshot and export-job rows, completed erasure state, and absence of
  the original exact object version. Old authenticated survey/download requests
  and the public definition request return 404. The foundation browser case passes.
- [x] Remove the target containers/volumes and assert absence. The unique source
  and target overlays disable host port publication and use selected unused
  subnets; no other worktree's Docker resources are changed.

Sanitized result: [SURV-090-restic-recovery.json](assets/SURV-090-restic-recovery.json).
The trap removes the private checkpoint, session, manifest, password, Restic
repository and generated overlays. Only content-free boolean results and
explicit limitations are retained. Scoped Ruff, shell syntax and diff whitespace
checks passed. No production dependency or license policy changed.

### Remaining scope

The checkpoint was exported before deliberate removal of the source project.
The whole host holding that file was not lost, and automatic independent
publication of the newest checkpoint is not implemented. HMAC validity alone
does not prove freshness; do not close 090.2b or claim completed disaster recovery.
This run uses the generic restore's no-build branch with exact local image IDs;
the separate pilot Doctor/release-manifest wrapper and preceding survey-schema
compatibility are not covered. Manual deletion UI, concurrency and limits/log
criteria elsewhere in SURV-090 remain unchanged.

## Manual erasure, status and open-respondent browser acceptance

Accepted: **090.1a, 090.T2 and 090.A5**. Parent 090.1 remains open for the full
autosave/completion/export/deletion interleavings in 090.A1. Source/probe content
committed with this section was unchanged throughout the final successful run.

Command: `rtk proxy sh tools/surveys/infrastructure.sh "$PWD" deletion-ui`.
Successful project: `leonaid-surveys-833458328-10022`, exit **0**, fresh networks
and volumes, no published host ports, teardown and resource absence verified.
Chromium results: open-respondent/erasure case **1 passed (4.8s)**; administrator
retry **1 passed (1.4s)**; worker-completion and foundation cases **2 passed (1.3s)**.
Member pages use a 390×844 viewport; the separate public participant uses the
browser's default desktop viewport. All identities and answer values are synthetic.

### Implemented behavior

- A trashed survey with delete capability exposes an explicit final-erasure
  confirmation. Its submit control remains disabled until the user acknowledges
  removal of the questionnaire, answers, invitations and export files. Existing
  server authorization and revision/idempotency checks still authorize the write.
- `GET /api/v1/surveys/{survey_id}/deletion` reads the durable content-free record
  even after the survey row is gone. Only an active original requester or current
  system administrator may read it; other principals receive 404, unauthenticated
  requests receive 401. Responses are `no-store`. States are pending, retrying,
  failed and completed; an unknown status is never displayed as successful erasure.
- The response contains only survey ID, status, request/completion timestamps and
  a nullable retry event ID. That event ID is supplied only to current system
  administrators when the existing outbox event is dead-lettered. No title,
  definition, answer, recipient or credential is returned.
- Status polling and full reload recover from the server. A lost POST response
  triggers a status lookup; it does not trigger a second erasure request. No
  browser-persisted operation record or credential is needed for reload recovery.
- Administrators can retry a failed job through the existing fresh-authentication
  `retryOperationalJob` endpoint. Its existing permission/audit boundary is
  retained. Other requesters see an instruction to contact administration.

### Live assertions

- [x] The public participant begins the real published fixture and receives a
  save acknowledgement. The member trashes it through the module while that
  public page remains open. Further input produces `data-save-state=error` and
  the visible message “Diese Umfrage nimmt keine Antworten mehr an.”
- [x] The already-rendered export download returns 404 after trash. Invitation
  creation returns 409. A separate invitation-mode fixture establishes a real
  successful pre-trash invitation creation, then rejects the same operation type
  after trash; anonymous-mode rejection alone is not used as that proof. This
  case verifies invitation creation, not a new mail-delivery/token-redemption run.
- [x] UI restoration returns the published survey to ended. Public definition
  access remains closed and reloading the respondent does not offer a new start.
- [x] The member trashes it again, checks the explicit confirmation and submits.
  Playwright forwards the real POST, verifies its committed pending response,
  then drops that response. The module recovers via GET, displays pending and
  retains that status after reload; no restore control remains. Exactly one POST
  committed in this lost-acknowledgement scenario.
- [x] `deletion_ui_live.py` verifies that an unrelated active member receives 404
  for status and 403 for operational retry. PostgreSQL still contains the earlier
  accepted text and contains none of the attempted post-trash text.
- [x] The probe seeds a real persisted dead-letter state for the deletion event.
  This is a UI/state fixture, not a newly claimed storage-outage proof. The admin
  browser sees failure, clicks retry and observes retrying through the real API.
- [x] Starting the actual production worker completes erasure. A newly opened
  member page displays completion; reload retains it and the ordinary survey
  endpoint returns 404. Existing object-crash/reclaim evidence above proves the
  underlying eraser's storage cleanup; this new case proves its member workflow.

Artifacts: [sanitized assertions](assets/SURV-090-deletion-ui.json),
[mobile confirmation](assets/SURV-090-deletion-confirm-mobile.png),
[mobile completion](assets/SURV-090-deletion-completed-mobile.png).
Both mobile captures were manually inspected: consequence text, acknowledgement,
buttons and completion text are readable; the confirmation's automated overflow
assertion passes. This is scoped visual observation, not full accessibility or
cross-browser certification. Raw traces/session files were not committed.

Scoped Ruff and MyPy for both changed server modules passed, as did web TypeScript
checking, OpenAPI/client regeneration, shell syntax and diff whitespace checks.
OpenAPI generation emitted the repository's existing unrelated Pydantic alias
warnings and exited zero.

### Failed attempts

- `...-7173` correctly produced the closed-survey error, but the test expected the
  generic network-failure wording. The retained public screenshot established
  the actual more specific wording; the assertion was corrected.
- `...-8620` used a `.invalid` recipient address rejected by the existing email
  validator with 422 before the intended lifecycle check. Reserved `example.com`
  fixture addresses fixed that setup; test mail stays in isolated Mailpit.
- `...-9298` used the summary revision when publishing the invitation fixture;
  publication requires the draft revision. The fixture now reads `/draft`.
- Every failed process was confirmed terminal before edits. The final fresh
  run above includes every corrected fixture and assertion.

## Deterministic deletion interleavings

The production code at `07a5861` required no change for this acceptance increment.
The new probe is [deletion_races_live.py](../../../tools/surveys/deletion_races_live.py);
its final content was unchanged during the accepted run. The harness adds the
`deletion-races` mode. Runtime image pins remain those in the existing Dockerfiles
and `infra/locks/images.env`.

### Ordering and assertions

The probe uses real HTTP endpoints, PostgreSQL transactions, production export
and deletion handlers, and RustFS. It observes `pg_stat_activity` lock waits and
`pg_blocking_pids`; the 20 ms polling interval does not determine ordering.
Each wait has a deadline. Survey revisions are loaded before starting the races,
so the actual POST trash mutation, rather than its preliminary GET, is queued.

| Case | Deliberately forced order | Verified outcome |
| --- | --- | --- |
| Autosave first | Hold the participation row; observe the API save holding the survey row while waiting; queue POST trash behind that save; release. | Save commits revision 3, trash succeeds, durable erasure removes the accepted answer and its operation record. |
| Completion first | The same observed row-lock chain with POST complete. | Completion commits revision 3 with completed status; subsequent trash and erasure remove it. |
| Deletion before autosave | Commit trash and deletion intent; hold the survey row; queue eraser first, then the API save; release only after both wait. | Erasure commits; save returns 404 and recreates no content. |
| Deletion before completion | The same observed lock chain with POST complete. | Completion returns 404 and recreates no content. |
| Export first | Pause the production handler after an actual S3 upload while it retains the survey locks; queue POST trash on that handler's advisory lock; release upload acknowledgement. | Export commits, trash succeeds, erasure removes the exact uploaded version and current object; download returns 404. |
| Deletion before export | With committed deletion intent, hold the survey advisory lock; observe eraser queued first, then the exporter after its preliminary job lookup; release. | Eraser removes the job; the waiting exporter becomes a no-op without calling upload. |

For every case, the probe checks absence of all survey-scoped rows in `survey`,
`survey_draft`, `survey_version`, `survey_participation`, `survey_operation`,
`survey_invitation`, `survey_grant`, `survey_analysis_snapshot` and
`survey_export_job`, plus a completed content-free deletion ledger entry.
Late save and completion requests return 404. Repeated erasure remains safe.
Both export cases additionally redeliver the persisted event after deletion and
check that no export becomes downloadable. Export fixtures contain a completed
synthetic response before snapshot creation.

The probe delivers persisted export events directly to the production handler;
it does not claim new queue-lease coverage. Actual queue reclaim, process crash
and uncommitted-upload cleanup are covered by the earlier A2 proof. It tests the
two serialization orders at the relevant locks, not exhaustive instruction-level
scheduling or load performance. Public writes cannot remain authorized once a
survey is trashed, so response-first cases race the trash cutoff, followed by
permanent erasure; deletion-first cases race the actual eraser.

### Execution evidence

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" deletion-races
```

Final project: `leonaid-surveys-833458328-14668`. All six integration cases passed;
the existing Chromium identity/public-host foundation test passed (1 test, 1.4 s).
The harness used fresh volumes, selected currently unused subnets, published no
host ports, and verified teardown. The full command exited zero. Ruff check and
format, shell syntax and `git diff --check` passed for the changed test/harness.
Sanitized results: [SURV-090-deletion-races.json](assets/SURV-090-deletion-races.json).
No sessions, participation secrets, record identifiers or answer payloads are
retained in that artifact.

An earlier run (`leonaid-surveys-833458328-14213`) passed, but review found its
trash helper first waited in a summary read. The final run above preloads the
revision and proves the actual mutation waits; only this final run is used for
acceptance. No application behavior was changed to satisfy the tests.

090.A1 and parent implementation task 090.1 are now accepted together with the
existing A2/A5 evidence. 090.T1 and the full work package remain open for recovery
checkpoint continuity and limits/log acceptance.

## Public request quota acceptance

Task **090.3a** and scenario **090.S4a** are accepted for the public-request
portion of 090.A4. Parent 090.3, 090.A4 and 090.T1 remain open: this increment
does not establish the remaining payload/export boundaries or captured-log scan.
Runtime baseline: `e49b530` plus the security change in the commit containing
this record. The own-license decision remains UNDEFINED; no dependency changed.

The existing PostgreSQL transport limiter now applies separate rolling
60-second quotas to public survey routes: 30 starts/redemptions, 300
writes/completions and 600 reads per client address across all survey IDs.
Quota identity is a keyed digest, independent of cookies and User-Agent.
The existing deployment proxy-trust setting controls address selection.
See [the operating contract](../DECISIONS.md#public-survey-request-quotas),
including shared-NAT and fixed-default limitations.

`tools/surveys/request_limits_live.py::main` uses actual HTTP handlers and
PostgreSQL, with the real member session established by the infrastructure
fixture. It creates and publishes a synthetic survey and starts a participation.
After each route category's first real attempt, it seeds only the preceding
quota counters up to one remaining permit using the transport-generated digest.
No survey handler, rate repository, lock or status is mocked.

The combined regression uses a reserved synthetic forwarded address for this
fixture, following the private API's trusted-proxy contract. Validation parity
cases similarly use distinct synthetic addresses because they represent
independent respondents. Quota tests retain one address across all their calls.
The checked-in proxy explicitly overwrites `X-Forwarded-For` with its peer's
address (`infra/proxy/Caddyfile`); direct fixture calls do not claim browser
forwarding-header abuse coverage.

- Two real concurrent starts compete for the final permit: one returns 200 and
  one 429. SQL finds exactly two total participations including the initial one.
- Further starts, a foreign survey ID and invitation redemption share the
  exhausted quota even with changed cookies and User-Agent. No participation
  is inserted by those rejected calls.
- Compact and `urn:uuid:` survey paths share the start/read quota; compact
  participation paths share the write quota. After expiry, actual compact/URN
  definition reads return 200, proving the test addresses supported routes.
- An accepted answer save and its idempotent replay exhaust the write quota.
  Rejected changed answers and completion leave the original answers,
  revision 2 and `in_progress` status unchanged in SQL.
- Read exhaustion also returns 429; authorized member survey access still works.
- Every rejected request has `request_rate_limited`, `Retry-After: 60` and no
  session/resume token in its error response. This checks response envelopes,
  not captured application logs.
- The fixture ages only the synthetic quota timestamps by 61 seconds. Actual
  start replay, restore and save replay succeed without adding participations.
  This proves window cutoff evaluation without a wall-clock sleep; it is not a
  real-time waiting benchmark.

Execution:

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" request-limits
```

Project `leonaid-surveys-833458328-23563`: the HTTP/SQL quota probe passed;
the Chromium identity/public-host foundation test passed (1 test, 2.3 s).
The complete command exited zero and verified removal of its owned resources.
It used fresh volumes, currently unused explicit subnets and no published host
ports. Sanitized output: [SURV-090-request-limits.json](assets/SURV-090-request-limits.json).
Only boolean/count/interval results are retained, with no participant identifiers,
answers or credentials.

Supporting regression: `tests/unit/test_http_security.py` passed all four tests
under the pinned UV/Python 3.13 image. The added test proves cookie/User-Agent
rotation and untrusted forwarding headers cannot reset the public quota
fingerprint, while distinct trusted addresses remain distinct. The existing
CSRF/origin and proxy-selection checks also pass. Scoped Ruff check, shell
syntax and diff whitespace checks pass.

The unit invocation (absolute checkout mount abbreviated as `$PWD`) was:

```sh
rtk proxy docker run --rm --network none -e PYTHONPATH=/workspace/src \
  -v "$PWD:/workspace" -w /workspace \
  ghcr.io/astral-sh/uv:0.11.17-python3.13-trixie-slim@sha256:6181d17d152967488408b4ced7b2930cc91c2b39adb7af6fb339965afce3404e \
  uv run --frozen --no-sync pytest tests/unit/test_http_security.py -q
```

Two intermediate combined `runner` invocations exited 1 and are not acceptance
evidence. `leonaid-surveys-833458328-24116` reached the new start quota while
creating unrelated validation cases through one client address. The fixture now
assigns each independent case a reserved synthetic proxy address; the production
quota was not increased. `leonaid-surveys-833458328-25029` passed all 192 parity
cases and validator stop/pause recovery, then failed the quota fixture's final
permit assertion. Review found that its seed counted historical attempts outside
the rolling window and depended on a potentially reused Docker client address.
The fixture now selects active-window counts and a dedicated synthetic address.
Both runs completed their cleanup traps before any test/runtime file was edited.
The final runtime matcher also covers compact and URN UUID spellings identified
during review; the first standalone run covered canonical UUID routes only.

Final acceptance command:

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" runner
```

Project `leonaid-surveys-833458328-26069` exited **0** on the final runtime and
fixtures. It passed the complete quota probe (including compact/URN paths),
192 actual API/PostgreSQL validation cases, response revision/idempotency and
timeout checks, worker restart, stopped and paused validator recovery, and
8 Chromium tests in 33.6 s. The browser tests are in
`tests/e2e/surveys-infrastructure.spec.mjs` and `tests/e2e/surveys-runner.spec.mjs`;
they include acknowledged text after closing mid-page, hidden-answer cleanup,
offline/reconnect, required conditions and matrix correction, and two-tab stale
saves with lost completion acknowledgement. Post-browser SQL and actual API /
worker restart probes retained the exact operation results and one durable
completion. Browser dependency: Playwright 1.54.1, locked container digest
`sha256:307ace13c8ba4349f790f4dfbc6eaa9fcafdeb29c218ff36129c7cacebb1e35f`.
Other service image versions are pinned in `infra/locks/images.env` and Compose;
Python and browser dependency lockfiles are unchanged.

The final run used fresh volumes, selected unused explicit subnets, published
no host ports, and verified owned-resource cleanup. Its sanitized quota JSON
replaces the earlier canonical-only artifact. No new screenshots or manual
visual/a11y acceptance are claimed. Existing httpx per-request-cookie
deprecation warnings were non-failing. The full SURV-090 and SURV-100 gates remain
open for the criteria identified above and in PLAN.md.
