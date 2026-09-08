# SURV-100 — Operations, dashboard and application security regressions

**100.3j / 100.S2i are accepted for these three existing suites.** Each complete
command exited zero against real services; a separate inventory then confirmed
zero owned containers, volumes and networks. The original sequence from the
first service build/start through the last business assertion is byte-identical
to the preceding committed harness. No assertion or timing budget was relaxed.

| Suite | Successful verification |
| --- | --- |
| Operations | Real dependency failures, dead-letter handling, authorized UI retry, recovered mail delivery, correlated logs and metrics; one Chromium journey (17.2 seconds). |
| Dashboard | Golden values checked against SQL aggregates, role-specific views, drilldowns, empty state and accessibility; three Chromium journeys (1.0 minute). |
| Application security | TLS and headers, CORS, CSRF, session rotation, RBAC and rate limits; one Chromium rate-limit explanation journey (1.3 seconds). |

[Command results and exact source hashes](assets/SURV-100-operations-regressions.json)
identify the accepted runs. The harness hashes match the checkpoint recorded
before the sequential collector began. Each harness reserves its unique networks
before startup, publishes no host ports and acquires ownership only after empty
resource inventories. Only one owned full service stack ran at a time.

The delivered isolation guard covers 34 harnesses and 136 rejection cases:
occupied containers, volumes, networks and unreadable inventory. The exact
committed subset passes independently; the expanded preparation suite also
passes all 180 cases. These checks establish refusal before Docker mutation;
the service runs above establish application behavior. Shell syntax and the
unchanged business sequences were checked separately.

The initial six-suite preparation has been split by actual result. Feature
flags failed during service readiness; UI system failed a screenshot comparison;
UX acceptance failed a heading wait and the existing main-thread performance
budget. They remain unaccepted under **100.3m / 100.S2l** in the plan.
No passing result in this increment supersedes those failures. Their private
artifacts and subsequent diagnostic changes are outside this commit.

This brings accepted isolated legacy suites to **33 of 42**. The remaining nine,
the complete repeated Survey gate, final CI, capability audit and independent
host-loss recovery remain open. The separate Caddy image-scan disposition is not
included or accepted here. The recurring Survey journey page-transition failure
also remains open; successful frontend simulations do not establish its cause.
