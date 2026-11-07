#!/usr/bin/env python3
"""Select the expensive CI suites a pull request has to run.

Two tiers:

* ``pull_request``: cheap gates always run (lint/types, unit, build,
  security, docs). Stack suites run only when their inputs changed.
* every other event (``merge_group``, ``push``, ``schedule``,
  ``workflow_dispatch``): everything. Nothing reaches ``main`` without the
  complete suite, because the merge queue runs it before the merge.

Each changed path is matched against ``RULES``; the first matching rule wins.
A path that no rule matches selects everything, so a new directory is safe by
default and only becomes cheaper once someone maps it here deliberately.
Shared infrastructure (Compose, locks, CI, test harness, migrations, platform,
dependency manifests, the ``leonaid`` CLI) is mapped to everything explicitly.

The script only uses the standard library: it runs in the workflow on the
plain runner Python and in ``./leonaid check`` inside the pinned image.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

# Matrix order is the request order: long jobs first.
INTEGRATION_SHARDS = (
    "compose",
    "seed-cold",
    "seed-reset",
    "core",
    "typst",
    "storage",
    "documents",
    "profiles",
    "crm-gateway",
    "crm-import",
    "twenty-install",
    "policy",
    "schema-outbox",
    "delivery",
)
E2E_SHARDS = (
    "acquisition-management",
    "public-catalog",
    "membership",
    "invoices",
    "commitments",
    "pwa",
    "action-templates",
    "action-admin",
    "public-orders",
    "identity",
    "matching",
    "tasks",
    "materials",
    "knowledge",
    "inbox",
    "leitsystem-ui",
    "operations",
    "invoice-flows",
)
EMDASH_GROUPS = ("krapfentaxi-orders", "krapfentaxi-migration", "static")
# Whole-workflow or whole-job suites.
FLAGS = ("contract", "golden", "surveys", "api", "pins")

ALL = "*"


def integration(*shards: str) -> frozenset[str]:
    return frozenset(f"integration:{shard}" for shard in shards)


def e2e(*shards: str) -> frozenset[str]:
    return frozenset(f"e2e:{shard}" for shard in shards)


EMDASH = frozenset({"emdash"})
NONE: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Rule:
    patterns: tuple[str, ...]
    suites: frozenset[str] | str
    reason: str


RULES: tuple[Rule, ...] = (
    # Fixture prose is test input (tools/golden/test.sh reads its README).
    Rule(("tests/fixtures/**",), ALL, "shared test fixtures"),
    # Prose never feeds a stack suite; docs.yml and the checks cover it.
    Rule(("**/*.md", "**/*.mdx"), NONE, "documentation"),
    # The EmDash CI entry point only drives the EmDash proof groups.
    Rule(("tools/ci/emdash.sh",), EMDASH, "EmDash CI entry point"),
    # Shared infrastructure: wins over every narrower rule below.
    Rule(
        (
            ".github/**",
            "tools/ci/**",
            "tools/testing/**",
            "tools/seed/**",
            "tools/twenty/**",
            "tools/typst/**",
            # network_override.py and infrastructure.sh serve every stack.
            "tools/surveys/**",
            "infra/compose/**",
            "infra/locks/**",
            "infra/proxy/**",
            "migrations/**",
            "alembic.ini",
            "src/leonaid/platform/**",
            "src/leonaid/bootstrap/**",
            "src/leonaid/adapters/postgres/**",
            "package.json",
            "bun.lock",
            "uv.lock",
            "pyproject.toml",
            ".tool-versions",
            "leonaid",
            "playwright.config.mjs",
            ".dockerignore",
            ".env.example",
            ".gitignore",
            "tests/e2e/*.config.mjs",
            "tests/e2e/csp-guard.mjs",
            "packages/testkit/**",
        ),
        ALL,
        "shared infrastructure",
    ),
    # Documentation and specifications: the Documentation workflow and the
    # always-on checks cover them; no stack suite reads them.
    Rule(
        ("specs/leonaid-poc/openapi-breaking-approvals.json",),
        frozenset({"api"}),
        "API approvals",
    ),
    Rule(
        ("specs/emdash-campaign-microsite-spike/**",), EMDASH, "EmDash route inventory"
    ),
    # Pilot plan, decisions and readiness documents feed the Contract job.
    Rule(("specs/leonaid-pilot/**",), frozenset({"contract"}), "pilot contracts"),
    Rule(
        (
            "apps/docs/**",
            "specs/**",
            "LICENSE",
            ".editorconfig",
            ".prettierrc.json",
            ".prettierignore",
            "tests/unit/**",
        ),
        NONE,
        "documentation or always-on gate",
    ),
    # EmDash campaign site.
    Rule(
        ("apps/campaign-site/**", "tools/emdash_spike/**", "infra/emdash-spike/**"),
        EMDASH,
        "EmDash campaign site",
    ),
    # Surveys module.
    Rule(
        (
            "src/leonaid/modules/surveys/**",
            "packages/surveys/**",
            "packages/features/src/surveys/**",
            "apps/surveys-demo/**",
            "tests/e2e/surveys-*.spec.mjs",
        ),
        frozenset({"surveys"}),
        "surveys module",
    ),
    # Tasks module.
    Rule(
        (
            "src/leonaid/modules/tasks/**",
            "packages/features/src/tasks/**",
            "tests/e2e/tasks-*.spec.mjs",
            "tests/e2e/modules-tasks.spec.mjs",
        ),
        e2e("tasks"),
        "tasks module",
    ),
    # tools/schema/test.sh also runs the tasks schema contract.
    Rule(
        ("tools/tasks/**",), e2e("tasks") | integration("schema-outbox"), "tasks proofs"
    ),
    # Materials module.
    Rule(
        (
            "src/leonaid/modules/materials/**",
            "packages/features/src/materials/**",
            "tests/e2e/modules-materials.spec.mjs",
        ),
        e2e("materials"),
        "materials module",
    ),
    # tools/schema/test.sh also runs the materials schema contracts.
    Rule(
        ("tools/materials/**",),
        e2e("materials") | integration("schema-outbox"),
        "materials proofs",
    ),
    # Knowledge module.
    Rule(
        (
            "src/leonaid/modules/knowledge/**",
            "packages/features/src/knowledge/**",
            "tests/e2e/modules-knowledge.spec.mjs",
            "tests/e2e/knowledge-editor.spec.mjs",
        ),
        e2e("knowledge"),
        "knowledge module",
    ),
    # tools/schema/test.sh also runs the knowledge schema contracts.
    Rule(
        ("tools/knowledge/**",),
        e2e("knowledge") | integration("schema-outbox"),
        "knowledge proofs",
    ),
    # Inbox module.
    Rule(
        (
            "src/leonaid/modules/inbox/**",
            "packages/features/src/inbox/**",
            "tests/e2e/modules-inbox.spec.mjs",
            "tests/e2e/public-inbox-retry.spec.mjs",
            "apps/public/src/components/PublicInbox.astro",
            "apps/public/src/lib/modules.ts",
        ),
        e2e("inbox"),
        "inbox module",
    ),
    # tools/schema/test.sh also runs the inbox schema contracts.
    Rule(
        ("tools/inbox/**",),
        e2e("inbox") | integration("schema-outbox"),
        "inbox proofs",
    ),
    # The shared axe scan serves every browser suite, the survey specs and the
    # EmDash order proof, so it selects everything on purpose.
    Rule(("tests/e2e/axe.mjs",), ALL, "shared axe scan"),
    # Shared list helpers of the module specs.
    Rule(("tests/e2e/task-list.mjs",), e2e("tasks"), "task list helper"),
    Rule(
        ("tests/e2e/material-list.mjs",),
        e2e("materials", "inbox", "knowledge"),
        "material list helper",
    ),
    Rule(("tests/e2e/delivery-board.spec.mjs",), e2e("invoices"), "delivery board"),
    # Leitsystem shell proofs (tools/ci/e2e.sh leitsystem-ui).
    Rule(
        (
            "tools/ui_system/**",
            "tools/ux_acceptance/**",
            "tools/dashboard/**",
            "tests/e2e/ui-system.spec.mjs",
            "tests/e2e/ui-system.spec.mjs-snapshots/**",
            "tests/e2e/axe-helper.spec.mjs",
            "tests/e2e/ux-acceptance.spec.mjs",
            "tests/e2e/command-palette.spec.mjs",
            "tests/e2e/command-palette-faults.spec.mjs",
            "tests/e2e/dashboard.spec.mjs",
        ),
        e2e("leitsystem-ui"),
        "Leitsystem UI proofs",
    ),
    Rule(
        (
            "tools/operations/**",
            "tools/feature_flags/**",
            "tools/privacy/**",
            "tests/e2e/operations.spec.mjs",
            "tests/e2e/feature-flags.spec.mjs",
            "tests/e2e/privacy.spec.mjs",
        ),
        e2e("operations"),
        "operations proofs",
    ),
    Rule(
        (
            "tools/invoice_delivery/**",
            "tools/invoice_settlements/**",
            "tests/e2e/invoice-delivery.spec.mjs",
            "tests/e2e/invoice-settlements.spec.mjs",
            "tests/e2e/invoices-keyboard.spec.mjs",
        ),
        e2e("invoice-flows"),
        "invoice flow proofs",
    ),
    # Integration shards with their own proof directories.
    Rule(("tools/delivery/**",), integration("delivery"), "delivery proofs"),
    Rule(("tools/compose/**",), integration("compose", "profiles"), "Compose proofs"),
    Rule(("tools/core/**",), integration("core"), "Core proofs"),
    Rule(
        (
            "tools/schema/**",
            "tools/outbox/**",
            "tests/integration/test_order_cancellation_api.py",
        ),
        integration("schema-outbox"),
        "schema/outbox proofs",
    ),
    Rule(("tools/storage/**",), integration("storage"), "storage proofs"),
    Rule(
        ("tools/documents/**", "tests/e2e/documents.spec.mjs"),
        integration("documents"),
        "document proofs",
    ),
    Rule(("tools/policy/**",), integration("policy"), "policy proofs"),
    # E2E leaves with their own proof directories and specs.
    Rule(
        ("tools/invoices/**", "tests/e2e/invoices.spec.mjs"),
        e2e("invoices"),
        "invoice proofs",
    ),
    Rule(
        (
            "tools/commitments/**",
            "tests/e2e/commitments.spec.mjs",
            "tests/e2e/order-cancellation.spec.mjs",
        ),
        e2e("commitments"),
        "commitment proofs",
    ),
    Rule(
        ("tools/matching/**", "tests/e2e/matching.spec.mjs"),
        e2e("matching", "acquisition-management"),
        "matching proofs",
    ),
    Rule(("tools/pwa/**", "tests/e2e/pwa*.spec.mjs"), e2e("pwa"), "PWA proofs"),
    Rule(
        (
            "tests/e2e/identity.spec.mjs",
            "tests/e2e/members-keyboard.spec.mjs",
            "tests/e2e/member-list.mjs",
            "tests/e2e/y-role-management.spec.mjs",
            "tests/e2e/z-account-status.spec.mjs",
        ),
        e2e("identity"),
        "identity specs",
    ),
    # EmDash proofs import tools/identity and tools/public_orders helpers.
    Rule(("tools/identity/**",), e2e("identity") | EMDASH, "identity proofs"),
    Rule(
        ("tools/public_orders/**",),
        e2e("public-orders", "public-catalog") | integration("delivery") | EMDASH,
        "public order proofs",
    ),
    Rule(
        ("tests/e2e/public-orders.spec.mjs",), e2e("public-orders"), "public order spec"
    ),
    Rule(
        (
            "tools/action_admin/**",
            "tests/e2e/action-admin.spec.mjs",
            "tests/e2e/delivery-windows.spec.mjs",
        ),
        e2e("action-admin"),
        "action admin proofs",
    ),
    Rule(
        (
            "tools/invitations/**",
            "tools/sessions/**",
            "tests/e2e/invitations.spec.mjs",
            "tests/e2e/sessions.spec.mjs",
            "tests/e2e/member-list.mjs",
        ),
        e2e("membership"),
        "membership proofs",
    ),
    Rule(
        ("tools/actions/**", "tools/templates/**", "tests/e2e/actions.spec.mjs"),
        e2e("action-templates"),
        "action template proofs",
    ),
    Rule(
        (
            "tools/assignments/**",
            "tools/activities/**",
            "tests/e2e/activities.spec.mjs",
        ),
        e2e("acquisition-management"),
        "acquisition management proofs",
    ),
    Rule(
        (
            "tools/public_actions/**",
            "tools/activity_feed/**",
            "tests/e2e/public-actions.spec.mjs",
            "tests/e2e/public-audit.spec.mjs",
            "tests/e2e/activity-feed.spec.mjs",
            "tools/multi_host/**",
            "tests/e2e/multi-host.spec.mjs",
        ),
        e2e("public-catalog"),
        "public catalog proofs",
    ),
    Rule(
        (
            "tools/golden_journey/**",
            "tools/golden/**",
            "tests/e2e/golden-journey.spec.mjs",
        ),
        frozenset({"golden"}),
        "Golden Journey",
    ),
    Rule(
        (
            "tools/pilot_contract/**",
            "tools/pilot_decisions/**",
            "tools/pilot_readiness/**",
            "tools/mail_domain/**",
            "tools/testkit/**",
        ),
        frozenset({"contract"}),
        "Contract job inputs",
    ),
    Rule(
        ("tools/openapi/**", "tests/contract/**"),
        frozenset({"api", "contract"}),
        "API contract",
    ),
    Rule(
        (
            "tools/pins/**",
            "tools/sbom/**",
            "tools/security/**",
            "infra/security/**",
            "renovate.json",
        ),
        frozenset({"pins"}),
        "dependency policy (Security always runs)",
    ),
    # Frontend feature folders.
    Rule(
        ("packages/features/src/commitments/**",),
        e2e("commitments", "invoices") | integration("delivery") | {"golden"},
        "commitment UI",
    ),
    Rule(
        ("packages/features/src/invoices/**",),
        e2e("invoices") | {"golden"},
        "invoice UI",
    ),
    Rule(
        ("packages/features/src/acquisition/**",),
        e2e("acquisition-management", "matching") | {"golden"},
        "acquisition UI",
    ),
    Rule(
        ("packages/features/src/action-admin/**",),
        e2e("action-admin"),
        "action admin UI",
    ),
    Rule(
        ("packages/features/src/activity-feed/**",),
        e2e("public-catalog"),
        "activity feed UI",
    ),
)

# Historical path filters of the two formerly filtered workflows. The
# selector keeps them, so those workflows run as often as before while their
# checks now always report.
API_PATHS = (
    ".github/workflows/api-contract.yml",
    "apps/**",
    "packages/api-client/**",
    "packages/features/**",
    "src/leonaid/**",
    "tests/contract/**",
    "tests/unit/**",
    "tools/openapi/**",
    "infra/compose/**",
    "leonaid",
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "bun.lock",
    "specs/leonaid-poc/openapi-breaking-approvals.json",
)
# Documentation-only changes no longer start the real API stack.
API_EXCLUDED = ("apps/docs/**", "apps/campaign-site/**", "**/*.md", "**/*.mdx")
PINS_PATHS = (
    ".github/workflows/pins.yml",
    ".tool-versions",
    "bun.lock",
    "infra/locks/**",
    "infra/security/**",
    "package.json",
    "pyproject.toml",
    "renovate.json",
    "tools/pins/**",
    "tools/security/vuln_policy*.py",
    "tools/sbom/**",
    "uv.lock",
)


@cache
def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Translate a path glob: ``*`` stays in one segment, ``**`` crosses them."""
    out = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(out) + r"\Z")


