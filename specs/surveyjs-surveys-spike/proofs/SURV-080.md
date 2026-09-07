# SURV-080 — Export implementation evidence

Baseline `8add0a6`. The first increment supplies the tabular rendering boundary;
**no SURV-080 acceptance criterion or complete implementation task is accepted**.
Worker/storage/API/UI/PDF integration remains required by PLAN.md.

## Task ledger

| Task | Delivered building block | Remaining acceptance |
|---|---|---|
| 080.1 | CSV, response XLSX and analysis XLSX through real worker/private storage and parsed API downloads | Export UI and complete raw-export denial journey |
| 080.2 | Native workbook chart definitions only | Server report charts, dedicated Typst template, PDF and rendered XLSX review |
| 080.3 | Durable jobs, current permission checks, private storage and protected downloads | Failure/retry/crash tests and complete revocation/deletion matrix |
| 080.T1 | 18 artifact-level tests, three real tabular pipelines and 22 database invariants | PDF, complete permission matrix and failure/recovery integration |
| 080.T2 | No delivery claim | All browser downloads and rendering review |

## Rendering contract

`SurveyExportSource` carries the immutable AnalysisSnapshot, a host-supplied
captured document title and optional typed private responses. `SurveyExportArtifact`
returns bytes, filename, MIME type, render version and SHA-256. It does not reuse
invoice-domain documents or perform authorization. The forthcoming worker must
load private responses only for a permitted raw-export product and freeze its
document title as part of the job input.

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

Add the dedicated Typst report renderer, export UI and explicit failure/recovery
scenarios, then execute all four real worker/storage/browser products. Only those
passing integration, E2E and rendering gates can close the still-open SURV-080
criteria. The `analysis_pdf` contract is reserved but its renderer is not yet
implemented; this increment does not claim PDF availability.

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
