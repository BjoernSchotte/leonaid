# SURV-100 — Complete survey CI, two passes

## Accepted scope

**100.A1 is accepted at source commit `e03083601786911eaf57f95f63ba835a22663213`.**
The [Survey acceptance run](https://github.com/BjoernSchotte/leonaid/actions/runs/34192365764)
completed all eight manifest groups. Every one of the 38 named checks ran twice
and returned zero: **76 successful executions**, with no missing, duplicated or
substituted check within either pass.

The tested PR merge commit was `738c1d216f67dfeeccb2db0180fc426adf8d4dd1`.
GitHub's compare API returned an empty changed-file list against the source
commit. Each downloaded result names that same merge commit and manifest SHA-256
`c48840bfc159665bba969ecfe4bc318b94ad9c497db3e893dbc29249f52d468f`.

[Structured evidence](assets/SURV-100-CI-REPEAT.json) records every check,
iteration, exit code and duration, plus hashes of the original downloaded reports.
The reports were checked against the ordered Cartesian product of each manifest
group's check IDs and passes 1 and 2; green job badges alone were not used.

| Group | Checks per pass | Successful executions |
|---|---:|---:|
| Foundation | 7 | 14 |
| Integration | 10 | 20 |
| Editor | 3 | 6 |
| Responses | 2 | 4 |
| Exports | 5 | 10 |
| Recovery | 9 | 18 |
| Package | 1 | 2 |
| E2E | 1 | 2 |

## Actual command and coverage

The workflow reads `tools/surveys/gate.json`, the same manifest as the local
aggregate. Each separate runner executes:

```sh
sudo ./leonaid test-surveys --group "$SURVEY_GATE_GROUP" --repeat 2
```

`tools/surveys/gate.py` executes every selected child synchronously, records its
terminal exit, and rejects the group on a failed child. It also rejects unmapped
or repeated infrastructure modes. The matrix partitions the complete manifest;
it does not select a reduced CI-only suite.

The migration check creates fresh PostgreSQL volumes, checks empty and existing
data upgrades, repeats migrations, and removes its container, volume and network.
Each `infrastructure.sh` invocation uses a fresh project, refuses existing project
resources, reserves isolated networks, publishes no host ports, and starts real
API, PostgreSQL, worker and object storage services. Its cleanup checks container,
volume and network inventories and fails if owned resources remain.

The runner check includes persisted answers across API/worker restart and
validator outage/recovery. Export recovery exercises worker/object-storage
failures. Recovery includes deletion races, deletion UI, retention, restart
recovery, all three Restic modes and pilot survey recovery. The package group
runs the independent packed consumer. The E2E group completes both sample surveys
at desktop and mobile sizes, including the independent export/erasure verifier.
These are the actual manifest children, not substitutions inferred from unit tests.

## Boundaries that remain open

This accepts the complete repeated survey suite at the recorded revision. It does
not accept later uncommitted working-tree changes or establish that an intermittent
browser failure can never recur. The strengthened rating helper subsequently
passed its [separate complete local live run](SURV-100-RATING-JOURNEY.md); that
result does not establish the historical CI failure's cause.

**100.1, 100.T1, 100.A3–A5 and full spike completion remain open.** Existing
application/operator regressions, the final capability/delivery review and
SURV-090 independent-host-loss recovery are separate requirements. The same
reports retain all three manual-review references.

**100.S1 remains open for final cleanup reconciliation across every harness.**
At this historical CI revision, the Restic success path verifies source/target
container and volume removal, but its trap suppresses archive-volume removal
errors and does not independently assert final network absence. That gap is now
fixed and all three complete modes pass with strict cleanup and independent final
inventories: [Restic cleanup evidence](SURV-100-RESTIC-CLEANUP.md). This new scoped
proof does not retroactively strengthen the 76 historical exits or accept the
final cross-harness cleanup and repeated aggregate.

No raw browser trace, credential, session file or unrestricted service log is
included in this proof. Own package licensing remains **UNDEFINED**; no publication
or commercial dependency decision is made here.
