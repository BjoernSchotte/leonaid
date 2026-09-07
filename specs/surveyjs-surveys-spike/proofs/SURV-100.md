# SURV-100 — Acceptance evidence in progress

Overall status: **open**. This file records scoped checks; it does not accept the
aggregate lane, complete sample journeys, recovery gates or remaining regressions.

## React peer policy and packed consumer

Source: the commit introducing this section, based on `84cfab6`.

| Task | Implementation and assertions | Result |
| --- | --- | --- |
| 100.3a | `tools/pins/check.py` permits only `react` and `react-dom` at `^19.2.8`, only in `peerDependencies` of `packages/surveys/package.json` with the expected package name. Direct LeonAid hosts must declare both runtimes at exactly `19.2.8`. | Accepted |
| 100.3a policy negatives | `tools/pins/peer_policy_test.py` rejects broader/different ranges, unrelated dependencies, other sections/paths/names, and missing/ranged/unproven host runtimes. The existing image, Python and frontend drift fixtures remain active in `tools/pins/test.sh`. | Six peer-policy tests and four existing negative cases pass |
| 100.3a installation | Frozen workspace installation keeps the lock unchanged. The packed consumer installs with its separate frozen lock, asserts peer declarations and actual exact runtime versions, and resolves no LeonAid workspace package. | Pass |
| 100.3a browser integration | `tests/e2e/surveys-package.spec.mjs`: multipage response saved through the real SQLite adapter; editor translation preserves author content/history; backend restart restores both respondent data and editor draft without an extra respondent save. | Four Chromium tests pass |

The package's compatibility declaration stays distinct from tested runtime
versions. This is evidence for React/React DOM **19.2.8**, not proof of future
versions in the peer range. SurveyJS core/React renderer remain **3.0.3**. No
dependency version, lockfile or own license decision changed. The package remains
private/`UNLICENSED`; the intended own license remains **UNDEFINED**.

Commands (repository root; all exit zero):

```sh
# Pinned UV image from infra/locks/images.env, with network disabled:
uv run --frozen --no-sync sh tools/pins/test.sh /workspace
uv run --frozen --no-sync ruff check tools/pins/check.py tools/pins/peer_policy_test.py
uv run --frozen --no-sync mypy tools/pins/check.py tools/pins/peer_policy_test.py
# Pinned Bun 1.2.19 image, with network disabled:
bun install --frozen-lockfile --ignore-scripts
# Host orchestration; builds and runs pinned containers:
rtk proxy sh tools/surveys/package.sh "$PWD"
```

The UV/Bun commands run with the repository mounted at `/workspace`, working
directory `/workspace`, and `PYTHONPATH=/workspace` for Python. The full pin
checker accepts 23 images and 89 Python packages. Bun reports 433 installations
across 542 packages, with no changes. Ruff and strict MyPy accept both Python
files. The packed consumer inventory is retained in
[SURV-100-package.json](assets/SURV-100-package.json).

The consumer harness allocates a unique worktree/PID project, selects an unused
subnet, publishes no host ports and removes its own container, data volume,
network and image. It uses an empty SQLite volume and restarts the actual backend
between browser groups. The final run used `surveys-package-833458328-74769`;
the two Chromium groups passed in 7.3 seconds and 2.1 seconds, and teardown
completed with exit zero. Build layers may be cached; this is not a claim of an
uncached dependency download or the full clean-stack aggregate gate.

Remaining: 100.1–100.4, 100.T1–100.T2 and 100.A1–100.A5 remain open except for the
specific 100.3a contribution above. Complete affected regression suites, both
full desktop/mobile sample journeys, predecessor recovery acceptance and the
capability/outcome report before declaring SURV-100 complete.
