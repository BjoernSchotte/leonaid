# SURV-020 — Independent packed consumer

Based on `d2616fb` plus this commit's package, demo and test changes. This proves
the respondent consumer boundary; editor-wide translation, analytics entrypoints
and the complete work package remain open.

## Delivery and acceptance

| Task | Required criteria | Evidence | Status |
|---|---|---|---|
| 020.1 | A1, A2, A3 | Separate existing entrypoints; new runner locale/messages | Partial: editor-wide translation and analytics entrypoint remain open |
| 020.2 | A1, A3 | Actual tarball installed in clean `/consumer`; real SQLite adapter; two browser phases | Delivered and accepted |
| 020.3 | A3, A4 | Host token overrides, English runner, browser mounting/restoration; T-07 disposition below | Delivered and accepted |
| 020.4 | A2 | Packed file allowlist, MIT inventory, retained software/OFL notices, bundle source-map inspection | Delivered and accepted for current shipped entrypoints |
| 020.T1 | A1, A2 | `apps/surveys-demo/inspect.mjs` and actual persisted external consumer | Passed |
| 020.T2 | A3, A4 | `tests/e2e/surveys-package.spec.mjs` and Astro reload assertions below | Passed for the selected browser-mounted path |

## Reproducible isolated command

`./leonaid test-surveys-package` builds the package in a `/package` stage with
`bun pm pack --ignore-scripts`. Only the resulting tarball crosses into a fresh
`/consumer` stage. There is no `/workspace`, original package directory, LeonAid
source or shared node_modules in that consumer. Installation uses the committed
consumer lockfile and `--frozen-lockfile --ignore-scripts`.

The template manifest is deliberately not a workspace `package.json`. All
consumer imports use exported package paths. Bun builds the actual packed runner
and fontless styles into browser assets. The backend uses Bun's SQLite adapter
and its own fixed two-page questionnaire validation, not LeonAid code or API.
It persists version/response snapshots, revisioned/idempotent writes and terminal
completion. This minimal synthetic backend is not an arbitrary survey service.

Final package run: project `surveys-package-833458328-76478`, exit **0**. The first
Chromium phase passed in 4.1s and the second in 2.4s. Between phases, Docker
restarted the actual backend process while retaining its private SQLite volume.
The browser used a fresh context with the same credential after restart.
The unique network used one currently unused explicit subnet; no host ports
were published. Browser and consumer shared the private network namespace so
`localhost` supplied the secure browser context required by cryptographic
operation IDs. The command removed its container, volume and network and its
temporary image tag; other worktrees were untouched.

## Named browser assertions

`packed consumer saves a multipage response in its own host` checks an English
required-answer error, fills a name and second-page comment, waits for the host's
custom saved acknowledgement and reads the exact persisted response through the
real API. Changing the host theme updates the SurveyJS brand token while the
adjacent host button retains its background styling. There is one participation.

`packed consumer restores after backend restart without an extra save` runs at
390 × 844 after process restart. It restores the second page and saved text,
compares the entire response plus server write counter to the pre-restart state,
and records zero POST/PUT/PATCH requests during restoration. Completion and a
subsequent reload show the host's translated thank-you screen, with the same
participation ID and exact answers. First-phase viewport: 1100 × 850.

Visual inspection of the synthetic desktop and mobile completion captures found
readable controls/text and no clipping in these states. This is not complete
mobile authoring or accessibility acceptance.

![Independent desktop host](assets/SURV-020-independent-desktop.png)
![Independent mobile completion](assets/SURV-020-independent-mobile.png)

## Package and license evidence

[Machine-readable inventory](assets/SURV-020-package.json) records the actual
installed versions and bundle measurements. The inspector requires exactly the
own package plus SurveyJS core/React 3.0.3, React/React DOM 19.2.8 and scheduler
0.27.0. All five third-party packages declare MIT and match the previously
reviewed dependencies. The own package remains private/UNLICENSED in metadata;
its future license decision is UNDEFINED.

Realpath checks ensure resolution remains under `/consumer`. The respondent
bundle's source map contains the packed runner but no editor, condition-builder
or server-validation candidate module. Its 17 source entries produce a
3,049,790-byte unminified browser JS file; this is a measured baseline, not a
performance acceptance claim. The tarball contains only its manifest, README,
third-party notice and package sources. Third-party font licensing stays
separate: the installed core retains `fonts/LICENSE.txt`, while the actual
fontless browser CSS contains no `@font-face` block.

The first build attempt used a constant output filename that also applied to
CSS and failed; default extension-aware naming fixed it. The first browser
attempt used the nonsecure `consumer` hostname and failed before creation at
`crypto.randomUUID`; the private localhost namespace fixed that host requirement.
Neither failed attempt is counted as acceptance. Traces and credential-bearing
browser state remain ignored local artifacts; only synthetic screenshots and
the dependency/bundle summary are retained here.

