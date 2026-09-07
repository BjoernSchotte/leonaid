# SURV-080 — Export implementation evidence

The initial tabular increment started at `8add0a6`; subsequent baselines are below.
**080.1 is accepted; 080.2 and 080.3 remain open.**
Criteria 080.A1, A2, A4 and A6 are proven below. Permission-race and workbook
render gates remain open; SURV-080 is not complete. Earlier sections record the
evidence and limitations of their respective increments.

## Task ledger

| Task | Delivered building block | Remaining acceptance |
|---|---|---|
| 080.1 | CSV, response XLSX and analysis XLSX through real worker/private storage and parsed API downloads | Export UI and complete raw-export denial journey |
| 080.2 | Native workbook charts, server-side vector PDF charts and dedicated Typst report; PDF visual review | Export UI and rendered XLSX review |
| 080.3 | Durable jobs, current permission checks, private storage and protected downloads | Failure/retry/crash tests and complete revocation/deletion matrix |
| 080.T1 | 18 tabular artifact tests, four real export pipelines, controlled PDF glyph failure and 22 database invariants | Complete permission matrix and failure/recovery integration |
| 080.T2 | Normal, long-label, empty and actual-worker PDF pages visually inspected | All browser export journeys and XLSX rendering review |

## Rendering contract

`SurveyExportSource` carries the immutable AnalysisSnapshot, a host-supplied
captured document title and optional typed private responses. `SurveyExportArtifact`
returns bytes, filename, MIME type, render version and SHA-256. It does not reuse
invoice-domain documents or perform authorization. The worker loads private
responses only for a permitted raw-export product and freezes its document title
as part of the job input.

`render_tabular` supports responses_csv, responses_xlsx and analysis_xlsx using
Python CSV and the already pinned openpyxl 3.1.5 dependency. It rejects missing,
duplicated or status-inconsistent raw selections. Analysis workbook generation
uses only the aggregate snapshot, even when the caller supplies private rows.

### CSV

UTF-8 with BOM, standard CSV quoting and CRLF records. The rectangular header
contains `record_type`, snapshot/filter/version metadata, participation metadata
and stable question columns. One `metadata` record always precedes the `response`
records, preserving filter context even when no responses match. Consumers must
select `record_type=response` when counting or importing participations; the
metadata record is not a participation. All rows have the same column structure.

Each question has `q:ID` and `q:ID:type`. Types distinguish missing, null, string,
number, boolean, array and object. Structured values use canonical JSON; matrix
row columns supplement the complete matrix value. Missing and null cells are
blank but remain distinguishable by type. Empty strings have type string.
Metadata repeats with response rows so concatenated/filter-selected rows retain
context. CSV prefixes formula-like and apostrophe-leading strings with one
apostrophe. Strip that single prefix when decoding string values; leading
apostrophes are themselves escaped so this is reversible. Whitespace and control
prefixes cannot hide formula operators from the guard.

### XLSX

Response workbooks contain Metadata, Questions and Responses. The question
catalogue preserves typed choice values and authored labels, including matrix
rows. Response columns use the same explicit value types as CSV; XLSX readers
that return blank for an empty string can reconstruct it from the string type.
Large integers and raw floats beyond Excel's 15-digit numeric precision are
stored as exact text with type number. Ordinary numbers remain numeric cells.

