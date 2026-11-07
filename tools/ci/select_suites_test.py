#!/usr/bin/env python3
"""Prove the PR-tier suite selection against real repository paths."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tools.ci import select_suites as s  # noqa: E402

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else HERE.parents[1]).resolve()
FAILURES: list[str] = []


def expect(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def pr(*paths: str) -> s.Selection:
    return s.select("pull_request", list(paths))


def broad(selection: s.Selection, *owners: str) -> bool:
    """Unknown/shared: every non-E2E suite, the smoke leg, mapped leaves only."""
    return not selection.full and selection.suites == s.everything_but_e2e() | {
        s.SMOKE
    } | s.e2e(*owners)


def full(selection: s.Selection) -> bool:
    return bool(selection.full and selection.suites == s.everything())


BINNED = ("integration", "e2e", "emdash")


def outputs(*paths: str) -> dict[str, Any]:
    """Selector outputs; matrix bins flattened to their shard names."""
    raw = {k: json.loads(v) for k, v in pr(*paths).outputs().items() if k != "reason"}
    for key in BINNED:
        raw[key] = [shard for leg in raw[key] for shard in leg["shards"].split()]
    return raw


def stack_suites(result: dict[str, Any]) -> dict[str, Any]:
    """Only what starts a runner: matrix shards plus the flags."""
    return {
        k: v for k, v in result.items() if k in BINNED or (v is True and k != "heavy")
    }


# Path -> exactly the suites it must start (flags that are true, shard lists).
PRECISE: tuple[tuple[str, dict[str, Any]], ...] = (
    # Gate data of always-running jobs: Security judges the allowlist, the
    # pins workflow checks the policy; no stack suite reads it.
    ("infra/security/vulnerability-allowlist.json", {"pins": True}),
    ("infra/security/image-scan-scope.json", {"pins": True}),
    ("tools/ci/reviewed_network_faults.json", {}),
    ("tools/ci/gate.py", {}),
    ("tools/ci/gate_test.py", {}),
    ("tools/ci/workflow_contract.py", {}),
    ("tools/ci/security.sh", {}),
    ("tools/ci/lint-types.sh", {}),
    ("tools/ci/flake_summary.py", {}),
    ("tools/ci/build.sh", {}),
    ("specs/leonaid-poc/KNOWN-LIMITS.md", {}),
    ("apps/docs/src/content/docs/de/index.mdx", {}),
    (".github/workflows/docs.yml", {}),
    (".github/workflows/nightly-watchdog.yml", {}),
    (".github/workflows/release.yml", {}),
    (".github/workflows/surveys.yml", {"surveys": True}),
    (".github/workflows/api-contract.yml", {"api": True}),
    (".github/workflows/pins.yml", {"pins": True}),
    ("tools/ci/contract.sh", {"contract": True, "integration": ["contract"]}),
    (
        "tools/ci/e2e.sh",
        {"e2e": sorted(s.E2E_SHARDS)},
    ),
    (
        "tools/ci/integration.sh",
        {
            "contract": True,
            "integration": sorted([*s.INTEGRATION_SHARDS, "contract"]),
        },
    ),
    ("tools/ci/emdash.sh", {"emdash": sorted(s.EMDASH_GROUPS)}),
    ("tools/delivery/foundation.py", {"integration": ["delivery"]}),
    ("tools/pwa/test.sh", {"e2e": ["pwa"]}),
)


def case_labels(script: Path) -> set[str]:
    """Labels of the two-space-indented shell `case` arms in tools/ci/<name>.sh."""
    labels: set[str] = set()
    for line in script.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^  ([a-z0-9|-]+)\)$", line)
        if match:
            labels.update(match.group(1).split("|"))
    return labels


def main() -> int:
    # Every event except pull_request runs everything.
    for event in ("push", "schedule", "workflow_dispatch"):
        selection = s.select(event, ["README.md"])
        expect(full(selection), f"{event} must select the complete suite")
    # No readable diff is never an excuse to skip.
    expect(full(pr()), "an empty PR diff must select everything")
    # Unknown paths select everything.
    for path in (
        "brand-new/thing.py",
        "tools/new_module/test.sh",
        "apps/web/src/app.tsx",
    ):
        expect(broad(pr(path)), f"unmapped {path}: all non-E2E suites plus smoke")
    # Shared infrastructure: every non-E2E suite plus smoke, E2E only mapped.
    for path in (
        ".github/workflows/ci.yml",
        ".github/workflows/select-suites.yml",
        ".github/workflows/test-fixture.yml",
        ".github/actions/build-cache/action.yml",
        "tools/ci/select_suites.py",
        "tools/ci/run-job.sh",
        "tools/ci/free-runner-disk.sh",
        "tools/ci/sanitize_artifacts.py",
        "tools/ci/docker-bake.hcl",
        "tools/testing/shared_stack.py",
        "infra/compose/compose.yml",
        "infra/locks/images.env",
        "infra/proxy/Caddyfile",
        "migrations/versions/0041_tasks.py",
        "src/leonaid/platform/http.py",
        "src/leonaid/bootstrap/api.py",
        "src/leonaid/adapters/postgres/outbox.py",
        "src/leonaid/application/delivery.py",
        "package.json",
        "bun.lock",
        "uv.lock",
        "pyproject.toml",
        "leonaid",
        "tools/surveys/network_override.py",
        "tests/fixtures/golden/v1/README.md",
    ):
        owners = s.e2e_owners(path, ROOT) or set()
        expect(
            broad(pr(path), *owners),
            f"shared {path}: all non-E2E suites, smoke, mapped leaves {owners}",
        )
    # Documentation-only PRs run no stack suite at all.
    docs = outputs(
        "apps/docs/src/content/docs/en/user/how-to/plan-tasks.md",
        "apps/docs/product-contracts.json",
        "specs/modular-platform/README.md",
        "tools/delivery/README.md",
        "README.md",
    )
    expect(
        docs["integration"] == []
        and docs["e2e"] == []
        and docs["emdash"] == []
        and not any(docs[flag] for flag in s.FLAGS),
        f"docs-only PR selected stack suites: {docs}",
    )
    # Module-local changes stay local.
    tasks = outputs(
        "src/leonaid/modules/tasks/api.py", "tests/e2e/tasks-views.spec.mjs"
    )
    expect(tasks["e2e"] == ["tasks"], f"tasks module: {tasks}")
    expect(
        tasks["integration"] == [] and tasks["emdash"] == [], f"tasks module: {tasks}"
    )
    expect(tasks["api"] is True and tasks["surveys"] is False, f"tasks module: {tasks}")
    delivery = outputs("tools/delivery/foundation.py")
    expect(
        delivery["integration"] == ["delivery"] and delivery["e2e"] == [],
        f"delivery: {delivery}",
    )
    campaign = outputs(
        "apps/campaign-site/emdash-editor-patch.mjs",
        "tools/emdash_spike/auth-patch-proof.mjs",
    )
    expect(campaign["emdash"] == list(s.EMDASH_GROUPS), f"campaign site: {campaign}")
    expect(
        campaign["e2e"] == []
        and campaign["integration"] == []
        and campaign["api"] is False,
        f"campaign site must not start Core suites: {campaign}",
    )
    surveys = outputs(
        "packages/surveys/src/index.ts", "tests/e2e/surveys-editor.spec.mjs"
    )
    expect(surveys["surveys"] is True and surveys["e2e"] == [], f"surveys: {surveys}")
    # Cross-suite helpers select every suite that imports them.
    orders = outputs("tools/public_orders/contract.py")
    expect(
        orders["emdash"] != [] and "public-orders" in orders["e2e"],
        f"public orders: {orders}",
    )
    expect("delivery" in orders["integration"], f"public orders: {orders}")
    identity = outputs("tools/identity/contract.py")
    expect(
        identity["emdash"] != [] and identity["e2e"] == ["identity"],
        f"identity: {identity}",
    )
    # Formerly path-filtered workflows keep their historical filters.
    expect(
        outputs("infra/security/vulnerability-allowlist.json")["pins"] is True,
        "pins filter",
    )
    expect(outputs("tools/openapi/generate.py")["api"] is True, "API filter")
    expect(
        outputs("tests/unit/test_x.py")["api"] is True, "API filter keeps tests/unit"
    )
    expect(outputs("tests/unit/test_x.py")["e2e"] == [], "unit tests run no stack")
    # Stacked pull requests (base is not main): module-local suites only.
    stack_paths = [
        "migrations/versions/0052_x.py",
        "infra/compose/compose.yml",
        "apps/web/src/app.tsx",
        "brand-new/thing.py",
        "uv.lock",
        "src/leonaid/modules/tasks/api.py",
        "tools/delivery/foundation.py",
    ]
    stacked_run = s.select("pull_request", stack_paths, "md/stage2c")
    raw = {k: json.loads(v) for k, v in stacked_run.outputs().items() if k != "reason"}
    expect(raw["heavy"] is False, "a stacked PR skips Security and Build")
    expect(
        [leg["shards"] for leg in raw["e2e"]] == ["tasks"]
        and [leg["shards"] for leg in raw["integration"]] == ["delivery"]
        and raw["emdash"] == []
        and not any(raw[flag] for flag in s.FLAGS),
        f"a stacked PR runs only module-local suites: {raw}",
    )
    expect(
        not stacked_run.full and "stacked" in stacked_run.reason,
        f"stacked reason: {stacked_run.reason}",
    )
    # The same diff into main keeps the complete, heavy selection.
    for base in ("main", ""):
        into_main = s.select("pull_request", stack_paths, base)
        expect(
            into_main.heavy
            and s.everything_but_e2e() <= into_main.suites
            and s.SMOKE in into_main.suites,
            f"base {base!r} must run every non-E2E suite: {into_main.reason}",
        )
    # Every other event ignores the base branch and runs everything.
    expect(
        full(s.select("push", stack_paths, "md/stage2c"))
        and s.select("push", [], "x").heavy,
        "push stays complete",
    )
    # A stacked PR without a readable diff stays fail-safe.
    expect(full(s.select("pull_request", [], "md/stage2c")), "stacked empty diff")
    expect(
        json.loads(pr("README.md").outputs()["heavy"]) is True,
        "a PR into main always runs Security and Build",
    )

    # E2E policy (2026-11-07): import graph, smoke leg, label, schedules.
    graph_cases = {
        "src/leonaid/application/invoices.py": {"invoices", "invoice-flows"},
        "src/leonaid/modules/tasks/api.py": {"tasks"},
        "src/leonaid/domain/sessions.py": {"membership"},
        "src/leonaid/application/public_orders.py": {"public-orders"},
    }
    for path, must in graph_cases.items():
        owners = s.e2e_owners(path, ROOT)
        expect(owners is not None and must <= owners, f"{path}: owners {owners}")
    expect(s.e2e_owners("apps/web/src/app.tsx", ROOT) is None, "non-Python path")
    errors = s.e2e_owners("src/leonaid/domain/errors.py", ROOT) or set()
    expect(len(errors) >= 10, f"a shared domain module fans out: {errors}")
    expect(
        s.e2e_owners("src/leonaid/domain/brand_new_thing.py", ROOT) == set(),
        "a new module nothing imports maps to no leaf",
    )
    # A graph hit adds exactly its leaves; the smoke leg runs alone.
    invoice_pr = s.select(
        "pull_request", ["src/leonaid/application/invoices.py"], "main", root=ROOT
    )
    legs = json.loads(invoice_pr.outputs()["e2e"])
    expect(legs[-1]["shards"] == s.SMOKE, f"smoke leg last and alone: {legs}")
    expect(
        all(s.SMOKE not in leg["shards"].split() for leg in legs[:-1]),
        f"the smoke leg is never packed with leaves: {legs}",
    )
    # The full-e2e label adds every leaf and drops the redundant smoke leg.
    labelled = s.select("pull_request", ["apps/web/src/app.tsx"], "main", full_e2e=True)
    labelled_legs = json.loads(labelled.outputs()["e2e"])
    expect(
        labelled.full
        and sorted(x for leg in labelled_legs for x in leg["shards"].split())
        == sorted(s.E2E_SHARDS),
        f"full-e2e label: every leaf, no smoke: {labelled_legs}",
    )
    expect(
        not s.select(
            "pull_request", ["tools/pwa/test.sh"], "md/x", full_e2e=True
        ).suites
        & s.e2e(*[x for x in s.E2E_SHARDS if x != "pwa"]),
        "the label does not widen a stacked PR",
    )
    # The 3-hourly main run: everything except the E2E leaves, plus smoke.
    every3h = s.select("schedule", [], schedule=s.MAIN_SCHEDULE)
    every3h_legs = json.loads(every3h.outputs()["e2e"])
    expect(
        every3h.suites == s.everything_but_e2e() | {s.SMOKE}
        and [leg["shards"] for leg in every3h_legs] == [s.SMOKE]
        and every3h.heavy,
        f"3-hourly main run: {every3h.reason} {every3h_legs}",
    )
    # The nightly run (and any other schedule or dispatch) runs every leaf.
    for event, cron in (("schedule", s.NIGHTLY_SCHEDULE), ("workflow_dispatch", "")):
        nightly = s.select(event, [], schedule=cron)
        expect(full(nightly), f"{event} {cron!r} must run every E2E leaf")
        expect(
            all(
                s.SMOKE not in leg["shards"]
                for leg in json.loads(nightly.outputs()["e2e"])
            ),
            "a complete run needs no smoke leg",
        )
    # Docs-only pull requests still start no stack suite, not even smoke.
    expect(
        json.loads(pr("README.md").outputs()["e2e"]) == [],
        "docs-only PR runs no smoke leg",
    )
    # The smoke leg is defined in the CI entry point.
    expect(s.SMOKE in case_labels(ROOT / "tools/ci/e2e.sh"), "tools/ci/e2e.sh smoke")

    # Precise selection: each path starts exactly its own suites.
    for path, expected in PRECISE:
        got = stack_suites(outputs(path))
        want: dict[str, Any] = {key: [] for key in BINNED} | expected
        got = {k: sorted(v) if isinstance(v, list) else v for k, v in got.items()}
        expect(got == want, f"{path}: expected {want}, got {got}")
    # Fewer, fatter jobs: the complete run packs every shard exactly once
    # into at most MAX_BINS legs per kind; durations exist for every shard.
    expect(
        set(s.INTEGRATION_SECONDS) == {*s.INTEGRATION_SHARDS, "contract"},
        "INTEGRATION_SECONDS must list every Integration shard and contract",
    )
    expect(
        set(s.E2E_SECONDS) == {*s.E2E_SHARDS, s.SMOKE},
        "E2E_SECONDS must list every leaf and the smoke leg",
    )
    expect(
        sorted(g for b in s.EMDASH_BINS for g in b) == sorted(s.EMDASH_GROUPS),
        "EMDASH_BINS must hold every EmDash group exactly once",
    )
    complete = s.select("push", []).outputs()
    for key, names, seconds in (
        ("integration", [*s.INTEGRATION_SHARDS, "contract"], s.INTEGRATION_SECONDS),
        ("e2e", list(s.E2E_SHARDS), s.E2E_SECONDS),
    ):
        legs = json.loads(complete[key])
        packed = [shard for leg in legs for shard in leg["shards"].split()]
        expect(sorted(packed) == sorted(names), f"{key}: bins lose or repeat shards")
        expect(len(legs) == s.MAX_BINS[key], f"{key}: {len(legs)} legs")
        loads = [sum(seconds[x] for x in leg["shards"].split()) for leg in legs]
        expect(loads == sorted(loads, reverse=True), f"{key}: longest bin first")
        expect(
            max(loads) - min(loads) <= max(seconds.values()),
            f"{key}: unbalanced bins {loads}",
        )
        expect(
            [leg["id"] for leg in legs] == [str(i) for i in range(1, len(legs) + 1)],
            f"{key}: leg ids must be 1..n",
        )
    for leg in json.loads(complete["integration"]):
        seed = bool(s.SEED_BOOTSTRAP & set(leg["shards"].split()))
        expect(
            leg["bootstrap"] == ("seed" if seed else "toolchains"),
            f"integration bootstrap: {leg}",
        )
    full_selection = s.select("push", [])
    expect(s.load_warnings(full_selection) == [], "complete run warns about leg load")
    for kind, bins, seconds in (
        ("integration", full_selection.integration_bins(), s.INTEGRATION_SECONDS),
        ("e2e", full_selection.e2e_bins(), s.E2E_SECONDS),
        ("emdash", full_selection.emdash_bins(), s.EMDASH_SECONDS),
    ):
        longest = max(s.leg_estimate(kind, b, seconds) for b in bins)
        expect(
            longest < 0.6 * s.JOB_TIMEOUT_MINUTES[kind] * 60,
            f"{kind}: longest leg {longest} s is too close to its timeout",
        )
    expect(set(s.EMDASH_SECONDS) == set(s.EMDASH_GROUPS), "EMDASH_SECONDS")
    expect(
        s.leg_estimate("integration", ["core", "policy"], s.INTEGRATION_SECONDS)
        == s.LEG_SETUP_SECONDS + 2 * s.SHARD_SETUP_SECONDS["integration"] + 226 + 206,
        "Integration estimates count a stack boot per shard",
    )
    original = dict(s.E2E_SECONDS)
    try:
        s.E2E_SECONDS["operations"] = 4000
        expect(
            any("e2e leg" in w for w in s.load_warnings(full_selection)),
            "a leg near its timeout must warn",
        )
    finally:
        s.E2E_SECONDS.clear()
        s.E2E_SECONDS.update(original)
    total = sum(len(json.loads(complete[key])) for key in BINNED)
    expect(total <= 10, f"a complete run must stay at 10 stack legs or fewer: {total}")
    # A small PR packs into one leg; packing is deterministic.
    small = pr("tools/pwa/test.sh", "tools/tasks/test.sh")
    legs = json.loads(small.outputs()["e2e"])
    expect(
        len(legs) == 1 and set(legs[0]["shards"].split()) == {"pwa", "tasks"},
        f"two small leaves must share one leg: {legs}",
    )
    expect(
        small.outputs() == pr("tools/tasks/test.sh", "tools/pwa/test.sh").outputs(),
        "packing must not depend on path order",
    )
    expect(s.pack([], s.E2E_SECONDS, 4) == [], "nothing selected packs to no leg")
    # Rules must point at the suites that exist in the CI entry points.
    expect(
        set(s.INTEGRATION_SHARDS) <= case_labels(ROOT / "tools/ci/integration.sh"),
        "INTEGRATION_SHARDS contains a shard tools/ci/integration.sh does not run",
    )
    expect(
        set(s.E2E_SHARDS) <= case_labels(ROOT / "tools/ci/e2e.sh"),
        "E2E_SHARDS contains a shard tools/ci/e2e.sh does not run",
    )
    expect(
        set(s.EMDASH_GROUPS) <= case_labels(ROOT / "tools/ci/emdash.sh"),
        "EMDASH_GROUPS contains a group tools/ci/emdash.sh does not run",
    )
    known = s.everything()
    for rule in s.RULES:
        if rule.suites != s.ALL:
            unknown = set(rule.suites) - known
            expect(not unknown, f"rule {rule.reason!r} names unknown suites {unknown}")
        # A renamed directory must not silently stop selecting its suite.
        for pattern in rule.patterns:
            prefix = pattern.split("*", 1)[0].rstrip("/")
            if prefix and "/" in pattern and not pattern.startswith("**"):
                base = prefix if pattern.endswith("/**") else str(Path(prefix).parent)
                expect(
                    (ROOT / base).exists(),
                    f"rule {rule.reason!r}: {pattern} matches nothing",
                )
    # Glob semantics.
    expect(
        s.matches("a/b/c.md", ["**/*.md"]) and s.matches("c.md", ["**/*.md"]),
        "** spans depth",
    )
    expect(
        not s.matches("tools/ci2/x", ["tools/ci/**"]), "** must not leak into siblings"
    )
    expect(
        not s.matches("tests/e2e/sub/x.spec.mjs", ["tests/e2e/*.spec.mjs"]),
        "* is one segment",
    )

    if FAILURES:
        for failure in FAILURES:
            print(f"select-suites-test: ERROR: {failure}", file=sys.stderr)
        return 1
    print(
        "select-suites-test: OK: tiers, shared infra, docs-only, module-local and unknown paths"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
