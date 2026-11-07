#!/usr/bin/env python3
"""The timing refit reads real log lines, rejects outliers, keeps a band."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tools.ci import refit_timings as r  # noqa: E402
from tools.ci import select_suites as s  # noqa: E402

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else HERE.parents[1]).resolve()
FAILURES: list[str] = []


def expect(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


LOG = """
2026-11-07T10:00:00Z ci-integration: bin: core passed (300s)
2026-11-07T10:00:00Z ci-integration: bin: policy FAILED (12s)
2026-11-07T10:00:00Z shared-stack: tools/invitations/test.sh 40.5s, exit 0
2026-11-07T10:00:00Z shared-stack: tools/sessions/test.sh 39.5s, exit 0
2026-11-07T10:00:00Z shared-stack: tools/tasks/test.sh 99.0s, exit 1
2026-11-07T10:00:00Z shared-stack: tools/public_actions/test.sh 70s, exit 0
2026-11-07T10:00:00Z shared-stack: tools/activity_feed/test.sh 40s, exit 0
2026-11-07T10:00:00Z ci-e2e: own leaf: tools/multi_host/test.sh 90s, exit 0
2026-11-07T10:00:00Z ci-emdash: OK: krapfentaxi-migration (300s)
2026-11-07T10:00:00Z ci-emdash: OK: redirect-aliases (40s)
"""


def main() -> int:
    leaves = r.e2e_leaves((ROOT / "tools/ci/e2e.sh").read_text(encoding="utf-8"))
    cases = r.emdash_cases((ROOT / "tools/ci/emdash.sh").read_text(encoding="utf-8"))
    expect(set(s.E2E_SHARDS) <= set(leaves), "every E2E shard has parsed leaves")
    expect(all(leaves[x] for x in s.E2E_SHARDS), "no E2E shard without leaf scripts")
    expect(
        leaves["action-admin"] == ["tools/action_admin/test.sh"],
        f"tr-mapped leaf: {leaves['action-admin']}",
    )
    expect(set(s.EMDASH_GROUPS) <= set(cases), "every EmDash group has cases")
    seconds = r.shard_seconds(LOG, leaves, cases)
    expect(seconds.get("core") == 300, f"integration line: {seconds}")
    expect("policy" not in seconds, "a failed shard is no timing")
    expect(
        seconds.get("membership") == 40.5 + 39.5 + r.E2E_SETUP_SHARE,
        f"E2E shard = its leaves plus the setup share: {seconds}",
    )
    expect("tasks" not in seconds, "a failed leaf is no timing")
    expect(
        seconds.get("public-catalog") == 70 + 40 + 90 + r.E2E_SETUP_SHARE,
        f"own-stack leaves count too: {seconds}",
    )
    expect(seconds.get("krapfentaxi-migration") == 340, f"EmDash group sum: {seconds}")
    expect("static" not in seconds, "an incomplete group is no timing")
    # Outliers (outside half to double the median) do not move the value.
    expect(r.robust_median([100, 110, 105, 900, 20]) == 105, "outlier rejection")
    expect(r.robust_median([]) is None, "no observation, no value")
    # The ±15 % band keeps small moves out of the bot's pull request.
    current = {"INTEGRATION_SECONDS": {"core": 226, "policy": 206, "typst": 119}}
    changes = r.refit(
        current, {"core": [300, 310, 290], "policy": [215, 220], "typst": []}
    )
    expect(
        changes == {"INTEGRATION_SECONDS": {"core": 300}},
        f"band and missing data: {changes}",
    )
    # Rewriting touches exactly the changed entries of the real file.
    source = (ROOT / "tools/ci/select_suites.py").read_text(encoding="utf-8")
    rewritten = r.rewrite(
        source, {"INTEGRATION_SECONDS": {"core": 301}, "E2E_SECONDS": {"tasks": 999}}
    )
    expect('\n    "core": 301,' in rewritten, "core rewritten")
    expect('\n    "tasks": 999,' in rewritten, "tasks rewritten")
    changed = [
        (a, b)
        for a, b in zip(source.splitlines(), rewritten.splitlines(), strict=True)
        if a != b
    ]
    expect(len(changed) == 2, f"only two lines change: {changed}")
    try:
        r.rewrite(source, {"E2E_SECONDS": {"no-such-shard": 1}})
        expect(False, "an unknown shard must not be written silently")
    except ValueError:
        pass
    if FAILURES:
        for failure in FAILURES:
            print(f"ci-refit-timings-test: ERROR: {failure}", file=sys.stderr)
        return 1
    print("ci-refit-timings-test: OK: log parsing, outliers, 15 % band, in-place rewrite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
