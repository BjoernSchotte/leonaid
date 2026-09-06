# SURV-050 — Timeout settings and durable classification

Baseline: `89a6b69` plus this commit's timeout API, migration, worker and live
checks. This is an incremental proof; SURV-050 is not fully accepted.

## Task ledger

| Task | Required acceptance | Delivery / named evidence | Acceptance / remaining gap |
|---|---|---|---|
| 050.1 | A3, A5 | Existing runner and [SURV-010 browser proof](SURV-010.md#browser-autosave-and-recovery-proof) | Full runner acceptance remains open |
| 050.2 | A1, A4 | Existing revision/idempotency contracts; timeout test repeats completion | Full restart/reordering/two-tab matrix remains open |
| 050.3 | A2, A5 | Timeout settings APIs, snapshot preservation, real classification worker and effective-status view; `tools/surveys/timeouts.py prepare/recover` | Backend delivery proven; A2 remains open for actual analysis integration under SURV-070 |
| 050.4 | A3, A4, A5 | Existing protected restore and [SURV-020 reload evidence](SURV-020.md#browser-rendering-and-restoration-disposition) | Full conflict/recovery acceptance remains open |
| 050.T1 | A1, A2 | Real worker stop/restart, settings/replay checks and delayed classification below | Partial: complete restart/concurrency and analysis coverage remain open |
| 050.T2 | A3, A4, A5 | Seven runner browser scenarios; existing A5 is preserved | Two-tab and lost-completion-acknowledgement journey remains open |

## Implementation contract

Migration `0028_survey_timeouts` adds a global settings operation ledger, an
effective-status view and an index for pending participation activity times.
It does not rewrite answer data. Global settings require an active system
administrator; survey overrides require existing design authorization. Both
use optimistic revisions and durable replay, and reject invalid timeout values.
The summary revision governs overrides; draft revisions remain independent.
See [the timeout decision](../DECISIONS.md#timeout-settings-and-effective-status-contract)
for API paths, limits, inheritance, sweep intervals and analysis requirements.

The worker runs the classifier independently of invoice/mail outbox throughput.
Each transaction updates at most 1000 rows, skips locked rows and changes status
only. The database holds deadlines and answer timestamps; no memory-only timer
is needed for restart recovery. Respondent reads evaluate the effective status
even while the worker is stopped. The new SQL view exposes that same calculation
for future aggregate queries. This does not prove the still-unimplemented
analysis endpoints, nor does it close 050.A2 on their behalf.

## Live scenarios

Command: `./leonaid test-surveys-runner`, isolated project
`leonaid-surveys-833458328-83559`. The harness builds the actual API and platform
worker, migrates a fresh database, seeds a real authenticated administrator and
stops the actual worker before `tools/surveys/timeouts.py prepare`.

`prepare` exercises the real FastAPI and PostgreSQL paths:

- Reads the default and changes it to 20 seconds; an exact retry returns the
  original response. Changed-payload replay and stale revision return 409.
- Rejects zero, negative, over-limit, boolean, fractional and null global values
  with 422, preserving the last valid settings. Unauthenticated access is 401.
- Creates one participation at 20 seconds, changes the default to 40, creates
  another, applies a 3-second survey override, creates a third and removes the
  override before a fourth. SQL verifies the four immutable effective values
  are 20, 40, 3 and 40. Override replay succeeds; stale revision conflicts.
- Seeds a second real authenticated member without grants. Global reads/writes
  return 403 and a foreign survey override returns 404; settings and survey
  summary remain unchanged. The temporary member is then removed.
- Saves a synthetic answer, then injects an already elapsed deadline using
  PostgreSQL statement time. With the real worker stopped, stored status remains
  `in_progress`, while the response API and SQL effective-status view report
  `partial`.
- Saves unchanged answers on a different page. The page/revision update is
  accepted, but the answer timestamp and content remain unchanged; the effective
  response is still partial. The snapshot is retained for restart verification.

The harness starts and waits for the real platform worker, then executes
`tools/surveys/timeouts.py recover`:

- Polls PostgreSQL until the worker persists `partial`, asserting unchanged
  answers, revision and timestamp.
- Changes an answer through the public API. The same participation returns to
  `in_progress`, advances exactly one revision and can complete. Repeating the
  completion operation returns the original result.
- Makes the completed row's activity timestamp old, waits across the five-second
  sweep interval, and verifies completed status, answers and revision survive.
  All four participations still exist: timeout did not delete data.
- Restores the test's original global default and deletes its synthetic survey.
  Resume credentials/state are kept only in the harness's temporary directory.

Both phases passed. This supplies backend evidence toward 050.S2 and 050.A2;
those remain open until the actual analysis consumer proves effective-status
filters and denominators with worker lag.

## Supporting checks and remaining acceptance

`./leonaid test-surveys-core` exited zero: 168 actual SurveyJS/reference
comparisons, 23 Python tests and three coordinator tests with 17 assertions.
Pinned Python 3.13/uv tooling ran Ruff on all changed Python files successfully;
Mypy reported no issues in the four changed application source files. Exact
runtime images remain pinned in `infra/locks/images.env`; no dependency or
license change was introduced.

The full runner command exited **0**. All seven Chromium scenarios passed in
23.9s, including the existing abandon/timeout/resume completion journey (050.A5).
The harness also passed all 192 API/PostgreSQL validation cases and both
stopped/paused-validator recovery checks. Seven unused explicit subnets were
selected, no host ports were published, and container/volume/network teardown
completed before successful exit. No full analysis, settings UI,
large-backlog performance or arbitrary concurrency claim follows from the
bounded scenarios above.
