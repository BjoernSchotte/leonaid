# SURV-070 — Aggregate engine and analysis integration

Baseline `0ac8da1` plus this increment, 2026-09-07. This increment implements the
neutral server aggregate engine and a bounded private adapter. **No SURV-070
implementation task or acceptance criterion is closed yet.** Persisted analysis
snapshots, authorized host queries/filters, charts and raw-response routes remain
to be integrated and tested.

## Task ledger

| Task | Delivered building block | Remaining acceptance |
|---|---|---|
| 070.1 | Strict question/batch DTOs with denominator invariants | Immutable snapshot persistence; actual status/version/date/test filters; worker-delay analysis consistency; A1/A2/A3 |
| 070.2 | `packages/surveys/src/analysis.ts`, private `/aggregate`, Python `aggregate_batch`, hand-calculated golden fixture | Integration into authorized selected-version snapshots and browser charts; A1/A3 |
| 070.3 | No delivery claim | Custom charts, accessible tables, separately authorized raw/free-text views; A2/A3/A4 |
| 070.T1 | Engine-level golden data and bounded adapter checks | Real persona/resource matrix, response status/version selection and immutable snapshots |
| 070.T2 | Existing packed-consumer and infrastructure regression only | Actual analysis filter/chart/table and raw-route-denial E2E journeys |

## Aggregate semantics

`aggregateApprovedSurvey` is exported through the neutral package's separate
`analysis` entrypoint. It creates/disposes the same SurveyJS model used by the
runner and uses `profileAnswerError` for partial answer validity. The host must
approve a stored initial-v1 definition before calling it. The function cannot
authorize a user or choose which responses belong in an analysis.

Every selected response increments either relevant or hidden for each question.
Relevant answers are partitioned into valid answered, unanswered and invalid.
Missing ratings/numbers remain missing. Author-defined choices retain scalar
type identity; response-created values never become buckets. Rating buckets
follow the configured scale, including fractional steps. Text/date contents are
never returned. Numeric fields provide sum, mean, minimum and maximum.

Choice percentages use valid answered participants. A participant selecting two
checkbox choices counts once in that denominator, so totals can exceed 100%.
Matrix rows have their own valid answered-cell denominator, missing-cell count
and invalid count. An invalid matrix answer is excluded as a whole; each row is
marked invalid for that response. Hidden matrices do not enter row denominators.

The initial NPS template convention is a 0–10 rating with step 1. Promoters are
9–10, detractors 0–6, and NPS is `100 * (promoters - detractors) / valid answered`.
Other scales receive no NPS metric. Empty means, NPS and percentages are null.
The engine retains counts/sums so future batch combination can recompute metrics
from denominators, rather than incorrectly averaging percentages or NPS values.

The private service exposes `/aggregate` alongside its unchanged `/validate`
operation. `aggregate_batch` approves the definition, rejects unknown answer
fields and limits a single batch to 100 records and a 550,000-byte JSON body.
This is a processing-batch limit, not the final survey response limit. Large
survey batching/snapshot orchestration remains pending. The adapter validates
strict DTOs, finite numeric values, matching question IDs and denominator sums.
Errors expose a generic unavailable outcome and no SurveyJS answer diagnostics.

## Golden and package evidence

`tests/fixtures/surveys/analysis-golden.json` deliberately contains five synthetic
answer states, including invalid legacy values and hidden stale text. Assertions
are hand-calculated independently of the implementation:

- Checkbox counts are 2 and 1 over two valid respondents: 100% and 50%.
- NPS has three valid values (10, 9, 0), one invalid value and one missing value;
  mean is 19/3 and NPS is 100/3.
- Numeric values 10 and 20 give sum 30, mean 15, min 10 and max 20.
- Conditional page/question visibility produces distinct relevant/hidden counts.
- Matrix row denominators are two and one valid cells; missing and invalid
  responses have separate counts.
- Text and date values, hidden stale text and invalid choice strings are absent
  from aggregate output. Empty batches retain author buckets with null metrics.
- Type-sensitive scalar choices and fractional-rating boundaries stay distinct;
  unknown answer keys are rejected.

`./leonaid test-surveys-core` exited **0**: 168 existing SurveyJS/Python
comparisons, 23 Python tests and eight Bun tests with 97 assertions (including
four new aggregate tests). The first new fractional-rating test expected a value
slightly above the configured maximum to count. Correcting the fixture to the
shared validation semantics now explicitly verifies that value is invalid.

Strict TypeScript on the new analysis entrypoint, Mypy on both changed Python
application/adapter files and Ruff on the changed Python files passed.

`./leonaid test-surveys-package` passed as
`surveys-package-833458328-10900`, exit **0**. The external consumer imports
`@leonaid/surveys/analysis` from the installed tarball, checks the NPS denominator
and absence of synthetic private text, and verifies analysis code is absent from
the respondent bundle. Existing browser persistence/restart phases passed in
2.8s and 901ms; isolated resources were removed. Dependency versions and MIT/OFL
notices remain unchanged. Own license remains UNDEFINED/manifest UNLICENSED.
[Packed-consumer inventory and entrypoint proof](assets/SURV-070-package.json).

## Private HTTP engine proof

`/bin/sh tools/surveys/aggregate-engine.sh` passed as
`surveys-engine-833458328-12074`, exit **0**. It bundles the service using the
installed pinned SurveyJS 3.0.3 modules and starts a separate private Docker
network without host ports. The actual Python adapter calls the Bun HTTP service:
golden counts/NPS/matrix/relevance, no raw text, empty results, 100-record batches,
over-count/over-size rejection and unknown-key rejection all pass. Stopping the
actual service produces `survey_analysis_unavailable`; starting it again repeats
the full golden proof successfully. Its container and network were removed.
[Sanitized aggregate result](assets/SURV-070-aggregates.json).

The separate `./leonaid test-surveys-aggregates` run,
`leonaid-surveys-833458328-10568`, is still pending in fresh-image dependency
installation at this commit. It is not recorded as passed and was not replaced
or restarted. The focused service test above does not prove the full fresh-image
build or the infrastructure browser regression; retain that distinction when
reconciling the next run.

## Acceptance boundary

The engine's input records are already selected by its caller. It does not yet
prove 070.A1's status/version isolation, 070.A2's actual aggregate-only persona
routes, or 070.A3/A4's analysis UI. In particular 050.A2 remains open: read-time
timeout classification must still be exercised through the future real analysis
query. The current infrastructure browser test is not an analysis UI test.
