# Capability matrix — SurveyJS surveys

Date: 2026-09-06

Status: required scope with implementation evidence indexed below. The final
cross-layer/whole-journey gate remains open; individual historical proofs apply
only to their stated fixtures and acceptance boundaries.

Own license decision: **UNDEFINED**

This matrix separates visual editing, respondent rendering, authoritative
server checks and analysis/export. Renderer support alone proves none of the
other layers. Publish only against an explicitly verified capability profile
and a pinned SurveyJS 3.x version.

All editor and analytics features below are our own implementation targets.
Commercial Survey Creator, Dashboard and PDF Generator are excluded under
[the dependency policy](DEPENDENCIES.md).

## 1. Required spike capabilities

| ID | Capability | Custom editor | SurveyJS rendering | Server / persistence | Analysis / export |
|---|---|---|---|---|---|
| C-01 | Pages and progress | Create, reorder, duplicate pages; move questions between pages | Forward/back, relevant pages, mobile layout | Version-bound progress and saves | Last visited page; no unsupported claim about abandonment reason |
| C-02 | Short / long text | Labels, descriptions, required flag, length limits | Inputs and errors | Type/length; missing answer allowed during autosave | Authorized free-text list and CSV/XLSX; deliberate inclusion in reports |
| C-03 | Single choice / dropdown | Stable IDs, labels, order | Single value | Allowed option only | Distribution and answered/relevant counts |
| C-04 | Multiple choice | Options and selection limits | Multiple values | Valid unique options; completion limits | Counts and documented percentage denominator |
| C-05 | Rating / NPS | Scale, labels; defined 0–10 NPS template | Rating control | Numeric type and range | Distribution/mean; NPS with explicit formula and valid n |
| C-06 | Number / date | Bounds and presentation | Localized input | Types, bounds and consistent storage | Numeric summaries; meaningful date summaries, not arbitrary date averages |
| C-07 | Fixed single-select matrix | Fixed rows and choice columns | Desktop/mobile matrix | Row/column IDs and relevant required rows | Per-row distribution; flat export columns |
| C-08 | Conditions | Guided comparisons with all/any conditions; show question/page | Equivalent visibility | Equivalent relevance and hidden-answer cleanup | Relevant, hidden and unanswered distinguished |
| C-09 | Required / validation | Required flag; value, choice-count and length limits | Clear errors | Partial vs final validation | Invalid values never silently count as valid responses |
| C-10 | Presentation | Titles, hints, completion page; bounded host colors/logo | Accessible responsive form | Sanitized content; no arbitrary scripts/URLs | Consistent report titles and descriptions |
| C-11 | Templates / duplication | Start from template | Preview | Copy without answers, tokens or recipients | No mixing with original survey |
| C-12 | JSON import / export | Diagnostics, lossless roundtrip, protected unknown regions | Only tested profile executable | Definition-schema checks plus profile/publish validation | No misleading aggregates for unknown types |
| C-13 | Undo/redo / draft autosave | Undo/redo and save status | Current draft preview | Draft revision checks | Does not apply to real responses |
| C-14 | German UI / accessibility | Translatable components, keyboard alternative to dragging | Labels, focus, errors, mobile operation | Language is not an authorization attribute | Tables, German reports and Unicode exports |
| C-15 | SurveyJS 3 host integration | Independent editor theme contract | Scoped token mapping and verified hydration mode | No unintended saves during restoration/hydration | Host chart/report theme; no dependency on upstream Dashboard |

C-08 initially supports comparisons against preceding answers: equal/not equal,
contains, empty/not empty and numeric comparisons. No arbitrary JavaScript.
SURV-010 defines detailed client/server fixtures and rejects unsupported logic.

## 2. Post-spike extensions

| Capability | Required work before promising support |
|---|---|
| Multilingual questionnaires | Translation editor, fallbacks, stable IDs, language-independent aggregation. |
| Repeated groups / dynamic panels | Nested editor, stable instance identities, server checks, relational export layout. |
| Advanced matrices | Mixed cell types, multiple selections per row, mobile UX and export rules. |
| Ranking | Editor, accessible ordering, server checks and rank statistics. |
| Uploads / signatures | Type/size limits, storage authorization, retention, public upload controls; avoid base64-heavy autosave. |
| Calculations / dynamic text | Defined expression language, equivalent server evaluation, cycle handling and safe interpolation. |
| External choice data | Authorized host adapters, allowed URLs, reproducible data versions and server validation. |
| Quiz / scoring | Server scoring, protection of solutions, release policies and corrections. |
| Randomization | Stable ordering per participation, recovery and interpretable results. |
| Rich theme editing | Design tokens, contrast checks, safe fonts/media and independent embedding. |
| Collaborative editing | Shared state and conflict handling beyond a draft revision counter. |
| Custom question types | Registration contract covering editor, renderer, validation, aggregation and exports. |
| Slider / range inputs | Scalar vs tuple shape, steps/bounds, autosave behavior, numeric summaries and accessibility. |
| Exclusive options / per-choice comments | Incompatible-choice validation, comment schema and distinct analysis/export fields. |
| Respondent-created choices | Server normalization, abuse/size limits and separation from author-defined choices. |
| Nested choice content | Depth limits, nested IDs, relevance cleanup and structured exports; blocked until proven. |
| Saved analysis views / cross-filtering | Declarative host-neutral view state, authorized server filters and consistent export snapshots. |
| Validation warnings / information | Explicit non-blocking severity separate from errors in editor, runner and server contracts. |

