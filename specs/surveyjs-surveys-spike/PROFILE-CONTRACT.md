# Initial capability profile and host contract

Own license: **UNDEFINED**. Published definitions record profile `initial-v1`
and renderer `3.0.3`; the renderer package is pinned. This is the source-reviewed
contract for SURV-000.5, accepted by the [consolidated review](proofs/SURV-000-CONTRACT-REVIEW.md).
The final spike gate remains open. [CAPABILITIES.md](CAPABILITIES.md) links all fifteen required
capabilities to their fixtures and work-package evidence.

## Executable definition boundary

The authoritative allowlist is `src/leonaid/domain/surveys/validation.py`.
Root properties are title, description, pages, showProgressBar, completedHtml and
locale. Pages have name, title, description, elements and optional visibleIf.
Questions use text, comment, radiogroup, dropdown, checkbox, rating or fixed matrix;
text additionally supports text, number and date input modes. Properties must
apply to their question type. Arbitrary executable scripts, HTML, remote assets,
external choice sources, dynamic panels and unreviewed SurveyJS properties cannot
publish. `completedHtml` is admitted only as bounded plain text despite its name.
The host logo and color/font configuration are outside questionnaire JSON.

| Boundary | Current rule |
| --- | --- |
| Pages / questions | 1–25 nonempty pages, at most 150 questions overall |
| Stable names | ASCII letter followed by up to 79 letters, digits or underscores; page names unique; question names unique across pages |
| Choices / fixed matrix axes | 1–100 entries each; nonempty finite string/number values; unique values; optional plain-text labels |
| Presentation strings | At most 10,000 Python characters for title, description, placeholder, completion text and option labels; `<` is rejected |
| Locale / progress | de, en or empty locale; off/top/bottom/both/auto progress positions |
| Length / choice-count limits | Integer 0–10,000; lower bound cannot exceed upper bound; answer rules also enforce available choices and defaults |
| Numeric / date bounds | Finite numeric bounds or canonical ISO calendar dates as appropriate; lower bound cannot exceed upper bound |
| Rating | Positive step, ordered endpoints, at most 100 scale points |
| Conditions | Only preceding-answer references, approved comparison/contains/empty operators, AND/OR; at most 2,000 characters and 20 opening parentheses |
| Stored definition / answer snapshots | At most 262,144 bytes using the host's JSON serialization check; not equivalent to raw HTTP body length |
| Raw HTTP survey request | At most 1,048,576 bytes, enforced before JSON parsing including streamed bodies; rejection is 413 |
| Private validator request | 600,000 bytes; host validation uses 3-second HTTP timeouts; aggregation has separate bounded batches/timeouts |

Sources for the last two limits are `survey_body_limit.py`,
`infra/compose/survey-validator.mjs` and `adapters/surveyjs_validation.py`.
Definition character limits and answer UTF-16 length rules are deliberately
stated separately. Final answer lengths match the browser/native input's UTF-16
units, including supplementary characters; the boundary is not a UTF-8 byte count.

## Client/server semantics

The browser and private validator use the same `createSurveyModel`,
`restoreSurveyAnswers` and `profileAnswerError` implementation. Python owns the
profile allowlist, current permissions, lifecycle, locks, revisions and durable
writes. It calls the private validator inside the save/completion transaction.
A stopped, timed-out or malformed validator fails with 503 and no answer update;
the known-divergent legacy Python evaluator is not a fallback.

Autosave may omit required values but cannot persist invalid supplied types,
unknown question/choice IDs or out-of-range values. Final completion validates
the stored snapshot against all relevant requirements. Numeric and date values
retain their defined storage types; matrices use stable row/column IDs. Hidden
answers are removed in dependency order on edits and restoration, and hidden
pages cannot reactivate stale descendants. A newly relevant required answer must
be supplied again. See the [shared-Core and restoration evidence](proofs/SURV-010.md).

The host stores complete snapshots with a participation revision and stable retry
operation ID. A page change is a save; answer-change time advances only when the
canonical answer object changes. Inactivity classifies a response as resumable
partial using its snapshotted timeout and does not delete it. Lifecycle closure,
invitation expiry/revocation and explicit retention are separate boundaries.
Exact write/replay/error rules are in [WRITE-CONTRACTS.md](WRITE-CONTRACTS.md);
roles and database constraints are in [ROLES-AND-DATA.md](ROLES-AND-DATA.md).

Safe unknown imported draft regions may be preserved read-only for lossless
roundtrip, but cannot execute in preview or be published without profile support.
Creating a new survey requires an executable initial definition; unsupported
import preservation happens through draft editing after creation.

## Host rendering and theme boundary

The respondent package imports SurveyJS's fontless CSS. The host supplies
`--survey-accent` and `--survey-font`, mapped under the runner's `.sd-theme-root`
to `--sjs2-color-project-brand-600` and `--sjs2-typography-font-family-text`.
Styles are scoped to survey containers. Narrow progress navigation uses a CSS
container on the progress region only, preserving dropdown popup positioning.
The optional local logo contract is documented in the package README.

LeonAid emits a public loading shell with no response contents and mounts the
React runner in the browser. The independent consumer also mounts into an empty
host element. No server-rendered SurveyJS tree is hydrated. The host adapter
restores authorized private state; model restoration precedes event registration,
so a reload does not itself save, create a second participation or overwrite
answers. Private responses use no-store and credentials remain in host-managed
cookies rather than definitions. The [independent backend-restart proof](proofs/SURV-020.md)
records this chosen browser-only boundary; arbitrary SurveyJS SSR compatibility
is not promised. Keep adapter and message identities stable during participation.

German is the default host UI, English is a tested independent-host override.
Question content is author data, not host chrome; multilingual questionnaires
remain a separately scoped extension. Charts and reports are implemented by our
package and existing export pipeline, without Survey Creator, Dashboard or
SurveyJS PDF Generator. See [DEPENDENCIES.md](DEPENDENCIES.md).
