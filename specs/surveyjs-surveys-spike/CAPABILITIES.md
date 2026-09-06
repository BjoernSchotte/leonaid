# Capability matrix — SurveyJS surveys

Date: 2026-09-06

Status: target scope; **none of these capabilities has yet been proven by this spike**

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

Actual fixture files and tests are implementation work. All data is synthetic;
proof documents record observed results rather than treating planned coverage
as completed evidence.
