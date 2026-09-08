# Task acceptance template

Use this template within `proofs/SURV-xxx.md`. It defines the evidence to collect;
it is not a test result. Preserve the task and acceptance IDs from [PLAN.md](PLAN.md).
Own license decision remains **UNDEFINED**.

## Task ledger

Create one row for every implementation and test task in the work package.
Reconcile each implementation row with [IMPLEMENTATION-TASKS.md](IMPLEMENTATION-TASKS.md),
including the required integration and E2E assertions before marking it accepted.
Replace placeholders with actual values; leave unimplemented items open.

| Task ID | Deliverable / changed paths | Required acceptance IDs | Named tests and assertion locations | Implementation delivered | Acceptance result / remaining gap |
|---|---|---|---|---|---|
| `<xxx.n or xxx.Tn>` | `<concrete artifact>` | `<all IDs linked by the plan>` | `<path and test name>` | `<yes/no>` | `<open/passed/failed, reason>` |

An implementation checkbox means delivery only. Accept a task only when every
referenced criterion passes. A shared criterion may require several tests;
passing one of them is not sufficient. Preserve existing evidence when adding
new scenarios, and identify which revision each result describes.

## Scenario specification and result

Repeat this section for every independently named scenario required by a test
task. Define expected results before execution.

- **Task and acceptance IDs:** `<IDs>`
- **Test layer:** `<integration, browser E2E, contract, bundle, or manual render review>`
- **Test location:** `<file and test name; proposed until implemented>`
- **Prerequisites:** `<persona, survey lifecycle/version, fixture, persisted state>`
- **Action:** `<API operation or actual UI interaction; injected failure if relevant>`
- **Expected visible/API outcome:** `<specific values, state or rejection>`
- **Expected persisted outcome:** `<answers, revision, status, job/object state; justify if inapplicable>`
- **Negative/recovery assertions:** `<unauthorized access, invalid values, retry or concurrency behavior required by the criterion>`
- **Execution:** `<commit, exact command, pinned runtime versions, exit code>`
- **Observed result:** `<open/passed/failed; actual values and limitations>`
- **Artifacts:** `<sanitized evidence paths; never tokens or real respondent data>`

For E2E scenarios, also record browser/viewport, the UI path and the assertions
that prove the result after reload or a fresh session where required. Use real
services for persistence, permissions and exports. Direct API checks supplement
the UI journey; they do not replace the required user interactions.

For integration scenarios, record the actual services exercised and how the
authoritative state was inspected. Mock-only tests cannot satisfy integration
criteria. Record the Docker project, isolated networks/ports and cleanup result.

## Review before checking acceptance

- [ ] Every task row lists all acceptance IDs required by the plan.
- [ ] Every acceptance ID has named scenarios covering all stated outcomes.
- [ ] Integration and E2E scenarios required by the work package both ran successfully.
- [ ] Tests assert rejection and unchanged state where invalid writes must be atomic.
- [ ] Recovery/concurrency scenarios assert durable outcomes, not only HTTP success.
- [ ] Test commands exit nonzero on failed assertions; skipped cases remain open.
- [ ] Browser viewport and manual visual observations are identified separately.
- [ ] Evidence identifies the tested revision and successful isolated teardown.
- [ ] Each checked criterion has a result and evidence link; remaining gaps stay open.

Do not copy checked boxes from this template. Completion of this review does not
waive any scenario, dependency gate or final exit criterion in PLAN.md.
