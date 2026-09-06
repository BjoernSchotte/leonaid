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
open until deliberate failure diagnostics are also demonstrated.

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