Recent upstream capabilities are discovery inputs. This table does not claim
they all first appeared in 3.0 or that our package gains them automatically.
Paper/AI extraction and PDF form filling are not part of the requested analysis
report workflow and are not included in the spike.

## 3. Unsupported feature handling

1. Parse definitions without losing unknown safe properties; identify affected
   question types, options and regions.
2. Allow safe editing; preserve other regions read-only with actionable diagnostics.
3. Inspect executable HTML/scripts and external resources. A recognized renderer
   option does not automatically authorize its execution.
4. Validate definition structure using metadata/schema from the pinned release.
   Separately require full profile coverage for server semantics before publication.
5. Verify old fixtures and answers on upgrades; record profile and renderer version
   with each published definition.

## 4. Acceptance fixtures

| Fixture | Key cases |
|---|---|
| Krapfentaxi | Three pages; low rating reveals follow-up; NPS/text; browser closes mid-page 2. |
| Golf tournament | Multi-page fixed matrix, multiple choice, conditional question; partial and complete responses. |
| Back navigation | Earlier edit hides a follow-up and removes its obsolete value from analysis. |
| Version change | New participants receive new definition; existing participation keeps its original version. |
| Import roundtrip | Safe unknown data preserved; unsafe or semantically unsupported definitions cannot publish. |
| Analysis golden data | Explicit n, percentages and NPS; missing/hidden distinguished; multiple versions. |
| Export edges | Accents, emoji, long text, possible formulas, empty choices/matrix cells, PDF pagination. |
| SurveyJS 3 compatibility | Scoped tokens, host theme, hydration without duplicate autosave; newer unsupported choice content diagnosed. |
| Definition vs response validation | Structurally valid definition with unsupported semantics rejected; invalid answers rejected independently. |

All data is synthetic. Proof documents record observed results rather than
treating planned coverage as completed evidence.

## 5. Capability-to-fixture evidence index

Paths below are relative to the repository root. This index is a navigation aid
for the SURV-000/100 audit, not an assertion that every named test was rerun in
the current increment. Follow each proof for commands, versions, observations
and remaining limitations. The general write boundary is indexed separately in
[WRITE-CONTRACTS.md](WRITE-CONTRACTS.md).

