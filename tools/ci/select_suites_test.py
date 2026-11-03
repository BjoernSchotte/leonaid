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


def full(selection: s.Selection) -> bool:
    return bool(selection.full and selection.suites == s.everything())


def outputs(*paths: str) -> dict[str, Any]:
    return {k: json.loads(v) for k, v in pr(*paths).outputs().items() if k != "reason"}


def case_labels(script: Path) -> set[str]:
    """Labels of the shell `case` arms in tools/ci/<name>.sh."""
    labels: set[str] = set()
    for line in script.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^  ([a-z0-9|-]+)\)$", line)
        if match:
            labels.update(match.group(1).split("|"))
    return labels


def main() -> int:
    # Every event except pull_request runs everything.
    for event in ("merge_group", "push", "schedule", "workflow_dispatch"):
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
        expect(full(pr(path)), f"unmapped {path} must select everything")
    # Shared infrastructure selects everything.
    for path in (
        ".github/workflows/ci.yml",
        "tools/ci/select_suites.py",
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
        expect(full(pr(path)), f"shared {path} must select everything")
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
    # Matrix order is preserved (long jobs first).
    expect(
        json.loads(s.select("push", []).outputs()["integration"])
        == list(s.INTEGRATION_SHARDS),
        "full integration matrix must keep the declared order",
    )
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
