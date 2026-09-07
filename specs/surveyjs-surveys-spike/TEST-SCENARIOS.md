# Surveys — checkable integration and E2E scenarios

This is part of [PLAN.md](PLAN.md), not a record of passing tests. Own license:
**UNDEFINED**. Commercial SurveyJS components remain excluded; OFL font assets
are allowed under the notice requirements in the dependency review.

Each checkbox is a test implementation **and successful execution** task. Link
its ID, named test, tested revision and actual result from the owning work-package
proof before checking it. Existing proofs may satisfy a scenario after review;
these initially open boxes do not reset the plan's existing acceptance status.
Use [TASK-ACCEPTANCE.md](TASK-ACCEPTANCE.md) for execution records and limitations.

Integration uses real services; E2E uses actual UI interactions with real
persistence and authorization. Every run records isolated Docker project,
networks, ports, synthetic fixtures and cleanup. Assert authoritative state in
addition to UI/API outcomes. Skipped scenarios remain open. The scenarios below
decompose the plan; they do not replace any of its acceptance requirements.

## SURV-000 — Contracts and infrastructure

- [ ] **000.S1 · Integration · 000.T1 → 000.A1:** Exercise versioned request/response and error fixtures for every write; authorization, invalid data, stale revisions and duplicate operations produce the documented result without unintended writes. Cover C-01–C-15 explicitly.
- [ ] **000.S2 · Integration · 000.T1 → 000.A2:** Start with empty volumes, migrate and seed every required persona; perform a real API/database roundtrip and verify persisted values and isolated teardown.
- [ ] **000.S3 · Dependency check · 000.T1 → 000.A4:** Inspect exact resolved software/assets; prohibited and unknown-license fixtures fail the command, allowed packages retain notices and own license stays UNDEFINED.
- [ ] **000.S4 · E2E · 000.T2 → 000.A3:** Authenticate a synthetic member, reach both member/public hosts and open the public survey shell; deliberately fail an assertion and verify nonzero exit, sanitized diagnostics and cleanup.

## SURV-010 — Autosave and validation

- [ ] **010.S1 · Integration · 010.T1 → 010.A1:** Run identical supported definitions/answers through client and authoritative backend validation; assert equal relevance/cleaned answers and reject forged values and unsupported definitions through the actual write endpoint.
- [ ] **010.S2 · Integration · 010.T1 → 010.A2:** Save incomplete required answers successfully; reject invalid supplied values and incomplete completion with the documented error and unchanged persisted revision/status on rejection.
- [ ] **010.S3 · Integration · 010.T1 → 010.A5:** Expire a short configured timeout, read the participation as partial, resume and complete it; the same identity and acknowledged answers survive.
- [ ] **010.S4 · E2E · 010.T2 → 010.A3:** Type without blur, wait for acknowledgement, close the browser context and restore using valid resume access; exact text remains persisted without a duplicate participation.
- [ ] **010.S5 · E2E · 010.T2 → 010.A4:** Answer conditional questions, change their controlling answers and navigate/reload; hidden answers are removed according to the contract from browser and database state.

## SURV-020 — Independent package

