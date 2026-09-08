# Standalone survey test resource safety

This closes the identified standalone-harness collision and cleanup defect.
It does not accept the full SURV-100.1 or the final aggregate gate.

`migrations.sh`, `package.sh` and `aggregate-engine.sh` now read exact container,
volume, network and image inventories before mutation. An unreadable inventory
or an existing name aborts the run. Creation attempts are tracked before Docker
commands; cleanup attempts all owned removals and returns nonzero on removal
failure or remaining resources. Signals retain unsuccessful exit codes.

## Real Docker safety proof

Command: `python3 tools/surveys/standalone_resources_live.py` — exit **0**.
The test uses real Docker resources and the actual harness entrypoints:

- All three scripts reject a probe-owned pre-existing volume before mutation;
  its complete inspected metadata stays unchanged and no other named resource
  appears.
- A stopped container keeps a volume busy. Cleanup reports failure but still
  removes the owned network. Removing the holder and retrying succeeds; all
  four inventories confirm absence.
- All three scripts reject an unavailable Docker daemon as an inventory error.

## Complete successful runs

Each command ran from the worktree root, sequentially after both Caddy pilots.
Each final result includes four independent readable inventories confirming no
owned container, volume, network or image tag remained. No host ports were used.

| Command | Exit | Seconds | Actual coverage |
| --- | --- | --- | --- |
| `sh tools/surveys/migrations.sh "$PWD"` | 0 | 382.399 | Empty and existing-data upgrades to 0034, repeated migration, 30 PostgreSQL invariants and preserved existing data |
| `sh tools/surveys/package.sh "$PWD"` | 0 | 179.244 | Four Chromium tests in a packed external consumer, SQLite persistence across restart, translated draft/history and host theme/messages |
| `sh tools/surveys/aggregate-engine.sh "$PWD"` | 0 | 222.372 | Real HTTP counts/NPS/matrix/relevance, raw-text exclusion, bounded batches, stopped-service rejection and recovery after restart |

The [machine-readable evidence](assets/SURV-100-standalone-resources.json)
records exact source hashes, projects, exit codes and timings. The controller
also checked unchanged main source hashes during all three runs. The changes
are relative to parent commit `5aedbe5`; the hashes identify the actual dirty
inputs tested before this delivery commit. Existing service-image pins were
used; the subsequent Caddy integration is a separate change.

`tools/surveys/gate.json` includes this safety test in the foundation group.
The revised complete aggregate has **39 checks per pass**, requiring **78 zero
exits** for its final two-pass proof. Historical 38-check results remain
historical evidence. Gate-controller tests (7), the no-test-doubles policy,
pinned Ruff 0.12.5 formatting/lint and shell syntax checks pass.
