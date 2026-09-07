# SURV-000 evidence

Status: partial, 2026-09-06. Work package remains open.

## 000.A4 — Dependency admission gate

Passed `./leonaid test-surveys-dependencies` in the repository-pinned Bun
1.2.19 Docker image (exit 0). The command inspected the installed package
manifests and transitive dependency declarations:

| Package | Version | License |
|---|---|---|
| survey-core | 3.0.3 | MIT |
| survey-react-ui | 3.0.3 | MIT |
| react | 19.2.8 | MIT |
| react-dom | 19.2.8 | MIT |
| scheduler | 0.27.0 | MIT |

The actual survey-core font license file identifies OFL-1.1. Four negative
fixtures were rejected: prohibited Creator package, commercial license on an
otherwise approved package, unreviewed version, and unknown transitive dependency.
The new package remains private/UNLICENSED; the own-license decision remains
UNDEFINED. No Creator, Dashboard or PDF Generator package was installed.

This proves the initial dependency gate only. It does not establish the final
artifact's notices, future editor/chart dependencies, runtime UI behavior or
all of SURV-000. Those checks remain open. Package dependencies are locked in
bun.lock; adding the workspace required its manifest in all frontend Docker
build stages. Contracts are initial and have no persistence proof yet.

## 000.A2 — Clean real-service foundation

Passed `./leonaid test-surveys-infrastructure` (exit 0) on 2026-09-06.
A fresh per-invocation Compose project built the actual services, migrated an
empty PostgreSQL database through 0027, seeded a synthetic admin/session, and
verified a persisted survey response snapshot. Updating a published version was
rejected by PostgreSQL; deleting the synthetic survey removed its participation.
The actual API returned readiness and authenticated identity successfully.

Playwright Chromium then opened the member UI with that server session and the
public site through the real proxy, with no mocked API routes (one browser test
passed). The screenshot was inspected locally. This is host infrastructure
evidence, not an implemented survey editor or respondent journey. 000.A3 stays
open in that initial run; the subsequent failure-diagnostic proof below now accepts it.

The command removed its own containers and volumes and checked that none
remained. It published no host ports. The first attempt encountered exhausted
Docker automatic address pools; the runner now selects explicit /24 subnets
that do not overlap the current Docker inventory. It refuses existing project
resources and never prunes other projects. Concurrent subnet allocation can
still cause a safe startup failure; rerun selects another project/subnet set.

Additional checks: three domain boundary tests passed (timeout, restoration and
action-scoped grants); five existing migration/architecture checks passed.
SurveyJS core executed both questionnaire fixtures in pinned Node, proving
basic rendering-model conditions, required matrix values and numeric bounds.
This does not yet prove authoritative answer validation parity.

## Foundation browser failure diagnostics

**000.T2 / 000.A3 / 000.S4 are accepted.** Source: the commit introducing this
section, based on `fecfd78`. The rest of SURV-000 remains open.

`tools/surveys/foundation_acceptance.py` runs two independent fresh Docker stacks
through the existing infrastructure harness. Each migrates to current schema,
proves the database/real-API foundation, publishes the actual questionnaire
fixtures, and creates a separate ordinary account without a global administrator
grant. Chromium authenticates that account and verifies the member UI, public
homepage, and a real published Krapfentaxi survey shell with its title and start
button. Both frontends are reached through the actual proxy; there are no mocked
API routes. The context uses the pinned Playwright default viewport, 1280 × 720
(verified in its installed browserContext implementation). This is not an
accessibility or mobile visual review.

The second browser run deliberately fails an assertion whose received value
contains the actual temporary member-session token and a recognizable test marker.
The restricted reporter retains only status, approved completed-step names, test
file/line/column, error category and counts. Messages, snippets, stacks, titles,
stdout/stderr, attachments and trace contents are excluded. Foundation tracing is
disabled; the failure collector does not copy raw test-result files or screenshots.
Before retaining the JSON, it checks every actual session/fixture environment
value and the error marker against its bytes. Other survey test modes retain their
previous local diagnostic behavior and are not covered by this privacy claim.

| Run | Browser result | Command exit | Retained diagnostics and teardown |
| --- | --- | --- | --- |
| `leonaid-surveys-833458328-94006` | All three steps pass | 0 | No errors, credential scan passed, no owned containers/volumes/networks remain |
| `leonaid-surveys-833458328-94504` | All three steps pass, then deliberate assertion fails | 1 | Assertion location retained, raw error marker absent from command log, actual credential scan passed, no owned containers/volumes/networks remain |

The outer acceptance command exits **0** only after verifying both expected exit
codes, the three completed steps, one result per run, the safe report, the failure
location, and Docker teardown. An earlier infrastructure/setup failure cannot
masquerade as the intended browser failure. The stacks use distinct generated
project names, explicit unused subnets and no published host ports.

```sh
rtk proxy python3 tools/surveys/foundation_acceptance.py "$PWD"
```

The underlying commands are `sh tools/surveys/infrastructure.sh "$PWD"
infrastructure` and the same command with `infrastructure-failure`. The normal
`./leonaid test-surveys-infrastructure` entrypoint continues to run the positive
case. The pinned Playwright image runs Chromium 139.0.7258.5 / Playwright 1.54.1.
The API/worker and frontend images are built from this checkout with the pinned
repository toolchains. Ruff for the three Python files, shell syntax and diff
whitespace checks pass. Final JavaScript whitespace normalization moved the assertion from line 60
to line 61. Locations in the unmodified raw result reflect the tested pre-format
source; no executable behavior changed during formatting.

See the [sanitized two-run result](assets/SURV-000-foundation-diagnostics.json).
Raw command logs remain ignored in `.artifacts/foundation-acceptance/`; foundation
JSON reports are retained in `.artifacts/surveys-infrastructure/foundation/`.
No session files or test traces are committed. The acceptance result proves the
foundation journey and its intentional failure path, not all module journeys,
all personas, the remaining write contracts or the aggregate SURV-100 gate.