Reconciled against [SURV-020 proof](proofs/SURV-020.md#browser-rendering-and-restoration-disposition).

- [x] **020.S1 · Integration · 020.T1 → 020.A1:** Install the packed artifact outside workspace resolution and save/load through the independent host's real adapter; no LeonAid internal import is required.
- [x] **020.S2 · Bundle check · 020.T1 → 020.A2:** Inspect packed files and respondent bundle; editor code and commercial components are absent, and required software/font notices are present.
- [x] **020.S3 · E2E · 020.T2 → 020.A3:** Submit a multipage questionnaire with host translations and styling; translated validation/save messages appear and adjacent host controls retain their styles.
- [x] **020.S4 · E2E · 020.T2 → 020.A4:** Reload and restore in the chosen rendering mode; no unintended write or duplicate participation occurs, private state is not publicly cached, and the observed SSR/browser-only boundary is documented.

## SURV-030 — Lifecycle and versions

- [ ] **030.S1 · Integration · 030.T1 → 030.A1:** Migrate both empty and baseline databases; enumerate every allowed/forbidden lifecycle edge from PLAN section 5 and assert resulting state or rejection without mutation.
- [ ] **030.S2 · Integration · 030.T1 → 030.A2:** Race draft saves/publication and end/completion using controlled concurrency; revisions and immutable versions stay consistent and the transaction cutoff determines the accepted response.
- [ ] **030.S3 · Integration · 030.T1 → 030.A3:** Publish v2 while v1 participations exist and duplicate the survey; old participations retain v1, new ones use v2, and the duplicate contains no answers, recipients or credentials.
- [x] **030.S4 · E2E · 030.T2 → 030.A4:** After SURV-060 supplies the member UI, create, publish, end, archive, trash and restore; UI/database states agree and the public survey remains closed after restore. [Evidence](proofs/SURV-060.md).

- [x] **030.S5 · Integration · 030.T1 → 030.A1:** Configure and replay a future end, reject invalid/past/stale requests, then advance the fixture deadline with the real worker stopped. Late start/save/completion and reopening fail; restart the worker and verify one durable closure with unchanged partial/completed answers and participation revisions. [Evidence](proofs/SURV-030.md#scheduled-closure-through-the-backend-and-worker).
- [x] **030.S6 · E2E · 030.T2 → 030.A4:** Set a future end in the member UI, verify the persisted timestamp, reload the field, remove the end and verify persisted null before exercising the manual lifecycle. [Evidence](proofs/SURV-030.md#scheduled-closure-through-the-backend-and-worker).

## SURV-040 — Editor

- [ ] **040.S1 · Integration · 040.T1 → 040.A1:** Persist and reload edited definitions including safe unknown regions; stable IDs and unknown data survive, while a stale draft write reports conflict without overwriting the newer draft.
- [ ] **040.S2 · Integration · 040.T1 → 040.A2:** Import unsupported and unsafe definitions and attempt publication through the API; publication is blocked with field/question-specific diagnostics.
- [ ] **040.S3 · E2E · 040.T2 → 040.A3:** Author and publish both complete sample questionnaires without JSON input; configure initial types, bounds and guided conditions, reorder pages/questions, preview and reload the saved definition.
- [ ] **040.S4 · E2E · 040.T2 → 040.A4:** Perform core authoring and error recovery by keyboard, including reordering; focus and accessible labels remain usable, with automated checks and separately recorded manual observations.
- [ ] **040.S5 · E2E · 040.T2 → 040.A5:** Exercise undo/redo and interrupt draft saving; pending changes are never labelled saved, and reconnect/reload shows the correctly acknowledged definition.

## SURV-050 — Runner and recovery

Reconciled against [runner restart and tab-loss evidence](proofs/SURV-050.md#process-restart-and-untransmitted-tab-loss).

- [x] **050.S1 · Integration · 050.T1 → 050.A1:** Duplicate/reorder saves and retry completion across API/worker restarts; older writes cannot replace newer data, completed state is terminal and retries create no second logical completion.
- [x] **050.S2 · Integration · 050.T1 → 050.A2:** Exercise default/override timeout snapshots, unchanged requests and delayed worker classification; only server-observed answer changes extend inactivity and classification never removes responses. [Accepted evidence](proofs/SURV-050.md#analysis-consumer-acceptance).
- [x] **050.S3 · E2E · 050.T2 → 050.A3:** Disconnect mid-page, type and reconnect; pending status remains truthful and acknowledged answers survive reload. Verify that tab closure does not promise recovery of unsent memory-only edits.
- [x] **050.S4 · E2E · 050.T2 → 050.A4:** Edit one participation in two tabs, delay requests and lose the completion acknowledgement; show conflicts, preserve newer data and finish with exactly one completed participation after retry. [Evidence](proofs/SURV-050.md#two-tab-ordering-and-lost-completion-acknowledgement).
- [x] **050.S5 · E2E · 050.T2 → 050.A5:** Abandon a multipage survey, expire the short timeout and resume with valid access; previous answers and identity remain intact and completion succeeds.

## SURV-060 — Module and permissions

- [ ] **060.S1 · Integration · 060.T1 → 060.A1:** Exercise the persona/resource matrix against lists, counts and direct read/write routes; foreign IDs and unauthorized operations reveal no protected data and change no state. Anonymous answers have no CRM/order association.
- [ ] **060.S2 · Integration · 060.T1 → 060.A2:** Retry invitation processing and expire/revoke access; one logical invitation remains, invalid access is rejected and seeded credentials appear in neither captured logs nor exports.
- [x] **060.S3 · E2E · 060.T2 → 060.A3:** Send an invitation from the member UI through the real worker, retrieve it from Mailpit and complete its linked questionnaire; a revoked invitation subsequently fails. [Evidence](proofs/SURV-060.md#personal-invitations).
- [ ] **060.S4 · E2E · 060.T2 → 060.A4:** Navigate action-linked and standalone surveys with different personas; visible actions match permissions and direct navigation/API calls cannot bypass them.
- [x] **060.S5 · E2E · 060.T2 → 060.A5:** Change the timeout in the backend UI; a new participation uses it and an existing participation retains its effective setting. Preview/test responses remain excluded from collected-response analysis.

## SURV-070 — Analysis

- [x] **070.S1 · Integration · 070.T1 → 070.A1:** Seed hand-calculated distributions, ratings, NPS, matrix and multiselect results with partial/hidden/missing answers and multiple versions; every count/denominator matches, including empty results, without implicit version merging. [Accepted evidence](proofs/SURV-070.md#immutable-analysis-snapshots).
- [x] **070.S2 · Integration · 070.T1 → 070.A2:** Query aggregates with aggregate-only and unauthorized personas; reject forbidden resources/filters and exclude raw text and recipient identities from all aggregate payloads. [Accepted evidence](proofs/SURV-070.md#immutable-analysis-snapshots).
- [x] **070.S3 · E2E · 070.T2 → 070.A3:** Switch status/version/date filters and compare charts/tables with the same snapshot; labels, counts, empty states and zero denominators stay consistent. [Accepted evidence](proofs/SURV-070.md#analysis-ui-and-neutral-result-components).
- [x] **070.S4 · E2E · 070.T2 → 070.A4:** Reach equivalent table data by keyboard; an aggregate-only member cannot open individual-response or free-text routes. [Accepted evidence](proofs/SURV-070.md#authorized-raw-response-browser-views).

## SURV-080 — Exports

- [x] **080.S1 · Integration · 080.T1 → 080.A1:** Generate response CSV/XLSX and analysis XLSX/PDF through the real worker/storage pipeline; parse values and metadata against the golden snapshot and assert that access tokens are absent. [Accepted evidence](proofs/SURV-080.md#worker-recovery-and-tabular-task-acceptance).
- [x] **080.S2 · Integration · 080.T1 → 080.A2:** Export formula-like text, Unicode, empty values and matrices; text remains inert and values survive parsing. Inject renderer failure and retry without a false successful job. [Accepted evidence](proofs/SURV-080.md#worker-recovery-and-tabular-task-acceptance).
- [x] **080.S3 · Integration · 080.T1 → 080.A3:** Revoke permissions or delete the survey before queued processing and before download; both queued and existing artifacts become inaccessible and object storage is not public. [Accepted evidence](proofs/SURV-080.md#permission-boundary-acceptance).
- [x] **080.S4 · E2E · 080.T2 → 080.A4:** Request all four export products through the analysis UI, observe job states and download through authenticated routes; downloaded values equal the displayed snapshot. [Accepted evidence](proofs/SURV-080.md#populated-browser-exports-and-permission-revocation).
- [x] **080.S5 · Render review · 080.T2 → 080.A5:** Render PDF pages and XLSX charts with long/Unicode fixtures; inspect fonts, legends, clipping and pagination, retaining synthetic evidence and identifying manual observations. [Accepted evidence](proofs/SURV-080.md#consolidated-render-acceptance).
- [x] **080.S6 · E2E · 080.T2 → 080.A6:** Permit aggregate-report export but deny raw export for a persona; UI, direct job requests and direct downloads all enforce that distinction. [Accepted evidence](proofs/SURV-080.md#populated-browser-exports-and-permission-revocation).

## SURV-090 — Deletion and operations

- [ ] **090.S1 · Integration · 090.T1 → 090.A1:** Race trash/permanent deletion against autosave, completion and exports; no late operation recreates deleted content or leaves a downloadable artifact.
- [x] **090.S2 · Integration · 090.T1 → 090.A2:** Interrupt permanent deletion between database/object-store steps and retry; every targeted definition, answer, association and export is removed and repeated processing is safe. [Evidence](proofs/SURV-090.md#durable-erasure-and-process-crash-recovery).
- [ ] **090.S3 · Integration · 090.T1 → 090.A3:** Restore a real synthetic backup and reapply content-free deletion records; previously deleted data is inaccessible and removed. Independently verify inactivity alone deletes nothing.
- [ ] **090.S4 · Integration · 090.T1 → 090.A4:** Exceed configured payload/request/export limits; errors are predictable and no partial writes occur. Scan captured logs for seeded answer/credential markers.
- [x] **090.S4a · Integration · 090.3a → 090.A4 (public requests):** Race two requests for the final start permit; test start/redeem, save/complete and read exhaustion, cookie/User-Agent rotation and cross-survey quota sharing. Assert HTTP 429 with Retry-After, no rejected participation or answer writes, independent member access and successful idempotent recovery after quota expiry. [Live evidence](proofs/SURV-090.md#public-request-quota-acceptance). Other 090.S4 requirements remain open.
- [x] **090.S4b · Integration · 090.3b → 090.A4 (payloads/logs):** Accept exact 1-MiB wire and 256-KiB definition/answer boundaries; reject one-byte excess including chunked HTTP without partial SQL writes. Scan actual API/worker/validator logs for seeded answer and credential markers; supporting ASGI tests cover misleading Content-Length and disconnect. [Live evidence](proofs/SURV-090.md#payload-boundaries-and-participation-log-acceptance). Export-related 090.S4 coverage remains open.
- [ ] **090.S5 · E2E · 090.T2 → 090.A5:** Trash while a respondent page is open; subsequent saving fails visibly, invitations/downloads stop, and restoring the survey does not silently reopen participation.

## SURV-100 — Final acceptance

- [ ] **100.S1 · Integration · 100.T1 → 100.A1:** Run the aggregate gate from empty volumes and repeat it; migrations, worker restart, object storage and recovery pass with isolated cleanup on both runs.
- [ ] **100.S2 · Regression · 100.T1 → 100.A3:** Run affected identity, policy, public-action, public-order and integration suites; record results and justify any excluded suite by an untouched boundary.
- [ ] **100.S3 · Evidence review · 100.T1 → 100.A4, 100.A5:** Reconcile every task and C-01–C-15 capability with named proof; verify the packed consumer, permissive dependencies/OFL notices and sanitized artifacts. Open prerequisites prevent a full-completion claim.
- [ ] **100.S4 · E2E · 100.T2 → 100.A2:** Execute both complete sample journeys on desktop and mobile: author, publish, invite/open, abandon/resume, complete, analyze, download every export, archive and delete; assert version isolation and permission boundaries throughout.