def matches(path: str, patterns: Iterable[str]) -> bool:
    return any(compile_pattern(pattern).match(path) for pattern in patterns)


def everything() -> frozenset[str]:
    return frozenset(
        integration(*INTEGRATION_SHARDS) | e2e(*E2E_SHARDS) | EMDASH | frozenset(FLAGS)
    )


def classify(path: str) -> tuple[frozenset[str], str]:
    for rule in RULES:
        if matches(path, rule.patterns):
            if rule.suites == ALL:
                return everything(), rule.reason
            return frozenset(rule.suites), rule.reason
    return everything(), "unmapped path"


@dataclass(frozen=True)
class Selection:
    full: bool
    reason: str
    suites: frozenset[str]
    explanation: tuple[tuple[str, str, tuple[str, ...]], ...] = ()

    def outputs(self) -> dict[str, str]:
        def listed(prefix: str, names: Sequence[str]) -> str:
            return json.dumps([n for n in names if f"{prefix}:{n}" in self.suites])

        result = {
            "full": json.dumps(self.full),
            "reason": self.reason,
            "integration": listed("integration", INTEGRATION_SHARDS),
            "e2e": listed("e2e", E2E_SHARDS),
            "emdash": json.dumps(
                list(EMDASH_GROUPS) if "emdash" in self.suites else []
            ),
        }
        for flag in FLAGS:
            result[flag] = json.dumps(flag in self.suites)
        return result


