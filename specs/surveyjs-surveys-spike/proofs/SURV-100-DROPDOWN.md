# SURV-100 — Dropdown pointer regression

**100.2a / 100.S4a are accepted.** This repairs the complete-journey regression;
it does not close the broader 100.2 capability audit or the final aggregate gate.
Source baseline: `de16fa64e7807824c45730feb8ba764de116698a`.

## Failure and change

The public host applies smooth scrolling to the document. Opening the Golf
dropdown makes SurveyJS focus its input; the observed subsequent document
scroll events dismiss the popup through SurveyJS's popup scroll callback.
The failed desktop/mobile runs both showed a closing (`sv-popup--leave`) popup.
This was not evidence of a stacking-order defect.

In the instrumented failed run `leonaid-surveys-833458328-42036`, desktop input
focus occurred at 1676 ms, followed by scroll events beginning at 1724 ms and a
document offset change from 273 to 339. Mobile input focus occurred at 2250 ms,
followed by scrolling at 2274 ms. Instrumentation only recorded event types,
element classes and geometry. Upstream `DropdownListModel.onClick`,
`SurveyElement.focusElementCore` and the dropdown popup's scroll callback explain
that observed sequence in the installed SurveyJS 3.0.3 source.

The survey page now uses `scroll-behavior: auto` on
`html:has(.survey-shell)`. This confines the host scrolling policy to pages
containing the survey shell. It resolves the interaction without changing the
questionnaire, answer transport or the original pointer test.

## Full live verification

`sh tools/surveys/infrastructure.sh "$PWD" journeys` exited **0** in project
`leonaid-surveys-833458328-52983`, with **five Chromium tests passing in 2.7 minutes**.
The entire command took 368.119 seconds. All temporary instrumentation and focus
experiments were removed before the browser run: `surveys-journey.spec.mjs` was
byte-identical to the source-baseline version.

The original test opens the visible dropdown wrapper, hit-tests the visible
option and performs a real mouse click before asserting its value. No forced
click, keyboard substitution, mocked response or whole-journey retry was added.

Both Krapfentaxi and Golf completed the full author-to-erasure journey at
1440×960 and 390×960. The actual API/PostgreSQL/worker/browser flow proved
partial resume, old/new publication isolation and outsider rejection. All
16 browser downloads were parsed; CSV/XLSX contents and snapshot metrics agreed.
Final verification found the expected database content and every corresponding
object version erased. The fifth browser case exercised the existing real
identity/member/public foundation.

[Machine-readable evidence](assets/SURV-100-dropdown-scroll.json) retains the
original test hash, run metadata and the four verification results. The harness
used reserved unique networks, published no host ports and removed its owned
resources. An independent inventory confirmed no containers, volumes or networks
remained for that project. Prettier and whitespace checks passed.

The preceding failed runs are diagnostic evidence, not passing acceptance runs.
This local result does not establish the final repeated aggregate or remote CI
result; those remain separately tracked.
