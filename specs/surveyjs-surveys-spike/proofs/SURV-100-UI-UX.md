# SURV-100 — Feature flags, UI system and UX regressions

**100.3m / 100.S2l are accepted for these three existing suites.** Feature flags,
UI system and UX acceptance pass their complete commands with independent
cleanup. The route-loading change additionally passes the complete survey
Journey regression. The broader parent gate and full spike remain open.

## Scope and required acceptance

| Task / criterion | Required evidence | Current result |
| --- | --- | --- |
| 100.3m / 100.A3 / 100.S2l — feature flags | Python/React flag evaluation, persistence, audit, fresh-login and RBAC contracts, actual browser behavior, owned cleanup | Fresh complete command passes in 718.487 seconds; one Chromium test passes in 3.6 seconds, post-restart contracts pass and independent inventories are empty. |
| 100.3m / 100.A3 / 100.S2l — UI system | Desktop/mobile reference comparison, authenticated catalog, keyboard navigation, toast/dialog/drawer behavior, light/dark accessibility and owned cleanup | Corrected complete command passes in 451.121 seconds; two Chromium tests pass in 20.2 seconds and independent cleanup passes. |
| 100.3m / 100.A3 / 100.S2l — UX | All three role-specific flows, accessibility, keyboard and touch targets, zoom/overflow checks, original mobile performance budgets and owned cleanup | All four Chromium tests pass; complete command exits zero in 641.881 seconds and independent cleanup passes. |
| Route-loading regression | Full survey desktop/mobile author-to-erasure journeys, export parsing, persisted values, version/permission boundaries and SQL/object erasure | All five Chromium tests pass; complete command exits zero in 542.636 seconds and independent cleanup passes. |

Executed entrypoints are `sh tools/feature_flags/test.sh "$PWD"`,
`sh tools/ux_acceptance/test.sh "$PWD"` and
`sh tools/surveys/infrastructure.sh "$PWD" journeys`. The UI entrypoint is
`sh tools/ui_system/test.sh "$PWD"` with `LEONAID_UPDATE_SCREENSHOTS=0`.
The source checkpoint is `99000e1` plus the explicitly reviewed worktree changes.
The fresh feature-flag run covers the route-loading change. [Exact per-run
source hashes and command results](assets/SURV-100-ui-ux-regressions.json) identify
the accepted runs. The earlier 571.878-second feature-flag pass is superseded
for this acceptance by the fresh repetition.

## Isolation and diagnostics

The three legacy harnesses use a worktree checksum and process ID for their
project names. They reject occupied or unreadable resource inventories before
acquiring ownership, reserve unused networks before starting services and
publish no host ports. Cleanup checks its exit status and all three owned
resource inventories. A separate controller repeats the inventory checks.

UI/UX browser results use a private per-run output mount. Failed runs retain
their traces and screenshots; successful runs copy the required final artifacts
before removing temporary browser output. An output-directory permission error
is therefore distinguishable from an application assertion failure. No passing
result is inferred from a stale artifact or a successful cleanup alone.

## Reviewed changes

The original desktop UI reference preceded existing navigation additions and a
danger-color update. Actual, expected and difference images were inspected.
Every changed raw pixel falls within the sidebar or the three affected danger
controls; all remaining pixels are identical. Only the desktop reference is
updated. The mobile reference and comparison tolerance remain unchanged.

The next full UI run passed that screenshot comparison, then reported contrast
failures on the three labels in a menu marked `data-closed` and
`data-ending-style`. The component has a 120-ms opacity transition. A separate
Chromium probe using the real `ThemeSwitcher` and built application CSS passes
twelve accessibility audits of opened and settled light/dark states. The probe
does not replace the complete application test. The revised test waits for menu
removal before checking the settled dark catalog and adds accessibility checks
of both opened menus plus Escape/focus restoration. Existing accessibility
rules and original assertions remain in place. Both tests now pass through the
complete application. All four actual desktop, collapsed, dark and mobile
viewport screenshots were inspected: synthetic identity, readable catalog and
intact shell; the dark screenshot shows focus restored to the theme trigger.

Reviewed viewport artifacts: [desktop](assets/SURV-100-ui-desktop.png),
[collapsed sidebar](assets/SURV-100-ui-collapsed.png),
[dark theme](assets/SURV-100-ui-dark.png) and
[mobile](assets/SURV-100-ui-mobile.png).

The earlier UX run exceeded the 2500-ms Charity-Admin LCP budget at 2740 ms.
The admin entry imported the survey editor/renderer eagerly. A route-level
`React.lazy` import with a visible `Suspense` loading state now loads that module
when the surveys route is selected. The entry source map excludes the survey
module, package and SurveyJS renderer; the separate lazy chunk includes them.
Pinned typechecking and production build pass. Uncompressed initial assets are
727523 bytes of JavaScript and 161847 bytes of CSS; these build sizes are separate
from the browser transfer measurements below.

## Complete UX performance repetition

The original profile is unchanged: Chromium/Playwright 1.54.1, 390×844 viewport,
4× CPU throttling, 10 Mbps download, 5 Mbps upload and 40-ms network latency.

| Surface | LCP (ms) | DOM content loaded (ms) | Main-thread tasks (ms) | Transferred bytes | CLS |
| --- | ---: | ---: | ---: | ---: | ---: |
| Public Krapfentaxi | 364 | 162 | 310 | 180414 | 0.0002 |
| Acquirer | 980 | 780 | 379 | 740220 | 0 |
| Charity-Admin | 1204 | 933 | 581 | 894266 | 0 |
| Existing maximum | 2500 | 2500 | 1800 | 1000000 | 0.1 |

These are observations from the successful complete run, not production load
guarantees. The expanded isolation guard also passes 188 cases across 44
harnesses and three operator target checks. Its final formatting is AST-identical
to the tested source. These guards supplement the real-service runs above.

This brings the delivered isolated legacy suite evidence to 42 of 42, with the
per-run revisions and boundaries retained. Caddy image integration, the complete
repeated aggregate, independent-host recovery and full spike completion remain separate.