Analysis workbooks contain Metadata, Questions, Metrics, Distributions, Matrix
rows, Charts and Last page. Counts, sums, means, NPS, missing/hidden/invalid values
and denominators come from the same stored snapshot. Native horizontal bar charts
reference the distribution table's percentage and label cells. The implementation
follows the upstream [bar-chart API](https://openpyxl.readthedocs.io/en/stable/charts/bar.html);
actual visual rendering remains an explicit acceptance gate.

All string cells are explicitly strings, with a quote-prefix hint where useful;
no user text becomes a formula or hyperlink. Unsupported XML characters and
strings longer than 32,767 characters cause `cell_text_unrepresentable`, without
returning an artifact or silently truncating data. This is an enforced format
limit to surface through the future job error state, not an accepted full export
error/retry workflow. ZIP timestamps and document creation/modification times are
normalized to ensure identical XLSX bytes across retries and writer-clock changes.

## Artifact-level verification

Pinned Python runtime command:

```sh
uv run --frozen --no-sync pytest tests/unit/test_survey_tabular_exports.py -q
```

The 18 tests create actual CSV/XLSX bytes and re-open them with independent CSV
and openpyxl readers. They verify hand-calculated NPS 100/3, numeric mean 15,
multiselect counts 2/1 and percentages 100/50, matrix row denominators, empty
results, metadata, Unicode/newlines, malformed raw selections, typed large
numbers, all formula prefixes, reversible apostrophes and no raw text in reports.
Five chart parts reference the aggregate distribution sheet. The tests explicitly
change the writer clock by a decade and still obtain identical bytes. They do
not claim that native charts were visually rendered.

The initial test found XLSX empty-string ambiguity; explicit type columns fix
that representation loss. A later clock fixture initially patched a module as a
class; correcting that fixture made the intended clock-drift check executable.
Mypy also required an explicit optional-string chart-group type. Final tests,
Mypy, Ruff and whitespace checks pass. No runtime dependency or own-license
selection was introduced; own license remains UNDEFINED.

Revalidated on 2026-09-07 against the five-file working-tree increment on
`8add0a6`, using the pinned container
`ghcr.io/astral-sh/uv:0.11.17-python3.13-trixie-slim@sha256:6181d17d152967488408b4ced7b2930cc91c2b39adb7af6fb339965afce3404e`.
The repository was mounted at `/workspace`, working directory `/workspace`,
with `PYTHONPATH=/workspace/src`. All containers used `--rm`, with no published
ports or application service stack.

| Command inside the pinned container | Observed result |
|---|---|
| `uv run --frozen --no-sync pytest tests/unit/test_survey_tabular_exports.py -q` | Exit 0; 18 passed in 0.43 s |
| `uv run --frozen --no-sync mypy src/leonaid/application/surveys/export_rendering.py src/leonaid/adapters/survey_tabular_exports.py` | Exit 0; two source files passed |
| `uv run --frozen --no-sync ruff check src/leonaid/application/surveys/export_rendering.py src/leonaid/adapters/survey_tabular_exports.py tests/unit/test_survey_tabular_exports.py` | Exit 0; all checks passed |

These commands exercise artifact rendering only, not the required isolated
application integration or browser journeys.

## Next required integration

Add the export UI and explicit failure/recovery scenarios, then execute all four
real worker/storage/browser products. Only those
passing integration, E2E and rendering gates can close the still-open SURV-080
criteria. PDF rendering is now implemented and proven through the worker; the
export UI, complete XLSX visual review and recovery matrix remain open.

## Durable tabular jobs — 2026-09-07

Baseline `08a3a19` plus the export-job working-tree increment. The API creates an
immutable request linked to the existing analysis snapshot and an outbox event
in one transaction. Exact operation replay returns the same job identity;
changed inputs conflict. Job titles are captured at request time. Raw response
projections are loaded only for raw products after `export_raw` authorization;
report products require `export_reports`. Test snapshots additionally require
design permission. Job reads/downloads are scoped to the requesting account.

The worker resolves the requesting account, roles, current action memberships
and survey grants from PostgreSQL. It checks them before rendering and again
before making the artifact available. Downloads check current permission before
and after reading the exact stored object version. They return bytes through the
authenticated API with `no-store`, attachment disposition and `nosniff`; neither
storage locations nor presigned URLs are returned. Stored bytes and hashes are
verified. Worker errors are reduced to a stable content-free code. Revoked queued
requests are cancelled. Object references survive cancellation and survey/snapshot
deletion is blocked until controlled retention removes export jobs and objects.

`tools/surveys/exports_live.py` ran in the actual API/worker/RustFS stack via:

```sh
rtk proxy sh tools/surveys/infrastructure.sh /Users/bjoern/.codex/worktrees/497a/leonaid exports
```

Project `leonaid-surveys-833458328-37646`, exit 0, all owned resources removed.
Seven unused explicit subnets, no published host ports. Observed assertions:

- Three tabular jobs survived the deliberately stopped worker and were processed
  after its restart. CSV rows and workbook metrics matched the frozen snapshot;
  actual workbook chart definitions were present.
- Duplicate operation IDs produced one job; changed products conflicted. Pending
  downloads returned 409. Foreign snapshot requests returned 404 and unauthenticated
  reads returned 401. Stored job inputs rejected SQL mutation.
- A report-only member could queue a report but could not queue raw data. Revoking
  that grant before processing cancelled the job without producing an object.
- Anonymous RustFS object reads were denied. After a survey was trashed through
  the real API, every existing job read and download returned 404. Direct survey
  deletion could not orphan the object references.
- Outbox payloads contained only empty JSON objects; job identities are carried
  by the outbox aggregate. Download bodies contained no synthetic session tokens.
- The existing member/public infrastructure browser test passed (1.7 s). This
  is a host regression check, **not** the still-required export UI journey.

Sanitized result: [tabular API proof](assets/SURV-080-tabular-api.json).

Migration command:

```sh
rtk proxy sh tools/surveys/migrations.sh /Users/bjoern/.codex/worktrees/497a/leonaid
```

Project `surveys-migrations-833458328-37939`, exit 0 and verified resource cleanup.
Both empty and populated databases reached `0031_survey_exports` and repeated
migration safely. Twenty-two actual PostgreSQL invariants passed, including
immutable export input, complete metadata before availability, cross-survey
snapshot rejection and retained object references. All 46 pre-survey table
fingerprints remained unchanged. Evidence: [empty](assets/SURV-080-migrations-empty.json),
[upgrade](assets/SURV-080-migrations-upgrade.json),
[baseline](assets/SURV-080-migrations-baseline.json).

The initial full-stack attempt (`37264`) exposed an import-time evaluation of
`asyncpg.Pool[Any]`; deferred annotations fixed API/worker startup. That attempt
failed and was cleaned up. It is not counted as a successful proof.

Final supporting checks: `pytest tests/unit/test_survey_tabular_exports.py
tests/unit/test_migration_policy.py -q` passed 20 tests in 0.50 s; Mypy passed
the five changed export/API/worker modules; Ruff passed all changed Python
modules and proof scripts. OpenAPI generation succeeded and the generated
`downloadSurveyExport` returns a `Blob`; `bun run typecheck:api-client` exited 0.
The binary OpenAPI description was added after the live run; it changes the
generated contract, not download execution. Proof links and whitespace checks
passed. No complete SURV-080 task or acceptance checkbox has been checked.

## Dedicated Typst reports and all four products — 2026-09-07

Baseline `84f4c85` plus the PDF increment. `TypstSurveyRenderer` and
`survey-analysis-v1.typ` use the existing pinned Typst 0.13.1 binary and pypdf
5.8.0 dependency. No new dependency, external chart service, commercial component
or own-license choice is introduced. The report receives aggregate presentation
data only; even explicitly supplying private response rows leaves its bytes
unchanged. Author strings are JSON data, never evaluated Typst code.

Reports include frozen selection/version/date metadata, scoped status totals,
per-question relevant/answered/unanswered/hidden/invalid counts, sums, means,
extrema, NPS, matrix row completeness, vector horizontal percentage bars with
count/denominator/table alternatives, and last saved page counts. German labels
explain denominators and round displayed metrics to at most two decimal places.
Missing percentages read `Nicht verfügbar`, rather than falsely reporting zero.
Question headings remain with their first count table. Chart tables repeat their
question number and distribution context across pages; ordinary long labels
remain with the corresponding row. The implementation uses the documented
[Typst table cell and repeated-header controls](https://typst.app/docs/reference/model/table/).

`python tools/surveys/pdf_render.py` ran against the pinned Dockerfile.core runtime
with the worktree mounted at `/workspace`, exit 0. Normal (4 pages), long-label
(8 pages) and empty (4 pages) reports have byte-identical repeated rendering.
The script parses actual PDFs, verifies IDs and selected golden metrics (NPS
33.33, mean 15), checks page numbering and absence of active annotations/private
text, proves literal handling of `#panic(...)`/HTML text, and exercises stable
errors for a wrong runtime and missing template. Results and hashes:
[render proof](assets/SURV-080-pdf-render.json).

### Font correctness and visual review

An additional Japanese-title probe revealed that Typst silently emits replacement
boxes without compiler warnings. The final adapter therefore inspects actual PDF
text-showing operators using pypdf and rejects glyph zero in the pinned CFF
Identity-H font profile, including form content streams. Unknown font profiles
also fail verification. A real Typst Japanese-title regression now raises
`typst_font_glyph_missing`; ordinary German/Greek Unicode fixtures pass with
unchanged bytes. This is explicit font coverage, **not universal Unicode font
support**. Adding fonts requires extending and proving the font profile.

All final pages of [normal](assets/SURV-080-pdf-normal.pdf),
[long-label](assets/SURV-080-pdf-long-labels.pdf),
[empty](assets/SURV-080-pdf-empty.pdf) and the
[actual worker report](assets/SURV-080-pdf-worker.pdf) were rendered with Poppler
(`pdftoppm -scale-to 1100 -png`) and visually inspected by the assistant.
No clipping, overlap, replacement glyphs or unreadable labels were observed in
these 20 pages. The initial heading and continuation-context issues were fixed
before this final review. This is a recorded visual check, not a PDF accessibility
certification. [Review record and source hashes](assets/SURV-080-pdf-review.json).

### Actual API/worker/storage proof

The final command was:

```sh
rtk proxy sh tools/surveys/infrastructure.sh /Users/bjoern/.codex/worktrees/497a/leonaid exports
```

Project `leonaid-surveys-833458328-41834`, exit 0, no host ports, owned resources
removed and verified. All four jobs were created while the worker was stopped,
then processed and downloaded through the actual API after worker startup.
CSV/XLSX parsing and the PDF text checks passed; the PDF was stored as an exact
private object version. Existing idempotency, raw-export denial, queued grant
revocation, anonymous storage denial and deleted-survey download checks passed
for this extended product set. A separate queued Japanese-title PDF job failed
without storing an artifact; download returned 409, and the persisted outbox error
was only `survey_export_failed`, with no title or raw diagnostics. The host browser
regression passed (897 ms); it remains distinct from the unimplemented export UI
journeys. [All-products result](assets/SURV-080-all-products-api.json).

An earlier all-products run (`40433`) passed before the glyph guard was added.
Only the final `41834` run supports the glyph-failure claim. During local renderer
development, two fixture assertions were corrected (normal results need not
contain missing percentages; Typst emits empty annotation arrays), and an edit
temporarily misplaced the glyph function inside payload construction. The real
render check caught that error; the final rerun and Mypy passed. Final Ruff,
format checks and Mypy pass; no whole SURV-080 acceptance gate is closed here.
# Export UI increment — empty snapshot and lost acknowledgement

Implementation based on `08d4bfc`; the commit containing this section records
the exact source revision. Own license remains UNDEFINED.

- Added the neutral `@leonaid/surveys/exports` entrypoint and scoped export
  styles. Host adapters supply authorization, credentials, translated messages
  and filenames; the package imports no LeonAid services or UI components.
- Connected all four formats to the displayed immutable analysis snapshot.
  Each product shows queued/running/retrying/available/failed/revoked state.
  A lost creation acknowledgement preserves the operation ID and request;
  status polls stop on errors and can be resumed explicitly. Permission/access
  rejection clears the affected job. Authenticated blob downloads use temporary
  object URLs, with no response blob stored in React state or browser storage.
- The member host supplies separate raw/report permissions. Full permission
  persona coverage and export-only navigation remain open; UI hiding alone is
  not acceptance evidence for authorization.

Verification:

- Pinned Bun container: `bunx --no-install tsc --noEmit -p apps/web/tsconfig.json`
  exited 0. `git diff --check` passed.
- `rtk proxy sh tools/surveys/infrastructure.sh /Users/bjoern/.codex/worktrees/497a/leonaid exports`
  exited 0 in project `leonaid-surveys-833458328-45881`. No published host
  ports; private project networks and volumes were removed and teardown checked.
- Existing real API/outbox/worker/RustFS/Typst proof passed for all four products,
  including snapshot values, cancellation, deletion and private storage checks.
- Chromium: 2 tests passed in 10.3 seconds. The new named test in
  `tests/e2e/surveys-exports.spec.mjs` creates/publishes a synthetic definition,
  requests an empty analysis through the UI, creates/downloads every product,
  checks file signatures and CSV snapshot metadata, and confirms all requests
  use the displayed snapshot. Network fault injection commits the first real
  export request before dropping its response; the UI retries the exact body.
- At 390px viewport width, no horizontal page overflow was observed. The
  rendered export panel was manually inspected: all four labels, statuses and
  download buttons are readable with no clipping or overlap.
- First attempt (`44808`) failed because the test read an analysis snapshot
  fixture instead of a definition (HTTP 422). Corrected to `analysis-golden.json`
  before the successful fresh-stack run. No product behavior was weakened.

Evidence: [browser assertions](assets/SURV-080-browser-empty.json),
[mobile panel](assets/SURV-080-browser-mobile.png).

This is incremental evidence, not acceptance of 080.A4 or SURV-080. Remaining:
populated-snapshot browser value comparisons, report-only/raw-denied and revoked
download journeys, failed/retrying worker and storage recovery UI, independent
packed export consumer, XLSX rendered-chart review, and remaining criteria below.

## Populated browser exports and permission revocation

Accepted **080.A4 / 080.S4** and **080.A6 / 080.S6**. The implementation baseline
is `627e02a`; this section, the tests and fixture/parser changes are committed
together. No other SURV-080 criterion or implementation task is accepted here.

| Task | Required criteria | Evidence and disposition |
|---|---|---|
| 080.T2 | A4, A5, A6 | A4/A6 pass through the named browser journeys and independent file parsing; A5 remains open for rendered XLSX review. |
| 080.1 | A1, A2, A4, A6 | A4/A6 accepted; full task remains open pending remaining integration gates. |
| 080.2 | A1, A4, A5 | A4 accepted; full task remains open. |
| 080.3 | A3, A4, A6 | A4/A6 accepted; full task remains open pending complete worker/storage recovery and permission-race gates. |

`tests/e2e/surveys-export-values.spec.mjs` contains two real Chromium journeys:

1. **populated snapshot exports match visible metrics and report-only access denies raw jobs**
   starts with five synthetic responses (four completed, one partial), creates
   analysis through the member UI and compares visible per-question counts,
   means and NPS with its immutable snapshot. It edits an unapplied status
   filter and then requests all four products through the UI: all jobs still
   reference the displayed snapshot, not the unapplied filter. It observes
   completion and saves the authenticated browser downloads for independent
   parsing. A second member has only `view_aggregates` and `export_reports`:
   report actions and a real report download work, both raw actions are absent,
   and direct raw job creation/download requests return 404 without attachments.
2. **revoked report access blocks existing downloads and trash clears a stale download action**
   runs after the fixture removes only the report grant in PostgreSQL. The same
   member can still create/view aggregate analysis, but cannot create reports
   or fetch/download its previously available report. Then an administrator
   creates a PDF, the real lifecycle API trashes the survey while the export
   panel remains open, and the stale download action receives 404. The UI shows
   the access rejection, removes the download button and emits no download.

`tools/surveys/export_browser_live.py verify-revoke` parses the **actual browser
downloads**, not fresh files downloaded by a different client:

- CSV/XLSX contain the same five participation IDs and matching raw text,
  multiselect, matrix, type and status values, including the partial response.
- XLSX snapshot metadata and every question's counts, mean, bounds and NPS
  match the snapshot asserted in the browser.
- PDF contains that snapshot ID, each question's exact count table, NPS 33.33,
  numeric sum 30/mean 15/minimum 10/maximum 20, multiselect 100/50 percentages,
  and matrix 50/50 and 0/100 percentages. Aggregate PDF/XLSX contain no seeded
  private text markers. XLSX includes charts; their visual rendering remains a
  separate, still-open gate.

Execution: `rtk proxy sh tools/surveys/infrastructure.sh /Users/bjoern/.codex/worktrees/497a/leonaid exports`
exited 0 in project `leonaid-surveys-833458328-48277`. Four browser tests passed:
two foundation/empty-export cases in 9.8s, populated export in 12.7s, revocation
in 4.5s. The existing four-product API/worker/private-storage proof also passed.
The preceding run `47430` passed; `48277` repeated the full sequence after adding
the stronger PDF count/metric/distribution assertions. Both used isolated
networks without host ports and completed verified teardown. Python syntax,
shell syntax and `git diff --check` passed; Python/JS files were formatted.

Temporary persona credentials, detailed snapshots and raw downloads stay in
the disposable proof directory and are deleted on teardown. Only sanitized
summaries are retained: [values](assets/SURV-080-browser-values.json),
[permissions](assets/SURV-080-browser-permissions.json).

Remaining work includes renderer/storage retry and crash recovery, complete
job-time revocation/deletion races, rendered XLSX inspection, packed independent
export consumer, export-only navigation, and the other open plan work packages.

## Worker recovery and tabular task acceptance

**080.A1 / 080.S1 and 080.A2 / 080.S2 are accepted.** Together with the existing
080.A4 / 080.S4 and 080.A6 / 080.S6 evidence above, this accepts **080.1**.
Runtime baseline `5f8eab4` is unchanged in this increment; the new integration
probe and harness mode are recorded in the commit containing this section.

| Task | Required criteria | Tests and result |
|---|---|---|
| 080.1 | A1, A2, A4, A6 | Accepted: `exports_live.py`, `export_browser_live.py`, `surveys-exports.spec.mjs`, both `surveys-export-values.spec.mjs` journeys, and `export_recovery_live.py` below. |
| 080.T1 | A1, A2, A3 | A1/A2 accepted; A3 remains open for the full revocation/deletion race matrix. |
| 080.T2 | A4, A5, A6 | A4/A6 accepted; A5 remains open for actual workbook render review. |

The already successful `exports` mode (project `48277`, documented above)
generated all four products with the real worker and private versioned RustFS,
parsed their golden counts/metrics and snapshot/filter metadata, and checked
absence of the synthetic access credentials. Actual browser downloads were
also independently parsed. The new `export-recovery` mode closes the remaining
renderer retry and adversarial tabular integration requirements:

1. **Process exit after upload:** a test-only subclass delegates to the actual
   S3 `put_immutable` method, which uploads and HEAD-verifies a version, then
   calls `os._exit(73)`. This runs inside the production `OutboxWorker`, queue
   and `AsyncpgSurveyExports` handler. The shell requires exactly exit 73.
   PostgreSQL shows the export transaction rolled back (queued job, no stored
   reference) and an unfinished first outbox claim; the real object is readable
   privately but the download API returns 409. Only the fixture claim timestamp
   is advanced to exercise the existing stale-lease recovery code. The regular
   worker reclaims the same event/job and reuses the exact original object
   version and hash; no second object version or job is created.
2. **Unavailable renderer:** a separate test worker process runs with a PATH
   that cannot resolve Typst. The actual subprocess invocation fails through
   the production handler/outbox path. No file becomes available, downloads
   return 409, and persisted error code/detail are both `survey_export_failed`.
   Starting the regular worker recovers the same job; the resulting PDF is
   parsed successfully and contains no raw formula-text answer.
3. **Unavailable storage:** RustFS is actually stopped while the regular worker
   attempts a CSV export. Failure/retry state and download denial are observed.
   Restarting RustFS allows the same job to succeed with a single object version
   and verified download hash.

The recovered XLSX/CSV contain two synthetic responses, including a formula-like
HYPERLINK string with Unicode, an empty string and a fully missing response.
Independent openpyxl/CSV parsing verifies that XLSX cells have neither formula
types nor hyperlinks, CSV applies the documented leading-apostrophe escaping,
Unicode text and multiselect/matrix values survive, and empty strings remain
distinguishable from missing values through their type columns. Both products
are obtained through actual authenticated API downloads after real worker jobs.

Command: `rtk proxy sh tools/surveys/infrastructure.sh /Users/bjoern/.codex/worktrees/497a/leonaid export-recovery`.
Final project `leonaid-surveys-833458328-51058` exited 0: crash and renderer jobs
completed on attempt 2, storage on attempt 3; each has exactly one object version.
Foundation browser regression passed in 1.9s. All owned containers, networks and
volumes were removed and teardown verified; no host ports were published.
The preceding `50025` run passed the three recovery cases before adding the
adversarial XLSX/CSV file assertions. Shell syntax and formatting checks passed.

Sanitized evidence: [recovery results](assets/SURV-080-recovery.json). Credentials
and object locations exist only in the temporary fixture directory and are
removed by teardown. No production fault-injection switches were added.

Remaining: full job-time permission/deletion races, especially cancellation
after an uploaded-but-uncommitted object; retention must account for such
objects even if no committed job reference exists. Also still open: XLSX visual
review, independent packed export consumer, broader export navigation, terminal
failure/retry browser states, and the rest of the overall plan. This acceptance
does not imply SURV-080 or the complete spike is finished.
