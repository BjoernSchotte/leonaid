# CI runtime

The Integration job is a required-check summary over six independent runners:
Compose cold start, seed/reset, Core, documents/storage, CRM and pilot import.
`bash tools/ci/integration.sh` still runs all 13 original scripts locally;
an optional shard argument runs one subset.

Survey acceptance reads its 16 shards from `tools/surveys/gate.json`.
The manifest validator requires all 39 checks to appear exactly once. Each
check runs once in CI. Existing `Surveys / <group>` check names remain as
conservative summaries: every shard must succeed before any summary passes.
Failure, cancellation or skipping of a shard cannot produce a green summary.

```sh
./leonaid test-surveys --shard integration-limits
./leonaid test-surveys --group integration
```

Within a locked survey aggregate, infrastructure checks reuse images built
from that checkout. Image names are scoped to the private run directory;
later checks use `--no-build`. The cache contains only image-name overrides,
not rendered Compose configuration, credentials or runtime data. Builds must
succeed before the cache is marked ready. Missing images fail the check.

Every check still owns fresh containers, networks and volumes and verifies
their teardown. Standalone infrastructure calls and foundation cold-build
checks keep their full build path. A new aggregate (or explicit repeat pass)
gets a new image namespace. Generated images remain local, like other test
builds, and are discarded with the ephemeral GitHub runner. No global Docker
pruning or shared database snapshots are introduced.

PR #4 baseline: Integration 37:52; Surveys / exports 34:35. The export group's
second pass alone took 14:57. These are observed baseline times, not a promise
of the new workflow's duration. Compare wall time and total runner minutes
after running the new workflow; additional runners trade parallel capacity
for shorter feedback time.
