#!/usr/bin/env python3
"""Prove the suite selection (fast, post-merge, full) against real paths."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
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


def post(*paths: str) -> s.Selection:
    """The post-merge run on main: what the paths select since the last green."""
    return s.select("push", list(paths))


def broad(selection: s.Selection, *owners: str, seed: bool = False) -> bool:
    """Post-merge, shared: non-E2E suites (E-042 seed-reset), smoke, leaves."""
    base = s.everything_but_e2e() - (set() if seed else {"integration:seed-reset"})
    smoke = set() if set(owners) >= set(s.E2E_SHARDS) else {s.SMOKE}
    return not selection.full and selection.suites == base | smoke | s.e2e(*owners)


def full(selection: s.Selection) -> bool:
    return bool(selection.full and selection.suites == s.everything())


BINNED = ("integration", "e2e", "emdash")


def flat(selection: s.Selection) -> dict[str, Any]:
    """Selector outputs; matrix bins flattened to their shard names."""
    raw = {
        k: json.loads(v)
        for k, v in selection.outputs().items()
        if k not in ("reason", "tier")
    }
    for key in BINNED:
        raw[key] = [shard for leg in raw[key] for shard in leg["shards"].split()]
    return raw


def outputs(*paths: str) -> dict[str, Any]:
    """Post-merge outputs: the mapping of the paths, before the tier split."""
    return flat(post(*paths))


def fast(*paths: str) -> dict[str, Any]:
    """Pull-request (fast tier) outputs."""
    return flat(pr(*paths))


def label_tier(labels: str) -> str:
    """The tier the command line gives a pull request with these labels."""
    with tempfile.TemporaryDirectory() as directory:
        paths = Path(directory) / "paths"
        paths.write_text("apps/web/src/app.tsx\n", encoding="utf-8")
        printed = io.StringIO()
        saved = {
            key: os.environ.pop(key, None)
            for key in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY")
        }
        try:
            with contextlib.redirect_stdout(printed):
                s.main(
                    [
                        "--event",
                        "pull_request",
                        "--paths-file",
                        str(paths),
                        "--labels",
                        labels,
                    ]
                )
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value
    return str(json.loads(printed.getvalue().splitlines()[-1])["tier"])


def stack_suites(result: dict[str, Any]) -> dict[str, Any]:
    """Only what starts a runner: matrix shards plus the flags."""
    return {k: v for k, v in result.items() if k in BINNED or v is True}


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
    ("tools/ci/build.sh", {}),
    ("specs/leonaid-poc/KNOWN-LIMITS.md", {}),
    ("apps/docs/src/content/docs/de/index.mdx", {}),
    (".github/workflows/docs.yml", {}),
    (".github/workflows/nightly-watchdog.yml", {}),
    (".github/workflows/release.yml", {}),
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
    ("tools/pwa/test.sh", {"e2e": ["pwa", "pwa-offline", "pwa-offline-webkit"]}),
    (
        "tests/e2e/pwa-offline-queue.spec.mjs",
        {"e2e": ["pwa-offline", "pwa-offline-webkit"]},
    ),
    ("tests/e2e/pwa-audit.spec.mjs", {"e2e": ["pwa"]}),
)


def case_labels(script: Path) -> set[str]:
    """Labels of the two-space-indented shell `case` arms in tools/ci/<name>.sh."""
    labels: set[str] = set()
    for line in script.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^  ([a-z0-9|-]+)\)$", line)
        if match:
            labels.update(match.group(1).split("|"))
    return labels


def fast_of(selection: s.Selection) -> bool:
    """A fast-tier selection: no browser, acceptance or unmapped stack suite."""
    return selection.tier == "fast" and not any(
        s.is_heavy(suite) for suite in selection.suites
    )


def main() -> int:
    # Schedules, dispatch and a push without a diff run everything.
    for event in ("push", "schedule", "workflow_dispatch"):
        selection = s.select(event, [])
        expect(full(selection), f"{event} without a diff must select everything")
    for event in ("schedule", "workflow_dispatch"):
        expect(full(s.select(event, ["README.md"])), f"{event} ignores paths")
    # No readable diff is never an excuse to skip.
    expect(full(pr()), "an empty PR diff must select everything")
    # Post-merge: unknown paths select every non-E2E suite plus smoke.
    for path in (
        "brand-new/thing.py",
        "tools/new_module/test.sh",
        "apps/web/src/app.tsx",
    ):
        expect(broad(post(path)), f"unmapped {path}: all non-E2E suites plus smoke")
        quick = pr(path)
        expect(
            fast_of(quick)
            and set(quick.integration_units()) <= {"api-contract"}
            and quick.deferred
            >= s.everything_but_e2e()
            - {"api", "pins", "integration:api-contract", "integration:seed-reset"},
            f"unmapped {path}: the PR runs the fast tier only, "
            f"the rest after the merge: {sorted(quick.suites)}",
        )
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
            broad(post(path), *owners, seed=s.matches(path, s.SEED_RESET_PATHS)),
            f"shared {path}: all non-E2E suites, smoke, mapped leaves {owners}",
        )
        expect(fast_of(pr(path)), f"shared {path}: fast tier only before the merge")
    # Documentation-only PRs run no stack suite at all.
    docs_paths = (
        "apps/docs/src/content/docs/en/user/how-to/plan-tasks.md",
        "apps/docs/product-contracts.json",
        "specs/modular-platform/README.md",
        "tools/delivery/README.md",
        "README.md",
    )
    for docs in (outputs(*docs_paths), fast(*docs_paths)):
        expect(
            docs["integration"] == []
            and docs["e2e"] == []
            and docs["emdash"] == []
            and not any(docs[flag] for flag in s.FLAGS),
            f"docs-only change selected stack suites: {docs}",
        )
    # Module-local changes stay local.
    tasks = outputs(
        "src/leonaid/modules/tasks/api.py", "tests/e2e/tasks-views.spec.mjs"
    )
    expect(tasks["e2e"] == ["tasks"], f"tasks module: {tasks}")
    expect(
        tasks["integration"] == ["schema", "api-contract"] and tasks["emdash"] == [],
        f"tasks module: its server contracts run in schema: {tasks}",
    )
    expect(tasks["api"] is True and tasks["surveys"] is False, f"tasks module: {tasks}")
    quick_tasks = fast(
        "src/leonaid/modules/tasks/api.py", "tests/e2e/tasks-views.spec.mjs"
    )
    expect(
        quick_tasks["e2e"] == [] and quick_tasks["api"] is True,
        f"tasks module, fast tier: API contract yes, E2E after the merge: {quick_tasks}",
    )
    delivery = outputs("tools/delivery/foundation.py")
    expect(
        delivery["integration"] == ["delivery"] and delivery["e2e"] == [],
        f"delivery: {delivery}",
    )
    expect(
        fast("tools/delivery/foundation.py")["integration"] == ["delivery"],
        "a specifically mapped short Integration shard runs before the merge",
    )
    # The delivery UI and its component tests select the invoices leaf, plus
    # the API contract its path filter (API_PATHS) always adds.
    for path in (
        "packages/features/src/delivery/tours.css",
        "apps/web/src/delivery-tours.test.tsx",
        "apps/web/src/driver-note.test.tsx",
        "apps/web/src/tour-map.test.tsx",
        "apps/web/src/tour-model.test.ts",
    ):
        ui = outputs(path)
        expect(
            ui["e2e"] == ["invoices"]
            and ui["integration"] == ["api-contract"]
            and ui["emdash"] == []
            and not post(path).full,
            f"delivery UI {path}: the invoices leaf only: {ui}",
        )
    # "Meine Tour" and the offline queue also select the offline journey.
    for path in (
        "packages/features/src/delivery/my-tour.tsx",
        "apps/web/src/my-tour.test.tsx",
    ):
        tour = outputs(path)
        expect(
            sorted(tour["e2e"]) == ["invoices", "pwa-offline"] and not post(path).full,
            f"Meine Tour {path}: invoices and pwa-offline: {tour}",
        )
    for path in (
        "packages/features/src/offline/tour-cache.ts",
        "packages/features/src/offline/queue.ts",
        "tests/e2e/pwa-offline-tour.spec.mjs",
    ):
        offline = outputs(path)
        expect(
            sorted(offline["e2e"]) == ["pwa-offline", "pwa-offline-webkit"]
            and not post(path).full,
            f"offline UI {path}: the offline leaves: {offline}",
        )
    # The PWA shell, service worker and offline page: the PWA leaves.
    for path in (
        "apps/pwa/src/app.tsx",
        "apps/pwa/public/sw.js",
        "apps/pwa/public/offline.js",
        "apps/pwa/public/offline.html",
    ):
        pwa = outputs(path)
        expect(
            sorted(pwa["e2e"]) == sorted(s.PWA) and not post(path).full,
            f"PWA app {path}: the PWA leaves: {pwa}",
        )
    flags = outputs("packages/features/src/feature-flags/openfeature-provider.tsx")
    expect(
        sorted(flags["e2e"]) == sorted(("invoices", "operations", *s.PWA)),
        f"flag provider: operations, invoices and the PWA leaves: {flags}",
    )
    public = outputs("apps/public/src/components/PublicOrder.astro")
    expect(
        sorted(public["e2e"])
        == ["identity", "membership", "public-catalog", "public-orders"]
        and public["emdash"] == []
        and not post("apps/public/src/components/PublicOrder.astro").full,
        f"public site: its leaves, no EmDash: {public}",
    )
    intro = outputs("apps/public/src/components/KrapfentaxiIntro.astro")
    expect(
        intro["e2e"] == ["public-orders"] and sorted(intro["emdash"]) == sorted(s.EMDASH_GROUPS),
        f"Krapfentaxi intro: public orders and the EmDash proofs: {intro}",
    )
    expect(
        outputs("apps/public/src/pages/surveys/[surveyId].astro")["surveys"] is True,
        "public survey page: the survey suites",
    )
    # The inbox rule still wins for its public component.
    expect(
        outputs("apps/public/src/components/PublicInbox.astro")["e2e"] == ["inbox"],
        "public inbox component: the inbox leaf",
    )
    campaign = outputs(
        "apps/campaign-site/emdash-editor-patch.mjs",
        "tools/emdash_spike/auth-patch-proof.mjs",
    )
    expect(
        sorted(campaign["emdash"]) == sorted(s.EMDASH_GROUPS),
        f"campaign site: {campaign}",
    )
    expect(
        campaign["e2e"] == []
        and campaign["integration"] == []
        and campaign["api"] is False,
        f"campaign site must not start Core suites: {campaign}",
    )
    expect(
        fast("apps/campaign-site/emdash-editor-patch.mjs")["emdash"] == [],
        "EmDash proofs run after the merge",
    )
    surveys = outputs(
        "packages/surveys/src/index.ts", "tests/e2e/surveys-editor.spec.mjs"
    )
    expect(surveys["surveys"] is True and surveys["e2e"] == [], f"surveys: {surveys}")
    expect(
        fast("packages/surveys/src/index.ts")["surveys"] is False,
        "survey shards run after the merge",
    )
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
    for view in (outputs, fast):
        expect(
            view("infra/security/vulnerability-allowlist.json")["pins"] is True,
            "pins filter",
        )
        expect(view("tools/openapi/generate.py")["api"] is True, "API filter")
        expect(
            view("tests/unit/test_x.py")["api"] is True, "API filter keeps tests/unit"
        )
        expect(view("tests/unit/test_x.py")["e2e"] == [], "unit tests run no stack")
    # The post-merge run on main ignores the base branch; no diff: complete.
    expect(
        broad(s.select("push", ["brand-new/thing.py"], "md/stage2c"))
        and s.select("push", [], "x").full
        and s.select("push", ["README.md"]).tier == "post-merge",
        "push diffs since the last green run",
    )
    # A pull request into another branch runs like one into main.
    expect(
        s.select("pull_request", ["tools/delivery/x.py"], "md/stage2c").suites
        == s.select("pull_request", ["tools/delivery/x.py"], "main").suites,
        "no stacked tier",
    )
    # Fast Integration legs: a selected unit is never dropped for the budget;
    # a long one gets a leg of its own.
    for shard in s.INTEGRATION_SECONDS:
        legs = s.fast_pack([shard], s.INTEGRATION_SECONDS)
        expect(legs == [[shard]], f"fast leg for {shard}")
    every = [*s.INTEGRATION_SHARDS, "contract"]
    legs = s.fast_pack(every, s.INTEGRATION_SECONDS)
    expect(
        all(
            len(leg) == 1
            or sum(s.INTEGRATION_SECONDS[x] for x in leg) <= s.FAST_LEG_SECONDS
            for leg in legs
        )
        and sorted(x for leg in legs for x in leg) == sorted(every),
        f"fast legs keep the budget and lose nothing: {legs}",
    )
    core = pr("tools/core/smoke.py")
    expect(
        core.integration_units() == ["seed-reset"]
        and "integration:seed-reset" not in core.deferred,
        f"a long shard still runs before the merge: {core.integration_bins()}",
    )
    # Every Integration unit selected (tools/ci/integration.sh): nothing is
    # dropped, and the fast legs stay within MAX_BINS (runner budget).
    wide = pr("tools/ci/integration.sh")
    wide_bins = wide.integration_bins()
    expect(
        len(wide_bins) <= s.MAX_BINS["integration"]
        and sorted(x for leg in wide_bins for x in leg)
        == sorted(wide.integration_units()),
        f"fast legs are capped and lose nothing: {wide_bins}",
    )
    # The API contract rides in an Integration leg whenever its filter matches.
    api = pr("tools/openapi/generate.py")
    expect(
        "api-contract" in api.integration_units(),
        f"the API filter runs the contract leg: {api.integration_bins()}",
    )
    # E-019: the authorization negative contract stays before the merge for
    # every change that reaches what it guards, in a leg of its own.
    for path in (
        "tools/policy/contract.py",
        "tools/sessions/test.sh",
        "src/leonaid/domain/sessions.py",
        "src/leonaid/entrypoints/fastapi/security.py",
        "src/leonaid/modules/tasks/api.py",
        "migrations/versions/0052_x.py",
        "alembic.ini",
        "tests/fixtures/golden/v1/dataset.json",
        "tools/twenty/provision.py",
        "tools/seed/seed_core.py",
        "infra/compose/compose.yml",
        "infra/proxy/Caddyfile",
        "tools/typst/render_golden.sh",
    ):
        guarded = pr(path)
        expect(
            guarded.integration_bins()[:1] == [["policy"]]
            and "integration:policy" not in guarded.deferred,
            f"{path}: Integration / policy must run before the merge, alone: "
            f"{guarded.integration_bins()}",
        )
    for path in (
        "apps/web/src/app.tsx",
        "tools/storage/test.sh",
        "README.md",
        ".github/workflows/ci.yml",
        "packages/features/src/tasks/x.tsx",
    ):
        expect(
            "integration:policy" not in pr(path).suites,
            f"{path} does not reach the authorization contract",
        )
    # rv-177 N1: the privacy rules (recipient normalization, inbox erasure)
    # select the privacy contract before the merge.
    for path in (
        "src/leonaid/domain/privacy.py",
        "src/leonaid/modules/inbox/privacy.py",
        "src/leonaid/application/legal_configuration.py",
    ):
        expect(
            ["privacy"] in pr(path).integration_bins(),
            f"{path}: Integration / privacy must run before the merge: "
            f"{pr(path).integration_bins()}",
        )
    combined = pr("src/leonaid/domain/sessions.py", "tools/delivery/foundation.py")
    expect(
        combined.integration_bins() == [["policy"], ["api-contract", "delivery"]],
        f"the required leg comes on top of the fast legs: {combined.integration_bins()}",
    )
    openapi = pr("tools/openapi/generate.py")
    expect(
        openapi.integration_units() == ["api-contract", "contract"]
        and json.loads(openapi.outputs()["contract"]) is True,
        "Contract runs before the merge when its inputs changed",
    )
    expect(
        json.loads(pr("tools/ci/contract.sh").outputs()["contract"]) is True,
        "the Contract entry point runs Contract",
    )

    # E2E policy (2026-11-07): import graph, smoke leg, label, schedules.
    graph_cases = {
        "src/leonaid/application/invoices.py": {"invoices", "invoice-flows"},
        "src/leonaid/modules/tasks/api.py": {"tasks"},
        "src/leonaid/domain/sessions.py": {"membership"},
        "src/leonaid/application/public_orders.py": {"public-orders"},
    }
    for path, must in graph_cases.items():
        mapped = s.e2e_owners(path, ROOT)
        expect(mapped is not None and must <= mapped, f"{path}: owners {mapped}")
    expect(s.e2e_owners("apps/web/src/app.tsx", ROOT) is None, "non-Python path")
    errors = s.e2e_owners("src/leonaid/domain/errors.py", ROOT) or set()
    expect(len(errors) >= 10, f"a shared domain module fans out: {errors}")
    # Fail safe: a module without any owner runs every leaf, unless it is a
    # reviewed E2E_NEUTRAL entry.
    expect(
        s.e2e_owners("src/leonaid/domain/brand_new_thing.py", ROOT)
        == set(s.E2E_SHARDS),
        "an unmapped new module runs every E2E leaf",
    )
    for path, must in (
        ("src/leonaid/entrypoints/fastapi/routes.py", set(s.E2E_SHARDS)),
        ("src/leonaid/entrypoints/fastapi/schemas.py", set(s.E2E_SHARDS)),
        ("src/leonaid/bootstrap/api.py", set(s.E2E_SHARDS)),
        ("src/leonaid/configuration.py", set(s.E2E_SHARDS)),
        ("src/leonaid/adapters/mail/smtp.py", {"membership", "invoice-flows"}),
        ("src/leonaid/adapters/twenty/gateway.py", set(s.PWA)),
        ("src/leonaid/adapters/typst/invoice_renderer.py", {"invoices"}),
        ("src/leonaid/entrypoints/worker/outbox.py", {"membership", "pwa"}),
    ):
        mapped = s.e2e_owners(path, ROOT) or set()
        expect(
            must <= mapped, f"{path}: {sorted(mapped)} lacks {sorted(must - mapped)}"
        )
    # Every module under a specific ALL_E2E prefix selects every leaf, even
    # when owner modules import it (platform.http, base_paths, ...).
    for module_path in sorted((ROOT / "src/leonaid").rglob("*.py")):
        relative = module_path.relative_to(ROOT).as_posix()
        module = s.module_of(relative) or ""
        prefix = next(
            (p for p, _ in s.MODULE_OWNERS if s.matches_module(module, p)), None
        )
        mapped_all = prefix is not None and dict(s.MODULE_OWNERS)[prefix] == s.ALL_E2E
        neutral = any(s.matches_module(module, n) for n in s.E2E_NEUTRAL)
        if prefix and prefix not in s.CATCH_ALL_PREFIXES and mapped_all and not neutral:
            expect(
                s.e2e_owners(relative, ROOT) == set(s.E2E_SHARDS),
                f"{relative} ({prefix}) must select every E2E leaf",
            )
    expect(
        s.e2e_owners("src/leonaid/platform/http.py", ROOT) == set(s.E2E_SHARDS),
        "platform.http selects every leaf",
    )
    expect(
        all(len(reason) >= 20 for reason in s.E2E_NEUTRAL.values())
        and len(s.E2E_NEUTRAL) <= 10,
        "E2E_NEUTRAL stays short and every entry has a reason",
    )
    # Every src/leonaid module that shared rules leave to the graph has
    # owners or a reviewed neutral entry: nothing falls to smoke silently.
    for module_path in sorted((ROOT / "src/leonaid").rglob("*.py")):
        relative = module_path.relative_to(ROOT).as_posix()
        if s.classify(relative)[0] != s.everything():
            continue
        mapped = s.e2e_owners(relative, ROOT)
        module = s.module_of(relative) or ""
        neutral = any(s.matches_module(module, n) for n in s.E2E_NEUTRAL)
        expect(
            bool(mapped) or neutral,
            f"{relative} maps to no E2E leaf and is not in E2E_NEUTRAL",
        )
    # A graph hit adds exactly its leaves after the merge; the smoke leg
    # runs alone.
    invoice_push = s.select(
        "push", ["src/leonaid/application/invoices.py"], "main", root=ROOT
    )
    legs = json.loads(invoice_push.outputs()["e2e"])
    expect(legs[-1]["shards"] == s.SMOKE, f"smoke leg last and alone: {legs}")
    expect(
        all(s.SMOKE not in leg["shards"].split() for leg in legs[:-1]),
        f"the smoke leg is never packed with leaves: {legs}",
    )
    invoice_pr = s.select(
        "pull_request", ["src/leonaid/application/invoices.py"], "main", root=ROOT
    )
    expect(
        json.loads(invoice_pr.outputs()["e2e"]) == []
        and {"e2e:invoices", s.SMOKE} <= invoice_pr.deferred,
        f"a pull request defers its E2E leaves: {sorted(invoice_pr.deferred)}",
    )
    # The full-ci label runs the complete suite before the
    # merge: every leaf, no smoke leg, every heavy suite.
    labelled = s.select("pull_request", ["apps/web/src/app.tsx"], "main", full_ci=True)
    labelled_legs = json.loads(labelled.outputs()["e2e"])
    expect(
        full(labelled)
        and labelled.tier == "full"
        and sorted(x for leg in labelled_legs for x in leg["shards"].split())
        == sorted(s.E2E_SHARDS),
        f"full-ci label: complete suite, no smoke: {labelled_legs}",
    )
    expect(
        full(s.select("pull_request", ["README.md"], "main", full_ci=True)),
        "full-ci runs the complete suite even for a docs-only change",
    )
    for labels, want_tier in (
        ("full-ci", "full"),
        ("x,full-ci", "full"),
        ("full-e2e", "fast"),
        ("x", "fast"),
    ):
        expect(
            label_tier(labels) == want_tier,
            f"--labels {labels!r} must give the {want_tier} tier",
        )
    # The nightly run (and dispatch) runs every leaf; it is the only schedule.
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
    # Docs-only changes still start no stack suite, not even smoke.
    for selection in (pr("README.md"), post("README.md")):
        expect(
            json.loads(selection.outputs()["e2e"]) == [],
            "docs-only change runs no smoke leg",
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
        free = set(leg["shards"].split()) <= s.TWENTY_FREE
        expect(
            leg["bootstrap"] == ("toolchains" if free else "seed"),
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
        s.leg_estimate("integration", ["seed-reset", "policy"], s.INTEGRATION_SECONDS)
        == s.LEG_SETUP_SECONDS
        + 2 * s.SHARD_SETUP_SECONDS["integration"]
        + s.INTEGRATION_SECONDS["seed-reset"]
        + s.INTEGRATION_SECONDS["policy"],
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
    # 6 Integration + 8 E2E (E-043) + 3 EmDash (krapfentaxi-orders in two
    # halves, E-024): with Golden's 2 and the 6 stack-free jobs 25 runners;
    # run 42569824316 ran 27 jobs at once without queueing.
    expect(total <= 17, f"a complete run must stay at 17 stack legs or fewer: {total}")
    # A small PR packs into one leg; packing is deterministic.
    small = post("tools/inbox/test.sh", "tools/tasks/test.sh")
    legs = json.loads(small.outputs()["e2e"])
    expect(
        len(legs) == 1 and set(legs[0]["shards"].split()) == {"inbox", "tasks"},
        f"two small leaves must share one leg: {legs}",
    )
    expect(
        small.outputs() == post("tools/tasks/test.sh", "tools/inbox/test.sh").outputs(),
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
