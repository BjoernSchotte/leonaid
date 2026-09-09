# Survey test gate

The agreed functional spike is accepted in [the closeout review](proofs/SURV-100-CLOSEOUT.md).
A command existing or one group passing is never sufficient: the review records
all 39 checks twice, manual evidence and a separate regression for the final
publication-refresh correction. Independent physical host-loss acceptance stays
deferred before production; a future push-triggered CI is not pre-labelled passing.

## Commands

Run from the repository root after `./leonaid bootstrap`:

```sh
./leonaid test-surveys --list
./leonaid test-surveys
./leonaid test-surveys --repeat 2
./leonaid test-surveys --group exports
./leonaid test-surveys --shard exports-download
./leonaid test-surveys-integration
./leonaid test-surveys-exports
./leonaid test-surveys-e2e
```

The default aggregate executes the 26 PR entries from the 39 entries in
[`tools/surveys/gate.json`](../../tools/surveys/gate.json), in manifest order.
`--repeat 2` executes the whole selection twice; each pass resets data between compatible checks. Local runs reuse a private
checkout fixture; CI creates fresh owned resources per pass. This is an explicit local option, not the CI
default. `--shard` selects one complete CI partition and cannot be combined with
`--group`. It does not rerun only failed cases. A nonzero
child exit stops the aggregate immediately and preserves that exit code. Skipped
later checks and missing second-pass checks do not count as passed.

The integration alias selects only `integration`; exports selects
`exports` without nightly checks, and E2E selects `e2e`.
Use `--suite nightly` or `--suite all` to explicitly include backup/recovery. The foundation and packed-consumer groups remain
part of the full aggregate. Existing individual leaf commands remain available.

| Group | Checks | Scope |
|---|---:|---|
| foundation | 8 | Controller process behavior, standalone resource safety, restore receipts, all survey unit tests, validation comparison, dependency inventory, empty/existing-data migrations and deliberate browser failure diagnostics |
| integration | 10 | Real aggregate engine outage/restart, all write contracts, lifecycle and observed competing lock orders, invitations, permissions, aggregates/analysis and public/payload limits |
| editor | 3 | Full editor/authoring/accessibility suite, preview isolation and host branding/completion/progress |
| responses | 2 | Response API and complete autosave, validation-adapter, resume/restart/browser suite |
| exports | 5 | Actual worker products, PDF/XLSX render fixtures, permissions, terminal states, recovery and admission limits |
| recovery | 9 | Deletion/races/UI, retention, recovery, all three Restic modes and nonempty pilot restore/resume |
| package | 1 | Packed independent consumer and real persistence across backend restart |
| e2e | 1 | Both complete sample journeys on desktop/mobile, actual invitation/downloads and independent file/SQL/object erasure verification |

The loader rejects a new infrastructure mode until the manifest covers it,
duplicate mode coverage and recursive aggregate leaf commands. The
CI shard inventory must include every check exactly once; omissions and duplicate
assignments are rejected before CI launches its matrix. The package's
manual rendering/accessibility findings and C-01–C-15/task reconciliation remain
separate acceptance requirements. Passing automation cannot certify them.

## Isolation and diagnostics

Within a checkout, the aggregate holds an OS advisory lock under
`.artifacts/surveys-gate/run.lock`. A competing aggregate exits 75 before launching
any check. Other worktrees have independent locks. Leaf scripts execute
sequentially because some existing artifact directories are shared within one
checkout; do not start individual leaf scripts there while the aggregate runs.

Service harnesses select their own fresh project names and unused explicit
subnets. Survey infrastructure/consumer/migration tests publish no host ports;
the pilot harness allocates free loopback ports for its actual TLS operator
workflow. No global prune or shared-project reset is part of this gate.

Compatible infrastructure checks within one aggregate pass share one initialized
Compose environment. The owner restores its private stopped-volume fixture
between checks; each check seeds its own data and starts fresh application
processes. Images, containers and networks are reused. An exclusive fixture
lease prevents a reset while a leaf is active. Independent runs never share
projects, volumes or fixture snapshots. Standalone calls, foundation cold-build
checks and nightly recovery harnesses retain their original path. See
[CI runtime](../../tools/ci/README.md) for reset scope and exceptions.

Raw child stdout/stderr is saved in owner-only logs beneath
`.artifacts/surveys-gate/private-*/`. It is neither echoed by the controller nor
included in the published result directory. These logs and the existing local
traces/downloads can contain synthetic answers or transient credentials and must
remain local and ignored. Inspect only the relevant failure when diagnosing it.

Each run creates a distinct JSON result under
`.artifacts/surveys-gate/results/`, initially `running`, then `passed`, `failed`
or `interrupted`. Results contain the commit, manifest digest, selected groups/shard,
requested passes, per-check exit codes/durations and remaining manual-review
references. They contain no child output, arbitrary command arguments, tokens,
answers, recipient addresses, raw traces or downloaded files. A `running` result
is not proof that its process is still alive; inspect the actual process handle.

SIGINT/SIGTERM is forwarded to the owned child process group. The controller
waits for that process and its cleanup and returns 130. It does not kill or clean
unrelated Docker resources. SIGKILL cannot produce a completed result; such a run
remains unaccepted and requires checking its exact owned resources.

## CI and final acceptance

[`surveys.yml`](../../.github/workflows/surveys.yml) partitions the manifest's 17 CI
shards into 11 regular and six nightly shards. Each selected shard uses a separate
ephemeral runner and runs once after bootstrap. The historical two-pass spike acceptance above remains a record
of that revision. The PR selection covers 26 checks; the nightly selection covers the other 13
(Recovery, export recovery and restore receipts). The night schedule is 01:17 UTC
daily; manual dispatch can run either selection or all 39 checks. Existing
`Surveys / <group>` check names summarize the selected matrix and require every selected shard to
succeed, including when other shards fail or are cancelled.
The controller and diagnostic collector share the container proof
owner on Linux. Only `results/*.json` and the fixed
`results/diagnostics/metadata.json` are copied into `$RUNNER_TEMP/surveys-ci-results/`
for upload; private logs and general `.artifacts` contents remain excluded and
owner-only. All selected matrix jobs must pass for the same revision. A PR summary does not
claim execution of nightly checks. Local
proof does not substitute for observing the actual GitHub Actions run.

This survey aggregate does not invoke the repository's 42-command
`test-integration` suite or replace **100.A3**. Those existing regression checks
have their own acceptance, including safe isolation of their legacy harnesses.
Independent physical host-loss recovery and independent newest-deletion-cutoff
provenance are deferred to deployment-specific operational acceptance before
production use, as agreed in PLAN.md. They are not counted as passing tests.
Existing local recovery and deletion-reapplication checks remain mandatory.


## Bounded CI diagnostics

After a CI group stops, `ci_diagnostics.py` emits fixed error-category names and
locations in tracked public source files. It reads only manifest-named gate logs
and the two known foundation logs, ignores symlinks and never serializes raw
messages, source excerpts, expected/actual values, private paths or attachments.
Locations must point to an existing line in a tracked source file. Presence of a
marker is diagnostic context, not proof of a root cause or failed assertion.
Four tests cover private markers, unknown paths, impossible lines, unreviewed log
names, symlinked logs and actual repository-file selection. The metadata lives
under `results/diagnostics/`; it is separate from per-run acceptance results.
