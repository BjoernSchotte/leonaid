# Survey test gate

The aggregate implementation is under verification. A command existing or a
single group passing does not accept **100.A1**, the remote CI lane or the whole
spike. Consult the per-run result and the acceptance checklist.

## Commands

Run from the repository root after `./leonaid bootstrap`:

```sh
./leonaid test-surveys --list
./leonaid test-surveys
./leonaid test-surveys --repeat 2
./leonaid test-surveys --group exports
./leonaid test-surveys-integration
./leonaid test-surveys-exports
./leonaid test-surveys-e2e
```

The default aggregate executes all 37 entries in
[`tools/surveys/gate.json`](../../tools/surveys/gate.json), in manifest order.
`--repeat 2` executes the whole selection twice; every service harness creates
fresh owned resources each time. It does not rerun only failed cases. A nonzero
child exit stops the aggregate immediately and preserves that exit code. Skipped
later checks and missing second-pass checks do not count as passed.

The integration alias selects `integration` and `recovery`; exports selects
`exports`, and E2E selects `e2e`. The foundation and packed-consumer groups remain
part of the full aggregate. Existing individual leaf commands remain available.

| Group | Checks | Scope |
|---|---:|---|
| foundation | 7 | Controller process behavior, restore receipts, all survey unit tests, validation comparison, dependency inventory, empty/existing-data migrations and deliberate browser failure diagnostics |
| integration | 9 | Real aggregate engine outage/restart, all write contracts, lifecycle, invitations, permissions, aggregates/analysis and public/payload limits |
| editor | 3 | Full editor/authoring/accessibility suite, preview isolation and host branding/completion/progress |
| responses | 2 | Response API and complete autosave, validation-adapter, resume/restart/browser suite |
| exports | 5 | Actual worker products, PDF/XLSX render fixtures, permissions, terminal states, recovery and admission limits |
| recovery | 9 | Deletion/races/UI, retention, recovery, all three Restic modes and nonempty pilot restore/resume |
| package | 1 | Packed independent consumer and real persistence across backend restart |
| e2e | 1 | Both complete sample journeys on desktop/mobile, actual invitation/downloads and independent file/SQL/object erasure verification |

The loader rejects a new infrastructure mode until the manifest covers it,
duplicate mode coverage and recursive aggregate leaf commands. The package's
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

Raw child stdout/stderr is saved in owner-only logs beneath
`.artifacts/surveys-gate/private-*/`. It is neither echoed by the controller nor
included in the published result directory. These logs and the existing local
traces/downloads can contain synthetic answers or transient credentials and must
remain local and ignored. Inspect only the relevant failure when diagnosing it.

Each run creates a distinct JSON result under
`.artifacts/surveys-gate/results/`, initially `running`, then `passed`, `failed`
or `interrupted`. Results contain the commit, manifest digest, selected groups,
requested passes, per-check exit codes/durations and remaining manual-review
references. They contain no child output, arbitrary command arguments, tokens,
answers, recipient addresses, raw traces or downloaded files. A `running` result
is not proof that its process is still alive; inspect the actual process handle.

SIGINT/SIGTERM is forwarded to the owned child process group. The controller
waits for that process and its cleanup and returns 130. It does not kill or clean
unrelated Docker resources. SIGKILL cannot produce a completed result; such a run
remains unaccepted and requires checking its exact owned resources.

## CI and final acceptance

[`surveys.yml`](../../.github/workflows/surveys.yml) reads the same manifest groups
into a matrix. Each group uses a separate ephemeral runner and runs twice after
bootstrap. Only `results/*.json` is uploaded; private logs and general `.artifacts`
contents are excluded. All matrix jobs must pass for the same revision. Local
proof does not substitute for observing the actual GitHub Actions run.

This survey aggregate does not invoke the repository's 42-command
`test-integration` suite or replace **100.A3**. Those existing regression checks
have their own acceptance, including safe isolation of their legacy harnesses.
The unresolved host-loss recovery and other open criteria remain required even
when a narrower recovery fixture or the complete automated gate passes.
