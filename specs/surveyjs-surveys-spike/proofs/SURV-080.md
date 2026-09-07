# SURV-080 — Export implementation evidence

Baseline `8add0a6`. The first increment supplies the tabular rendering boundary;
**no SURV-080 acceptance criterion or complete implementation task is accepted**.
Worker/storage/API/UI/PDF integration remains required by PLAN.md.

## Task ledger

| Task | Delivered building block | Remaining acceptance |
|---|---|---|
| 080.1 | Shared CSV, response XLSX and analysis XLSX renderer; parsed artifact tests | Real worker/storage jobs, authorized UI/downloads and raw-export denial |
| 080.2 | Native workbook chart definitions only | Server report charts, dedicated Typst template, PDF and rendered XLSX review |
| 080.3 | No delivery claim | Durable jobs, retries, private storage and revocation/deletion enforcement |
| 080.T1 | 18 artifact-level tests | Real worker/storage permissions and recovery integration |
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

Implement survey-specific durable export jobs and outbox handling, private S3
object storage, retry/error states and protected downloads with current permission
and lifecycle checks. Add the dedicated Typst report renderer and then execute
all four real worker/storage/browser products. Only those passing integration,
E2E and rendering gates can close the still-open SURV-080 criteria.
