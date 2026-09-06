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
