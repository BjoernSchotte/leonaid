#!/usr/bin/env python3
"""The timing refit reads real log lines, rejects outliers, keeps a band."""

from __future__ import annotations

import shutil
from collections.abc import Callable
import subprocess
import sys
import tempfile
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
2026-11-07T10:00:00Z ci-emdash: OK: campaign-hosts (300s)
2026-11-07T10:00:00Z ci-emdash: OK: redirect-aliases (40s)
"""


def fake_api(
    runs: list[dict[str, object]], logs: dict[int, str]
) -> tuple[Callable[[str], object], Callable[[str], str]]:
    def fetch_json(path: str) -> object:
        if "/workflows/ci.yml/runs" in path:
            return {"workflow_runs": runs}
        run = int(path.split("/actions/runs/")[1].split("/")[0])
        return {
            "jobs": [
                {"id": run * 10 + 1, "name": "Integration 1/4"},
                {"id": run * 10 + 2, "name": "Lint, types and unit"},
            ]
        }

    def fetch_text(path: str) -> str:
        job = int(path.split("/actions/jobs/")[1].split("/")[0])
        if job % 10 != 1:
            raise AssertionError("only stack legs' logs are read")
        if job // 10 not in logs:
            raise subprocess.CalledProcessError(1, ["gh", "api", path])
        return logs[job // 10]

    return fetch_json, fetch_text


def test_collect_and_main(
    leaves: dict[str, list[str]], cases: dict[str, list[str]]
) -> None:
    nightly = [
        {"id": n, "display_title": "LeonAid CI nightly (every E2E leaf)"}
        for n in (1, 2, 3)
    ]
    every3h = [{"id": 9, "display_title": "LeonAid CI main every 3 hours"}]
    logs = {n: f"ci-integration: bin: core passed ({400 + n}s)" for n in (1, 2, 3, 9)}
    fetch_json, fetch_text = fake_api(every3h + nightly, logs)
    found = r.collect("o/r", 7, leaves, cases, fetch_json, fetch_text)
    expect(found == {"core": [401, 402, 403]}, f"only nightly runs count: {found}")
    # No nightly run, no timing at all, or an unreadable log: fail loudly.
    for runs, run_logs, label in (
        (every3h, logs, "no nightly run"),
        (nightly, {n: "nothing here" for n in (1, 2, 3)}, "no timing"),
    ):
        fetch_json, fetch_text = fake_api(runs, run_logs)
        try:
            r.collect("o/r", 7, leaves, cases, fetch_json, fetch_text)
            expect(False, f"{label} must fail")
        except r.RefitError:
            pass
    # main(): --write rewrites a copy of the tree; failures return 1.
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for relative in (
            "tools/ci/select_suites.py",
            "tools/ci/e2e.sh",
            "tools/ci/emdash.sh",
        ):
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / relative, root / relative)
        summary = root / "refit.md"
        fetch_json, fetch_text = fake_api(nightly, logs)
        code = r.main(
            [str(root), "--write", "--summary", str(summary), "--repository", "o/r"],
            fetch_json,
            fetch_text,
        )
        written = (root / "tools/ci/select_suites.py").read_text(encoding="utf-8")
        expect(code == 0, f"main --write exit {code}")
        expect('\n    "core": 402,' in written, "main --write rewrote core")
        expect("| INTEGRATION_SECONDS | core |" in summary.read_text(), "summary table")
        before = written
        fetch_json, fetch_text = fake_api(nightly, {1: logs[1]})
        code = r.main(
            [str(root), "--write", "--repository", "o/r"], fetch_json, fetch_text
        )
        expect(code == 1, "an unreadable log fails the job")
        expect(
            (root / "tools/ci/select_suites.py").read_text(encoding="utf-8") == before,
            "a failed refit writes nothing",
        )
        code = r.main([str(root), "--repository", "o/r"], *fake_api(nightly, logs))
        expect(code == 0, "without --write nothing is written")


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
    # The group's case list grows with emdash.sh; the log names the two cases
    # above and every further case at 10 s, so the sum stays exact.
    extra = [c for c in cases["campaign-edge"] if f"OK: {c} (" not in LOG]
    log = LOG + "".join(
        f"2026-11-07T10:00:00Z ci-emdash: OK: {c} (10s)\n" for c in extra
    )
    seconds = r.shard_seconds(log, leaves, cases)
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
    expect(
        seconds.get("campaign-edge") == 340 + 10 * len(extra),
        f"EmDash group sum: {seconds}",
    )
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
    # Guards: zero values never count, fewer than 3 observations change
    # nothing, and the result is never below 1 s.
    expect(
        r.refit({"T": {"a": 100}}, {"a": [0.0, 0.0, 0.0]}) == {},
        "zero timings are ignored",
    )
    expect(r.refit({"T": {"a": 100}}, {"a": [500]}) == {}, "one run changes nothing")
    expect(
        r.refit({"T": {"a": 100}}, {"a": [500, 0.0, 510]}) == {},
        "two usable runs change nothing",
    )
    expect(
        r.refit({"T": {"a": 100}}, {"a": [500, 490, 510]}) == {"T": {"a": 500}},
        "three usable runs change the value",
    )
    test_collect_and_main(leaves, cases)
    if FAILURES:
        for failure in FAILURES:
            print(f"ci-refit-timings-test: ERROR: {failure}", file=sys.stderr)
        return 1
    print(
        "ci-refit-timings-test: OK: log parsing, outliers, 15 % band, in-place rewrite"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