def select(event: str, paths: Sequence[str]) -> Selection:
    if event != "pull_request":
        return Selection(True, f"{event}: complete suite", everything())
    changed = sorted({p.strip() for p in paths if p.strip()})
    if not changed:
        return Selection(
            True, "pull_request without a readable diff: complete suite", everything()
        )
    suites: set[str] = set()
    explanation = []
    for path in changed:
        selected, reason = classify(path)
        if matches(path, API_PATHS) and not matches(path, API_EXCLUDED):
            selected = selected | {"api"}
        if matches(path, PINS_PATHS):
            selected = selected | {"pins"}
        suites |= selected
        explanation.append((path, reason, tuple(sorted(selected))))
    full = frozenset(suites) >= everything()
    reason = (
        "pull_request: complete suite" if full else "pull_request: changed inputs only"
    )
    return Selection(full, reason, frozenset(suites), tuple(explanation))


def changed_paths(base: str, head: str) -> list[str]:
    # --no-renames reports both sides of a rename: a moved proof still
    # selects the suite that owned its old location.
    output = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", base, head],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return output.splitlines()


def summary(selection: Selection) -> str:
    outputs = selection.outputs()
    lines = [
        "### Suite selection",
        "",
        f"**{selection.reason}**",
        "",
        "| Suite | Selected |",
        "|---|---|",
    ]
    for key in ("integration", "e2e", "emdash", *FLAGS):
        lines.append(f"| {key} | `{outputs[key]}` |")
    if selection.explanation and not selection.full:
        lines += ["", "| Changed path | Rule | Suites |", "|---|---|---|"]
        for path, reason, suites in selection.explanation[:200]:
            lines.append(f"| `{path}` | {reason} | {', '.join(suites) or '—'} |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", required=True)
    parser.add_argument("--base", help="git base revision for pull_request")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument(
        "--paths-file", help="newline-separated changed paths instead of git diff"
    )
    parser.add_argument("--explain", action="store_true", help="print per-path rules")
    args = parser.parse_args(argv)

    paths: list[str] = []
    if args.event == "pull_request":
        if args.paths_file:
            paths = Path(args.paths_file).read_text(encoding="utf-8").splitlines()
        elif args.base:
            try:
                paths = changed_paths(args.base, args.head)
            except subprocess.CalledProcessError as error:
                print(
                    f"select-suites: WARNING: git diff failed: {error.stderr}",
                    file=sys.stderr,
                )
                paths = []
    selection = select(args.event, paths)
    outputs = selection.outputs()

    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            for key, value in outputs.items():
                handle.write(f"{key}={value}\n")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary(selection))
    if args.explain:
        for path, reason, suites in selection.explanation:
            print(f"{path}\t{reason}\t{','.join(suites) or '-'}")
    print(json.dumps(outputs, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