| Capability | Actual fixtures / executable assertions | Observed evidence and boundary |
| --- | --- | --- |
| C-01 | `tests/fixtures/surveys/krapfentaxi.json`, `golf.json`; `surveys-editor.spec.mjs` structural moves; `surveys-runner.spec.mjs` mid-page/tab-loss journeys; analysis `lastPageCounts` | [Editor structural persistence](proofs/SURV-040.md#live-browser-result), [timeout/resume](proofs/SURV-050.md), [snapshot page counts](proofs/SURV-070.md#immutable-analysis-snapshots); last page is observed progress, not a proven abandonment reason |
| C-02 | Taxi text/comment questions; validation length/Unicode fixtures; `surveys-runner.spec.mjs` minimum length; `raw_responses_live.py`; export snapshot text markers | [Authoritative validation](proofs/SURV-010.md#shared-core-backend-integration), [authorized raw response views](proofs/SURV-070.md#authorized-raw-response-browser-views), [Unicode and report review](proofs/SURV-080.md#consolidated-render-acceptance) |
| C-03 | Taxi `freshness`, golf `return`; `surveys-authoring.spec.mjs`; `analysis-golden.json` and `tools/surveys/analysis.test.ts` exact scalar choice identities | [Sample authoring](proofs/SURV-040.md#complete-sample-authoring-and-validated-preview), [golden aggregate values](proofs/SURV-070.md#golden-and-package-evidence) |
| C-04 | Golf `improvements`; authoring selection limit; validation coercion/boundaries; golden multiple-selection percentages | [Shared-Core integration](proofs/SURV-010.md#shared-core-backend-integration), [explicit denominators](proofs/SURV-070.md#aggregate-semantics) |
| C-05 | Taxi delivery rating and 0–10 NPS; `analysis-golden.json`; `analysis.test.ts` fractional scale and hand-calculated NPS | [Authoring/preview](proofs/SURV-040.md#complete-sample-authoring-and-validated-preview), [NPS/distributions](proofs/SURV-070.md#golden-and-package-evidence), [report products](proofs/SURV-080.md#dedicated-typst-reports-and-all-four-products--2026-09-07) |
| C-06 | Golf handicap/date; validation-boundaries/coercion fixtures; golden numeric/date values | [Strict persisted types](proofs/SURV-010.md#strict-answer-types-and-matrix-completion), [numeric/date semantics](proofs/SURV-070.md#aggregate-semantics); date values are not averaged |
| C-07 | Golf fixed matrix; `surveys-runner.spec.mjs` forged matrix and required-row correction; golden per-row counts; export snapshot matrix columns | [Real matrix correction](proofs/SURV-010.md#strict-answer-types-and-matrix-completion), [row aggregates](proofs/SURV-070.md#golden-and-package-evidence), [tabular artifacts](proofs/SURV-080.md#artifact-level-verification) |
| C-08 | `conditional-pages.json`, `condition-candidate-cases.json`, `condition-coercion.json`; guided editor conditions; runner hidden-page-chain tests | [Shared browser/server Core](proofs/SURV-010.md#shared-core-backend-integration), [hidden-page restoration](proofs/SURV-010.md#hidden-page-chains-and-canonical-restoration); arbitrary JS remains unsupported |
| C-09 | `validation-cases.json`, `validation-boundaries.json`, `validation-coercion.json`; `validation_live.py cases/unavailable/recover` | [192 real API cases and fail-closed adapter recovery](proofs/SURV-010.md#shared-core-backend-integration); autosave permits missing required answers, not invalid values |
| C-10 | `surveys-authoring.spec.mjs` unsafe presentation rejection and correction; editor title/hint/completion controls; scoped `styles.css` tokens | [Validated preview](proofs/SURV-040.md#complete-sample-authoring-and-validated-preview), [theme/restoration](proofs/SURV-020.md#browser-rendering-and-restoration-disposition), [report rendering](proofs/SURV-080.md#consolidated-render-acceptance). [Bounded host logos](proofs/SURV-020.md#bounded-host-logo-integration) load in both actual hosts, survive respondent restoration and reject external/unsafe path forms |
| C-11 | `tools/surveys/lifecycle.py` duplicates immutable publication without participations, versions or grants; `surveys-templates.spec.mjs` starts both host templates independently | [Duplication/lifecycle](proofs/SURV-030.md); [Template creation and independent copies](proofs/SURV-040.md#template-creation-and-editor-regression) now accept **040.5**; duplication alone did not cover starting from a template |
| C-12 | `surveys-import-recovery.spec.mjs` unknown/unsafe JSON; `tools/surveys/editor.test.ts` atomic import, stable IDs and nested read-only properties | [Import and recovery](proofs/SURV-040.md#json-preservation-publication-diagnostics-and-draft-recovery); unverified renderer options cannot bypass publication validation |
| C-13 | `surveys-import-recovery.spec.mjs` lost draft acknowledgement/undo/two tabs; `editor.test.ts` exact queued retry; actual draft revisions | [Draft recovery](proofs/SURV-040.md#json-preservation-publication-diagnostics-and-draft-recovery); history is local editing state, not respondent answer history |
| C-14 | `surveys-accessibility.spec.mjs` real Tab/Enter traversal, focus/error recovery and axe; `surveys-package.spec.mjs` host translations; Unicode export fixtures | [Reviewed keyboard/contrast evidence](proofs/SURV-040.md#final-verification-and-acceptance), [neutral translated editor](proofs/SURV-020.md#host-translated-editor-and-entrypoint-acceptance), [report render acceptance](proofs/SURV-080.md#consolidated-render-acceptance); no general WCAG certification or screen-reader proof is claimed |
| C-15 | `tools/surveys/rendering-probe.ts`; packed consumer restart/write counters; actual Astro HTML/cache/header and zero-restoration-write assertions | [Chosen browser-mount disposition](proofs/SURV-020.md#browser-rendering-and-restoration-disposition); SSR answer fidelity is not selected or claimed |

Browser filenames in this table live under `tests/e2e/`; JSON fixture filenames
live under `tests/fixtures/surveys/` unless otherwise stated. Open SURV-000 contract
coverage, SURV-090 recovery and SURV-100 aggregate/complete-journey requirements
remain acceptance blockers even when a capability has several useful proofs.