## Remaining boundaries

Both the independent host and the existing Astro participation page mount in
the browser. No SSR capability is claimed by this proof. The Astro route sets
`Cache-Control: no-store` and renders a loading shell; private response data is
loaded later through the authorized API. Full 020.A4 disposition and the
remaining theme/SSR task stay open until their host-specific checks are recorded.

Current package TypeScript and `test-surveys-core` passed (168 comparison cases,
23 Python tests and three coordinator tests / 17 assertions); the network helper
passed Ruff.

The final LeonAid regression `./leonaid test-surveys-runner`, project
`leonaid-surveys-833458328-76619`, exited zero: seven Chromium scenarios passed
in 24.6 seconds after real migrations, response contracts, all 192 API/database
cases and stopped/paused-validator recovery. It retained German default text,
no-blur persistence, numeric-text conditions, hidden-page cleanup, offline retry,
matrix correction and completion. The command verified isolated teardown with
no host ports. Existing defaults remain compatible while the independent host
uses explicit English locale/messages. This is not full editor translation or
SSR acceptance.

## Browser rendering and restoration disposition

Revision: `e9ec59f` plus this commit's browser assertions, rendering probe and
decision record. No product runtime code changed in this increment.

`./leonaid test-surveys-package` ran as `surveys-package-833458328-80870` and
exited **0**. Its two Chromium phases passed in 3.0s and 1.3s at the desktop/mobile
viewports recorded above, with an actual backend restart between phases. The
restoration test additionally inspected the original HTML response: the empty
mount point was present and both synthetic saved answer strings were absent.
An authenticated response fetch returned HTTP 200 and `Cache-Control: no-store`.
The restored snapshot and server write counter matched the pre-restart values;
the browser recorded no POST/PUT/PATCH while restoring. Completion and subsequent
reload retained the same identity and answers. Existing host-theme and English
validation/message assertions passed in the first phase.

`./leonaid test-surveys-runner` ran as `leonaid-surveys-833458328-80893` and exited **0**.
All seven Chromium scenarios passed in 24.9s. The named
`acknowledged text survives closing mid-page and hidden follow-up is removed`
scenario now inspects the real Astro reload response: HTTP HTML has `no-store`,
contains the loading shell and omits the persisted second-page note. The browser
then displays that exact note from the authorized API, whose response also has
`no-store`. Reload records no POST/PUT/PATCH. The same scenario also verifies
fresh-context restoration, a 650ms observation without autosave, timeout
resumption and hidden-answer cleanup against persisted state. The harness again
passed its real migrations, response contracts, all 192 API/PostgreSQL cases and
stopped/paused-validator rejection and recovery checks.

The independent run published no host ports, used its own explicit subnet and
removed its container, volume and network. The LeonAid harness used seven
currently unused explicit subnets and no host ports; it verified complete
container, volume and network teardown before exiting successfully.

The standalone investigation command was:

```sh
rtk proxy docker run --rm \
  -v "$PWD:/workspace" -w /workspace \
  docker.io/oven/bun:1.2.19-alpine@sha256:7dc0e33a62cbc1606d14b07706c3a00ae66e8e9d0e81b83241ed609763e66d55 \
  sh -c 'bun tools/surveys/rendering-probe.ts .artifacts/surveys-package/rendering-probe.json > .artifacts/surveys-package/rendering-probe.log 2>&1'
```

It exited **0** and reported `rendered: true`, `bytes: 3091`,
`questionPresent: true`, `privateAnswerPresent: false`, `adapterCalls: 0`.
The probe uses only synthetic data and the installed pinned React 19.2.8 /
SurveyJS 3.0.3. A successful `renderToString` invocation does not establish
SSR answer fidelity or framework hydration. T-07 therefore selects the tested
browser-mounted path in both hosts; SSR remains outside the chosen spike path.
No new visual review or broader authoring accessibility claim is made here.

Scenario reconciliation:

| Scenario | Named evidence | Result |
|---|---|---|
| 020.S1 | Packed install/inspection plus both `surveys-package.spec.mjs` tests and real SQLite writes/restart | Passed |
| 020.S2 | `apps/surveys-demo/inspect.mjs`, packed inventory and retained notice checks documented above | Passed |
| 020.S3 | `packed consumer saves a multipage response in its own host` and completion in the second phase | Passed |
| 020.S4 | `packed consumer restores after backend restart without an extra save`, Astro reload assertions, and T-07 probe/disposition | Passed, including verified harness teardown |

This closes 020.3, 020.T2 and 020.A4 with verified cleanup. The package gate's
four acceptance criteria now pass. The editor-wide translation and analytics entrypoint work in
020.1 remains open; the overall work package and spike are not complete.
