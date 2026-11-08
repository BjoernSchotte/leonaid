#!/usr/bin/env python3
"""Select the expensive CI suites a run has to execute.

Two tiers (decision E-018; there is no merge queue: GitHub offers none for a
personal-account repository):

* ``pull_request`` into main, the **fast tier** (the required gates, about
  five minutes): the always-on jobs (lint/types, unit, build, security,
  vulnerability gate, docs) plus the API contract and pins workflows when
  their path filters match, plus the Integration shards and the Contract
  job that a *specific* rule maps, packed into legs of ``FAST_LEG_SECONDS``
  (a longer unit gets a leg of its own; nothing selected is dropped). E2E leaves, the smoke leg, EmDash proofs, the
  Golden Journey and the survey shards never run here (``deferred``).
* ``pull_request`` with the ``full-ci`` label: the complete suite, every
  E2E leaf included, before the merge (migrations, security, large rewrites).
* ``push`` to main, the **post-merge tier**: the suites the changed paths
  select since the last green run on main (``--base``), as the pull request
  tier selected them before E-018: stack suites by their inputs, E2E leaves
  by module paths, specs and the reverse import graph (``e2e_owners``), and
  for shared infrastructure and unmapped paths every non-E2E suite plus the
  short ``smoke`` leg (login, one list view, one public order). Without a
  readable diff: the complete suite.
* nightly ``schedule``, ``workflow_dispatch``, ``push`` without a diff
  (probe branch): everything, including every E2E leaf.

Each changed path is matched against ``RULES``; the first matching rule wins.
A path that no rule matches selects every non-E2E suite, so a new directory
is safe by default and only becomes cheaper once someone maps it here
deliberately. Shared infrastructure (Compose, locks, CI, test harness,
migrations, platform, dependency manifests, the ``leonaid`` CLI) is mapped
the same way explicitly.

The script only uses the standard library: it runs in the workflow on the
plain runner Python and in ``./leonaid check`` inside the pinned image.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Matrix order is the request order: long jobs first.
INTEGRATION_SHARDS = (
    "compose",
    "seed-reset",
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
    # The live OpenAPI contract on the prepared fixture (tools/openapi/test.sh).
    "api-contract",
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
# Short browser smoke leg (tools/ci/e2e.sh smoke): real login, one list view,
# one public order. Runs alone in its leg.
SMOKE = "smoke"
EMDASH_GROUPS = (
    "krapfentaxi-orders",
    "krapfentaxi-deadlines",
    "campaign-edge",
    "static",
)
# Whole-workflow or whole-job suites.
FLAGS = ("contract", "golden", "surveys", "api", "pins")

# Fewer, fatter jobs. A runner job costs about two minutes before its first
# test (checkout, build-layer import, bootstrap, fixture, image pulls), so the
# selected shards are bin-packed into at most MAX_BINS jobs per kind of about
# TARGET_SECONDS of test time each. Every shard still runs exactly once, each
# on its own fresh stack (tools/ci/integration.sh, e2e.sh). Seconds are the
# measured test-step durations of PR run 42360553738 (2026-11-07); refresh
# them from `gh run view <id> --json jobs` when a shard grows a lot.
INTEGRATION_SECONDS = {
    # Run 42508593075: compose 296 s (now with the Core smoke), seed-reset
    # 273 s (now with the idempotent second seed of the former seed-cold).
    "compose": 300,
    "seed-reset": 295,
    "typst": 119,
    "storage": 142,
    "documents": 149,
    "profiles": 127,
    "crm-gateway": 129,
    "crm-import": 100,
    "twenty-install": 133,
    # On the prepared fixture: about 35 s import, 25 s contract.
    "policy": 75,
    "schema-outbox": 199,
    "delivery": 30,
    # Local run 171 s incl. fixture restore: generation, typecheck and the
    # live contract, without the former job's Twenty pull and boot.
    "api-contract": 120,
    # The Contract job (tools/ci/contract.sh) rides in an Integration bin.
    "contract": 178,
}
E2E_SECONDS = {
    "acquisition-management": 156,
    # 183 s measured plus an estimate for the own-stack multi-host proof (#97).
    "public-catalog": 300,
    "membership": 160,
    "invoices": 120,
    "commitments": 175,
    "pwa": 180,
    "action-templates": 123,
    "action-admin": 155,
    "public-orders": 152,
    "identity": 129,
    "matching": 103,
    "tasks": 162,
    "materials": 112,
    "knowledge": 127,
    "inbox": 99,
    "leitsystem-ui": 278,
    "operations": 294,
    "invoice-flows": 188,
    # Estimate: three single tests on two prepared stacks.
    SMOKE: 240,
}
# EmDash bins are fixed: the order proof alone is the longest job of the run.
EMDASH_BINS = (
    ("krapfentaxi-orders",),
    ("krapfentaxi-deadlines",),
    ("campaign-edge", "static"),
)
EMDASH_SECONDS = {
    # Measured on PR #145 run 42511933095: commerce half 458 s, deadline
    # half 413 s, redirect-aliases 147 s; campaign-hosts 160 s plus its
    # admin-only round on the same stack (about 60 s, estimate).
    # Chromium-only orders and deadlines (E-026): estimates −64 s and −100 s.
    "krapfentaxi-orders": 395,
    "krapfentaxi-deadlines": 315,
    "campaign-edge": 370,
    "static": 107,
}
TARGET_SECONDS = 600
# ci.yml timeout-minutes of each leg kind (workflow_contract.py keeps them
# equal). A leg's estimate is its shards' seconds plus LEG_SETUP_SECONDS; the
# selector warns at LOAD_WARNING of the timeout, before a growing shard table
# turns into timeouts.
JOB_TIMEOUT_MINUTES = {"integration": 45, "e2e": 90, "emdash": 60}
LEG_SETUP_SECONDS = 150
# Every Integration shard and EmDash group boots its own stack; E2E leaves of
# one fixture kind share one (tools/ci/e2e.sh).
SHARD_SETUP_SECONDS = {"integration": 90, "e2e": 0, "emdash": 90}
LOAD_WARNING = 0.75
MAX_BINS = {"integration": 4, "e2e": 4}
# Integration shards that start Twenty: its image (about 40 s of pulls in
# the policy leg of run 42504505501) is prefetched beside the layer import.
SEED_BOOTSTRAP = frozenset({"compose", "seed-reset", "twenty-install", "policy"})

# Fast tier (pull requests): Integration shards and Contract that a specific
# rule selects run before the merge, packed into legs of FAST_LEG_SECONDS of
# INTEGRATION_SECONDS (a leg also pays about two minutes of preparation);
# a longer unit gets a leg of its own. Browser and acceptance suites run
# after the merge on main (post-merge tier).
FAST_LEG_SECONDS = 180
# Security proofs that never move after the merge (decision E-019): a pull
# request into main runs each, in a leg of its own outside the fast budget,
# whenever a changed path matches its patterns, also for shared and unmapped
# paths. Integration / policy is the authorization negative contract
# (sessions and foreign-action access against real PostgreSQL and Twenty),
# including the inputs it reads: the Golden fixtures, the seed and Twenty
# provisioning, the Compose stack and proxy it starts, and the Golden PDF
# renderer its seed calls.
FAST_REQUIRED: dict[str, tuple[str, ...]] = {
    "policy": (
        "src/leonaid/**",
        "migrations/**",
        "alembic.ini",
        "tools/policy/**",
        "tools/sessions/**",
        "tests/fixtures/golden/**",
        "tools/twenty/**",
        "tools/seed/**",
        "infra/compose/**",
        "infra/proxy/**",
        "tools/typst/render_golden.sh",
    ),
}
# Never in the fast tier: browser suites and multi-minute acceptance runs.
HEAVY_FLAGS = frozenset({"golden", "surveys"})

ALL = "*"
MAIN_BRANCH = "main"
# ci.yml's only schedule: the nightly run executes every E2E leaf.
NIGHTLY_SCHEDULE = "7 3 * * *"
# The lead sets it on risky pull requests: the complete suite before merge.
# The former full-e2e label is gone: only adding full-ci starts a run.
FULL_CI_LABEL = "full-ci"


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
    # CI entry points drive only their own suites.
    Rule(("tools/ci/emdash.sh",), EMDASH, "EmDash CI entry point"),
    Rule(
        ("tools/ci/e2e.sh",),
        e2e(*E2E_SHARDS),
        "E2E CI entry point",
    ),
    Rule(
        ("tools/ci/integration.sh",),
        integration(*INTEGRATION_SHARDS) | {"contract"},
        "Integration CI entry point (also runs Contract)",
    ),
    Rule(("tools/ci/contract.sh",), frozenset({"contract"}), "Contract CI entry point"),
    # Gates of always-running jobs: Lint and types / Unit, Build, Security and
    # the CI gate itself run on every event, so their scripts and checkers
    # select no stack suite. tools/ci/lint-types.sh runs the *_test.py files.
    Rule(
        (
            "tools/ci/*_test.py",
            "tools/ci/axe_helper.py",
            "tools/ci/build.sh",
            "tools/ci/conflict_markers.py",
            "tools/ci/core_oneoff_user.py",
            "tools/ci/gate.py",
            "tools/ci/legacy_ui.py",
            "tools/ci/lint-types.sh",
            "tools/ci/no_test_doubles.py",
            "tools/ci/reviewed_network_faults.json",
            "tools/ci/security.sh",
            "tools/ci/unit.sh",
            "tools/ci/workflow_contract.py",
        ),
        NONE,
        "always-on CI gate",
    ),
    # Workflows that run no ci.yml suite. Each gated workflow selects itself.
    Rule(
        (
            ".github/workflows/docs.yml",
            ".github/workflows/docs-watchdog.yml",
            ".github/workflows/nightly-watchdog.yml",
            ".github/workflows/pin-drift.yml",
            ".github/workflows/release.yml",
        ),
        NONE,
        "workflow without stack suites",
    ),
    Rule((".github/workflows/surveys.yml",), frozenset({"surveys"}), "Survey workflow"),
    Rule((".github/workflows/pins.yml",), frozenset({"pins"}), "pins workflow"),
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
    Rule(("tools/core/**",), integration("compose"), "Core smoke (in compose)"),
    Rule(
        (
            "tools/schema/**",
            "tools/outbox/**",
            "tests/integration/test_order_cancellation_api.py",
            "tests/integration/test_offline_capture_api.py",
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


def everything_but_e2e() -> frozenset[str]:
    return everything() - e2e(*E2E_SHARDS)


# E2E leaves that own a Python module, by module stem. The stem matches in
# leonaid.application, leonaid.domain, leonaid.adapters.postgres and
# leonaid.modules.<stem>.*. A changed module selects the owners of every
# module that imports it, directly or transitively (``e2e_owners``).
E2E_OWNERS: dict[str, tuple[str, ...]] = {
    "tasks": ("tasks",),
    "materials": ("materials",),
    "inbox": ("inbox",),
    "knowledge": ("knowledge",),
    "acquisition": ("acquisition-management", "matching"),
    "sponsor_matching": ("matching",),
    "crm_matching": ("matching",),
    "activities": ("acquisition-management",),
    "assignments": ("acquisition-management",),
    "activity_feed": ("public-catalog",),
    "activity_projection": ("public-catalog",),
    "campaign_aliases": ("public-catalog",),
    "campaign_renderer": ("public-catalog",),
    "action_progress": ("action-templates", "action-admin"),
    "actions": ("action-templates", "action-admin", "public-catalog"),
    "action_templates": ("action-templates",),
    "commitments": ("commitments",),
    "order_cancellation": ("commitments",),
    "delivery": ("action-admin", "invoices"),
    "delivery_board": ("invoices",),
    "delivery_completion": ("action-admin", "invoices"),
    "invoices": ("invoices", "invoice-flows"),
    "invoice_documents": ("invoices",),
    "invoice_deliveries": ("invoice-flows",),
    "invoice_settlements": ("invoice-flows",),
    "invoice_payments": ("invoice-flows",),
    "invoice_payment_state": ("invoice-flows",),
    "identity": ("identity", "membership"),
    "sessions": ("membership",),
    "email_changes": ("membership",),
    "invitations": ("membership",),
    "policies": ("identity",),
    "feature_flags": ("operations",),
    "privacy": ("operations",),
    "operations": ("operations",),
    "legal_configuration": ("operations",),
    "dashboard": ("leitsystem-ui",),
    "search": ("leitsystem-ui",),
    "public_orders": ("public-orders",),
}
# Leaves that send mail, sync the CRM or deliver invoices through the outbox.
_MESSAGING = (
    "membership",
    "invoice-flows",
    "public-orders",
    "matching",
    "acquisition-management",
)
ALL_E2E = "*"
# Modules the reverse import graph cannot reach: LeonAid wires adapters and
# entry points by dependency injection (bootstrap/, entrypoints/), so the
# import edges point from them to the application, never back. Mapped by
# module prefix, checked in order; the first match wins. ALL_E2E: the
# module serves every leaf (HTTP surface, wiring, platform).
MODULE_OWNERS: tuple[tuple[str, tuple[str, ...] | str], ...] = (
    ("leonaid.adapters.mail", ("membership", "invoice-flows", "public-orders")),
    (
        "leonaid.adapters.twenty",
        ("matching", "acquisition-management", "public-orders"),
    ),
    ("leonaid.adapters.typst", ("invoices", "invoice-flows")),
    ("leonaid.adapters.storage", ("materials", "knowledge", "inbox", "invoices")),
    ("leonaid.adapters.feature_flags", ("operations",)),
    ("leonaid.adapters.operations", ("operations",)),
    ("leonaid.adapters.postgres.outbox", _MESSAGING),
    ("leonaid.entrypoints.worker.outbox", _MESSAGING),
    ("leonaid.entrypoints.worker.retention", ("operations",)),
    ("leonaid.entrypoints.fastapi.order_proxy", ("public-orders", "public-catalog")),
    ("leonaid.entrypoints.fastapi.maintenance", ("operations",)),
    # The HTTP surface (routes, schemas, security, app), the worker
    # process, the wiring, configuration and the platform serve every leaf.
    ("leonaid.entrypoints.fastapi", ALL_E2E),
    ("leonaid.entrypoints.worker", ALL_E2E),
    ("leonaid.entrypoints", ALL_E2E),
    ("leonaid.bootstrap", ALL_E2E),
    ("leonaid.platform", ALL_E2E),
    ("leonaid.configuration", ALL_E2E),
    ("leonaid.adapters", ALL_E2E),
    ("leonaid.application.platform", ALL_E2E),
    ("leonaid.domain.platform", ALL_E2E),
    ("leonaid.domain.identifiers", ALL_E2E),
    ("leonaid", ALL_E2E),
)
# Fallback prefixes of MODULE_OWNERS; every other prefix is specific and
# unioned with the stem owners of the module's importers.
CATCH_ALL_PREFIXES = frozenset({"leonaid", "leonaid.adapters"})
# Reviewed modules that no browser leaf exercises. Keep this short; every
# entry needs a reason. Anything else without an owner runs every leaf.
E2E_NEUTRAL: dict[str, str] = {
    "leonaid.entrypoints.monitoring": "Prometheus exporter and log sink; "
    "covered by the Integration and Compose proofs, no browser path",
    "leonaid.entrypoints.fastapi.prometheus": "metrics endpoint, no browser path",
    "leonaid.entrypoints.crm_match_keys": "operator CLI (pilot repair units), "
    "covered by Integration / crm-gateway",
    "leonaid.entrypoints.material_cleanup": "operator CLI, covered by the "
    "materials schema contracts in Integration / schema-outbox",
    "leonaid.application.documents": "document proofs run in Integration / "
    "documents, including their browser coverage",
    "leonaid.adapters.postgres.documents": "document proofs run in Integration / "
    "documents, including their browser coverage",
}

OWNER_PACKAGES = (
    "leonaid.application.",
    "leonaid.domain.",
    "leonaid.adapters.postgres.",
    "leonaid.modules.",
)


@cache
def import_graph(root: Path) -> dict[str, frozenset[str]]:
    """Reverse import graph of src/leonaid: module -> modules importing it."""
    source = root / "src"
    modules: dict[str, Path] = {}
    for path in sorted((source / "leonaid").rglob("*.py")):
        parts = list(path.relative_to(source).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules[".".join(parts)] = path
    importers: dict[str, set[str]] = {name: set() for name in modules}
    for name, path in modules.items():
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        targets: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    anchor = package.split(".")
                    anchor = anchor[: len(anchor) - node.level + 1]
                    base = ".".join([*anchor, base] if base else anchor)
                targets.add(base)
                targets.update(f"{base}.{alias.name}" for alias in node.names)
        for target in targets:
            # "import leonaid.a.b" also imports its packages.
            while target:
                if target in importers and target != name:
                    importers[target].add(name)
                target = target.rpartition(".")[0]
    return {name: frozenset(found) for name, found in importers.items()}


def module_of(path: str) -> str | None:
    if not (path.startswith("src/leonaid/") and path.endswith(".py")):
        return None
    parts = path[len("src/") : -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def stem_owners(module: str) -> set[str]:
    for package in OWNER_PACKAGES:
        if module.startswith(package):
            stem = module[len(package) :].split(".")[0]
            return set(E2E_OWNERS.get(stem, ()))
    return set()


def matches_module(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def e2e_owners(path: str, root: Path | None = None) -> set[str] | None:
    """E2E leaves a changed src/leonaid module reaches; None for other paths.

    1. The module and everything that imports it (transitively) are mapped
       by stem through E2E_OWNERS.
    2. A specific MODULE_OWNERS prefix of the module itself is added
       (adapters and entry points wired by dependency injection; ALL_E2E
       for the HTTP surface, wiring and platform).
    3. A reviewed E2E_NEUTRAL module adds nothing beyond its stem owners.
    4. A module with no owner at all selects every leaf (CATCH_ALL).
    """
    module = module_of(path)
    if module is None:
        return None
    graph = import_graph((root or ROOT).resolve())
    seen = {module}
    queue = [module]
    while queue:
        for importer in graph.get(queue.pop(), ()):
            if importer not in seen:
                seen.add(importer)
                queue.append(importer)
    owners: set[str] = set()
    for name in seen:
        owners |= stem_owners(name)
    neutral = any(matches_module(module, n) for n in E2E_NEUTRAL)
    for prefix, mapped in MODULE_OWNERS:
        if not matches_module(module, prefix):
            continue
        if prefix in CATCH_ALL_PREFIXES:
            # Fallback only: an unmapped module without stem owners.
            if owners or neutral:
                return owners
        elif neutral:
            return owners
        return owners | (set(E2E_SHARDS) if mapped == ALL_E2E else set(mapped))
    return owners if (owners or neutral) else set(E2E_SHARDS)


def classify(path: str) -> tuple[frozenset[str], str]:
    for rule in RULES:
        if matches(path, rule.patterns):
            if rule.suites == ALL:
                return everything(), rule.reason
            return frozenset(rule.suites), rule.reason
    return everything(), "unmapped path"


def pack(
    names: Sequence[str], seconds: Mapping[str, int], max_bins: int
) -> list[list[str]]:
    """Longest-processing-time-first bin packing, deterministic.

    The bin count is the smallest that keeps the average at TARGET_SECONDS,
    capped at ``max_bins``. Bins come back longest first.
    """
    if not names:
        return []
    ordered = sorted(names, key=lambda name: (-seconds[name], name))
    total = sum(seconds[name] for name in ordered)
    count = max(1, min(max_bins, len(ordered), math.ceil(total / TARGET_SECONDS)))
    bins: list[list[str]] = [[] for _ in range(count)]
    loads = [0] * count
    for name in ordered:
        index = min(range(count), key=lambda i: (loads[i], i))
        bins[index].append(name)
        loads[index] += seconds[name]
    order = sorted(range(count), key=lambda i: (-loads[i], i))
    return [bins[i] for i in order]


def fast_pack(
    names: Sequence[str], seconds: Mapping[str, int]
) -> tuple[list[list[str]], list[str]]:
    """Fast-tier legs: first-fit decreasing, deterministic.

    Legs of at most FAST_LEG_SECONDS each; a unit longer than that gets a leg
    of its own. A selected unit is never dropped for the budget. Returns the
    legs (longest first) and an empty list (kept for the callers' shape).
    """
    bins: list[list[str]] = []
    loads: list[int] = []
    for name in sorted(names, key=lambda name: (-seconds[name], name)):
        cost = seconds[name]
        for index, load in enumerate(loads):
            if load + cost <= FAST_LEG_SECONDS:
                bins[index].append(name)
                loads[index] += cost
                break
        else:
            bins.append([name])
            loads.append(cost)
    order = sorted(range(len(bins)), key=lambda i: (-loads[i], i))
    return [bins[i] for i in order], []


def integration_unit(suite: str) -> str | None:
    """The Integration leg unit of a suite key (a shard or Contract)."""
    if suite == "contract":
        return suite
    if suite.startswith("integration:"):
        return suite.split(":", 1)[1]
    return None


def is_heavy(suite: str) -> bool:
    """Suites the fast tier never runs (browser and acceptance suites)."""
    return (
        suite.startswith("e2e:") or suite in (SMOKE, "emdash") or suite in HEAVY_FLAGS
    )


def matrix(
    bins: Sequence[Sequence[str]], bootstrap: Callable[[Sequence[str]], str]
) -> list[dict[str, str]]:
    """GitHub matrix legs: stable id for artifacts, readable title for the UI."""
    return [
        {
            "id": str(number),
            "count": str(len(bins)),
            "title": ", ".join(names),
            "shards": " ".join(names),
            "bootstrap": bootstrap(names),
        }
        for number, names in enumerate(bins, start=1)
    ]


def integration_bootstrap(names: Sequence[str]) -> str:
    return "seed" if SEED_BOOTSTRAP & set(names) else "toolchains"


def emdash_bootstrap(names: Sequence[str]) -> str:
    return "toolchains" if set(names) == {"static"} else "browser"


@dataclass(frozen=True)
class Selection:
    full: bool
    reason: str
    suites: frozenset[str]
    explanation: tuple[tuple[str, str, tuple[str, ...]], ...] = ()
    # "fast" (pull request), "full" (full-ci label), "post-merge"
    # (push to main) or "complete" (schedule, dispatch, push without a diff).
    tier: str = "complete"
    # What the change selects but the fast tier leaves to the post-merge run.
    deferred: frozenset[str] = frozenset()

    def shards(self, prefix: str, names: Sequence[str]) -> list[str]:
        return [n for n in names if f"{prefix}:{n}" in self.suites]

    def integration_units(self) -> list[str]:
        units = self.shards("integration", INTEGRATION_SHARDS)
        return units + (["contract"] if "contract" in self.suites else [])

    def integration_bins(self) -> list[list[str]]:
        if self.tier == "fast":
            # Required security proofs get a leg each; select() kept only
            # other units that fit, so nothing is dropped here.
            units = self.integration_units()
            solo = [[unit] for unit in units if unit in FAST_REQUIRED]
            rest = [unit for unit in units if unit not in FAST_REQUIRED]
            return solo + fast_pack(rest, INTEGRATION_SECONDS)[0]
        return pack(
            self.integration_units(), INTEGRATION_SECONDS, MAX_BINS["integration"]
        )

    def e2e_bins(self) -> list[list[str]]:
        bins = pack(self.shards("e2e", E2E_SHARDS), E2E_SECONDS, MAX_BINS["e2e"])
        # The smoke leg runs alone (tools/ci/e2e.sh) and only when not every
        # E2E leaf runs anyway.
        if SMOKE in self.suites and not e2e(*E2E_SHARDS) <= self.suites:
            bins.append([SMOKE])
        return bins

    def emdash_bins(self) -> list[list[str]]:
        return [list(b) for b in EMDASH_BINS] if "emdash" in self.suites else []

    def outputs(self) -> dict[str, str]:
        result = {
            "full": json.dumps(self.full),
            "reason": self.reason,
            "integration": json.dumps(
                matrix(self.integration_bins(), integration_bootstrap)
            ),
            "e2e": json.dumps(matrix(self.e2e_bins(), lambda _: "browser")),
            "emdash": json.dumps(matrix(self.emdash_bins(), emdash_bootstrap)),
            "tier": self.tier,
        }
        for flag in FLAGS:
            result[flag] = json.dumps(flag in self.suites)
        return result


@dataclass(frozen=True)
class Mapped:
    """What the changed paths select, before the tier decides when it runs."""

    suites: frozenset[str]
    # Suites selected by a specific rule (not shared infrastructure, an
    # unmapped path or the import graph): candidates for the fast tier.
    specific: frozenset[str]
    explanation: tuple[tuple[str, str, tuple[str, ...]], ...]


def map_paths(changed: Sequence[str], root: Path | None) -> Mapped:
    """Suites per changed path (``RULES``, import graph, API/pins filters)."""
    suites: set[str] = set()
    specific: set[str] = set()
    explanation = []
    for path in changed:
        selected, reason = classify(path)
        if selected == everything():
            # Unknown or shared: every non-E2E suite, the smoke leg, and the
            # E2E leaves the import graph maps.
            owners = e2e_owners(path, root)
            selected = everything_but_e2e() | {SMOKE} | e2e(*(owners or ()))
            if owners is not None:
                reason = (
                    f"{reason}; import graph: {', '.join(sorted(owners)) or 'no leaf'}"
                )
        else:
            specific |= selected
        if matches(path, API_PATHS) and not matches(path, API_EXCLUDED):
            # The live API contract rides in an Integration leg.
            selected = selected | {"api", "integration:api-contract"}
        if matches(path, PINS_PATHS):
            selected = selected | {"pins"}
        suites |= selected
        explanation.append((path, reason, tuple(sorted(selected))))
    if e2e(*E2E_SHARDS) <= suites:
        # Every leaf runs; the smoke leg would only repeat three of them.
        suites.discard(SMOKE)
    return Mapped(frozenset(suites), frozenset(specific), tuple(explanation))


def required_security(changed: Sequence[str]) -> list[str]:
    """FAST_REQUIRED proofs the changed paths reach (decision E-019)."""
    return [
        unit
        for unit, patterns in FAST_REQUIRED.items()
        if any(matches(path, patterns) for path in changed)
    ]


def fast_tier(
    mapped: Mapped, required: Sequence[str] = ()
) -> tuple[frozenset[str], frozenset[str]]:
    """(suites, deferred): what a pull request runs before the merge.

    Browser and acceptance suites never run here. The ``required`` security
    proofs always run (a leg each). Other Integration shards and Contract run
    only when a specific rule selected them and all of them fit the fast
    legs; the rest of the selection runs after the merge.
    """
    kept = {
        suite
        for suite in mapped.suites
        if not is_heavy(suite) and integration_unit(suite) is None
    }
    kept |= {f"integration:{unit}" for unit in required}
    candidates = [
        unit
        for suite in sorted(mapped.suites & mapped.specific)
        if (unit := integration_unit(suite)) is not None and unit not in required
    ]
    bins, _ = fast_pack(candidates, INTEGRATION_SECONDS)
    for unit in (unit for leg in bins for unit in leg):
        kept.add("contract" if unit == "contract" else f"integration:{unit}")
    suites = frozenset(kept)
    return suites, mapped.suites - suites


def select(
    event: str,
    paths: Sequence[str],
    base_ref: str = "",
    schedule: str = "",
    full_ci: bool = False,
    root: Path | None = None,
) -> Selection:
    """Suites for an event (see the module docstring for the tiers).

    ``base_ref`` is accepted for the workflow's call and ignored: a pull
    request into another branch runs like one into main.

    ``push`` with ``paths`` is the post-merge run on main: the paths changed
    since the last green run there. ``push`` without paths (no green run
    found, the probe branch) runs the complete suite.
    """
    changed = sorted({p.strip() for p in paths if p.strip()})
    if event == "push" and changed:
        mapped = map_paths(changed, root)
        full = mapped.suites >= everything()
        reason = (
            "post-merge: complete suite"
            if full
            else "post-merge: suites of the paths changed since the last green run"
        )
        return Selection(
            full, reason, mapped.suites, mapped.explanation, tier="post-merge"
        )
    if event != "pull_request":
        return Selection(True, f"{event}: complete suite", everything())
    if not changed:
        return Selection(
            True, "pull_request without a readable diff: complete suite", everything()
        )
    mapped = map_paths(changed, root)
    if full_ci:
        return Selection(
            True,
            f"pull_request with the {FULL_CI_LABEL} label: complete suite before the merge",
            everything(),
            mapped.explanation,
            tier="full",
        )
    required = required_security(changed)
    if "integration:api-contract" in mapped.suites:
        # The API contract gate is required: its leg always runs (own leg).
        required.append("api-contract")
    suites, deferred = fast_tier(mapped, required)
    return Selection(
        False,
        "pull_request: fast tier; the rest runs after the merge on main",
        suites,
        mapped.explanation,
        tier="fast",
        deferred=deferred,
    )


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


def leg_estimate(kind: str, names: Sequence[str], seconds: Mapping[str, int]) -> int:
    """Estimated leg runtime: job setup, per-shard stack boot and test time."""
    return (
        LEG_SETUP_SECONDS
        + SHARD_SETUP_SECONDS[kind] * len(names)
        + sum(seconds[name] for name in names)
    )


def load_warnings(selection: Selection) -> list[str]:
    """Legs whose estimated runtime nears their job timeout."""
    warnings = []
    for kind, bins, seconds in (
        ("integration", selection.integration_bins(), INTEGRATION_SECONDS),
        ("e2e", selection.e2e_bins(), E2E_SECONDS),
        ("emdash", selection.emdash_bins(), EMDASH_SECONDS),
    ):
        limit = JOB_TIMEOUT_MINUTES[kind] * 60
        for number, names in enumerate(bins, start=1):
            estimate = leg_estimate(kind, names, seconds)
            if estimate > LOAD_WARNING * limit:
                warnings.append(
                    f"{kind} leg {number} ({', '.join(names)}) is estimated at "
                    f"{estimate} s, over {LOAD_WARNING:.0%} of its {limit} s "
                    "timeout: raise MAX_BINS or split a shard"
                )
    return warnings


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
    for key, bins in (
        ("integration", selection.integration_bins()),
        ("e2e", selection.e2e_bins()),
        ("emdash", selection.emdash_bins()),
    ):
        jobs = "<br>".join(f"{n}: {', '.join(b)}" for n, b in enumerate(bins, 1))
        lines.append(f"| {key} | {jobs or '—'} |")
    for key in FLAGS:
        lines.append(f"| {key} | `{outputs[key]}` |")
    if selection.deferred:
        lines += [
            "",
            "**After the merge on main** (or now with the "
            f"`{FULL_CI_LABEL}` label): "
            + ", ".join(f"`{suite}`" for suite in sorted(selection.deferred)),
        ]
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
        "--schedule", default="", help="cron of a scheduled run (github.event.schedule)"
    )
    parser.add_argument(
        "--labels",
        default="",
        help=f"pull request labels, comma-separated; {FULL_CI_LABEL} runs the "
        "complete suite",
    )
    parser.add_argument(
        "--base-ref",
        default="",
        help="pull request base branch (ignored; kept for the workflow call)",
    )
    parser.add_argument(
        "--paths-file", help="newline-separated changed paths instead of git diff"
    )
    parser.add_argument("--explain", action="store_true", help="print per-path rules")
    args = parser.parse_args(argv)

    paths: list[str] = []
    # A push diffs only when the workflow found the last green run on main
    # (--base); otherwise it runs the complete suite.
    if args.event == "pull_request" or (args.event == "push" and args.base):
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
    labels = {label.strip() for label in args.labels.split(",") if label.strip()}
    selection = select(
        args.event,
        paths,
        args.base_ref,
        schedule=args.schedule,
        full_ci=FULL_CI_LABEL in labels,
    )
    outputs = selection.outputs()
    for warning in load_warnings(selection):
        print(f"::warning title=CI leg near timeout::{warning}")

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
