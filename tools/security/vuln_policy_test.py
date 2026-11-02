#!/usr/bin/env python3
"""Unit tests for the vulnerability scope, waiver and gate policy.

Run with PYTHONPATH set to the repository root.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any

from tools.security import vuln_policy
from tools.security.vuln_policy import check, gate

TODAY = date(2026, 11, 2)
DIGEST = "sha256:" + "a" * 64
REASON = "No fixed upstream release yet; the vulnerable code path is unreachable here."


def lock(*ids: str) -> dict[str, Any]:
    return {
        "systems": [
            {"id": system_id, "image": f"docker.io/x/{system_id}:1.0@{DIGEST}"}
            for system_id in ids
        ]
    }


def scope(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schemaVersion": 1,
        "ownImages": ["leonaid-api"],
        "runtime": ["twenty"],
        "excluded": {
            "trivy": {
                "kind": "toolchain",
                "reason": "Scanner itself, runs in CI only and is never deployed.",
            }
        },
    }
    data.update(overrides)
    return data


def waiver(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "CVE-2026-0001",
        "targets": ["image:twenty"],
        "reason": REASON,
        "reviewer": "Björn Schotte",
        "reviewedOn": "2026-11-01",
        "expires": "2026-12-01",
    }
    data.update(overrides)
    return data


def trivy_report(*vulns: dict[str, Any]) -> dict[str, Any]:
    return {"Results": [{"Target": "x", "Vulnerabilities": list(vulns)}]}


def trivy_vuln(severity: str = "HIGH", fixed: str = "1.2.3") -> dict[str, Any]:
    return {
        "VulnerabilityID": "CVE-2026-0001",
        "PkgName": "openssl",
        "InstalledVersion": "1.0",
        "FixedVersion": fixed,
        "Severity": severity,
    }


def osv_report(
    score: str = "7.5", fixed: bool = True, label: str | None = None
) -> dict[str, Any]:
    events: list[dict[str, str]] = [{"introduced": "0"}]
    if fixed:
        events.append({"fixed": "2.0.0"})
    vulnerability: dict[str, Any] = {
        "id": "GHSA-aaaa-bbbb-cccc",
        "affected": [
            {
                "package": {"name": "undici"},
                "ranges": [{"type": "SEMVER", "events": events}],
            }
        ],
    }
    if label is not None:
        vulnerability["database_specific"] = {"severity": label}
    return {
        "results": [
            {
                "source": {"path": "/workspace/bun.lock"},
                "packages": [
                    {
                        "package": {"name": "undici", "version": "1.0.0"},
                        "vulnerabilities": [vulnerability],
                        "groups": [
                            {
                                "ids": ["GHSA-aaaa-bbbb-cccc"],
                                "aliases": ["CVE-2026-0002", "GHSA-aaaa-bbbb-cccc"],
                                "max_severity": score,
                            }
                        ],
                    }
                ],
            }
        ]
    }


class PolicyTree:
    def __init__(self, directory: Path) -> None:
        self.root = directory / "repo"
        self.reports = directory / "reports"
        self.reports.mkdir()
        self.write(vuln_policy.LOCK, lock("twenty", "trivy"))
        self.write(vuln_policy.SCOPE, scope())
        self.allow()
        self.clean_reports()

    def write(self, relative: Path | str, data: Any) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def allow(self, *entries: dict[str, Any]) -> None:
        self.write(
            vuln_policy.ALLOWLIST, {"schemaVersion": 1, "entries": list(entries)}
        )

    def report(self, target: str, data: Any) -> None:
        path = self.reports / vuln_policy.report_file(target)
        path.write_text(json.dumps(data), encoding="utf-8")

    def clean_reports(self) -> None:
        for target in ("fs", "image:leonaid-api", "image:twenty"):
            self.report(target, trivy_report())
        self.report("osv", {"results": []})

    def problems(self) -> list[str]:
        return check(self.root, TODAY)[2].messages

    def gate(self) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = gate(self.root, self.reports, TODAY)
        return status, output.getvalue()


class PolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.tree = PolicyTree(Path(self.directory.name))

    def tearDown(self) -> None:
        self.directory.cleanup()

    def assertProblem(self, fragment: str) -> None:
        problems = self.tree.problems()
        self.assertTrue(
            any(fragment in message for message in problems),
            f"{fragment!r} not in {problems}",
        )

    def test_valid_policy_lists_every_target(self) -> None:
        targets, waivers, problems = check(self.tree.root, TODAY)
        self.assertEqual(problems.messages, [])
        self.assertEqual(
            [(t.name, t.mode) for t in targets],
            [
                ("fs", "fs"),
                ("osv", "osv"),
                ("image:leonaid-api", "local"),
                ("image:twenty", "remote"),
            ],
        )
        self.assertEqual(targets[-1].reference, f"docker.io/x/twenty:1.0@{DIGEST}")

    def test_unclassified_lock_system_fails(self) -> None:
        self.tree.write(vuln_policy.LOCK, lock("twenty", "trivy", "newcomer"))
        self.assertProblem("without scan decision: ['newcomer']")

    def test_exclusion_needs_reason_and_kind(self) -> None:
        self.tree.write(
            vuln_policy.SCOPE,
            scope(excluded={"trivy": {"kind": "whatever", "reason": "short"}}),
        )
        self.assertProblem("excluded trivy needs kind")

    def test_expired_waiver_fails(self) -> None:
        self.tree.allow(waiver(reviewedOn="2026-08-01", expires="2026-11-01"))
        self.assertProblem("waiver EXPIRED on 2026-11-01")

    def test_waiver_expiring_today_is_valid(self) -> None:
        self.tree.allow(waiver(reviewedOn="2026-10-01", expires="2026-11-02"))
        self.assertEqual(self.tree.problems(), [])

    def test_waiver_longer_than_ninety_days_fails(self) -> None:
        self.tree.allow(waiver(expires="2027-03-01"))
        self.assertProblem("more than 90 days after review")

    def test_waiver_without_reason_or_reviewer_fails(self) -> None:
        self.tree.allow(waiver(reason="accepted", reviewer=" "))
        self.assertProblem("reason must explain")
        self.assertProblem("reviewer is required")

    def test_waiver_with_unknown_target_or_field_fails(self) -> None:
        entry = waiver(targets=["image:nope"])
        entry["note"] = "x"
        self.tree.allow(entry)
        self.assertProblem("unknown target 'image:nope'")
        self.assertProblem("must have exactly the fields")

    def test_waiver_reviewed_in_future_fails(self) -> None:
        self.tree.allow(waiver(reviewedOn="2026-11-03", expires="2026-12-01"))
        self.assertProblem("lies in the future")

    def test_clean_reports_pass(self) -> None:
        status, output = self.tree.gate()
        self.assertEqual(status, 0, output)

    def test_fixable_high_image_finding_blocks(self) -> None:
        self.tree.report("image:twenty", trivy_report(trivy_vuln()))
        status, output = self.tree.gate()
        self.assertEqual(status, 1)
        self.assertIn("BLOCKING image:twenty: CVE-2026-0001 HIGH openssl", output)

    def test_unfixed_or_medium_image_finding_passes(self) -> None:
        self.tree.report(
            "image:twenty",
            trivy_report(trivy_vuln(fixed=""), trivy_vuln(severity="MEDIUM")),
        )
        self.assertEqual(self.tree.gate()[0], 0)

    def test_waiver_applies_only_to_its_target(self) -> None:
        self.tree.allow(waiver())
        self.tree.report("image:twenty", trivy_report(trivy_vuln()))
        self.assertEqual(self.tree.gate()[0], 0)
        self.tree.report("image:leonaid-api", trivy_report(trivy_vuln("CRITICAL")))
        status, output = self.tree.gate()
        self.assertEqual(status, 1)
        self.assertIn("BLOCKING image:leonaid-api", output)

    def test_expired_waiver_does_not_waive(self) -> None:
        self.tree.allow(waiver(reviewedOn="2026-08-01", expires="2026-11-01"))
        self.tree.report("image:twenty", trivy_report(trivy_vuln()))
        status, output = self.tree.gate()
        self.assertEqual(status, 1)
        self.assertIn("EXPIRED", output)
        self.assertIn("BLOCKING", output)

    def test_unused_waiver_is_reported(self) -> None:
        self.tree.allow(waiver())
        status, output = self.tree.gate()
        self.assertEqual(status, 0)
        self.assertIn("matched nothing", output)

    def test_missing_report_fails(self) -> None:
        (self.tree.reports / "image--twenty.json").unlink()
        status, output = self.tree.gate()
        self.assertEqual(status, 1)
        self.assertIn("missing or unreadable scan report for image:twenty", output)

    def test_osv_high_with_fix_blocks(self) -> None:
        self.tree.report("osv", osv_report("7.5"))
        status, output = self.tree.gate()
        self.assertEqual(status, 1)
        self.assertIn("BLOCKING osv:bun.lock", output)

    def test_osv_moderate_or_unfixed_passes(self) -> None:
        self.tree.report("osv", osv_report("5.3"))
        self.assertEqual(self.tree.gate()[0], 0)
        self.tree.report("osv", osv_report("9.8", fixed=False))
        self.assertEqual(self.tree.gate()[0], 0)

    def test_osv_without_score_uses_label_then_blocks_unknown(self) -> None:
        self.tree.report("osv", osv_report("", label="MODERATE"))
        self.assertEqual(self.tree.gate()[0], 0)
        self.tree.report("osv", osv_report("", label="HIGH"))
        self.assertEqual(self.tree.gate()[0], 1)
        self.tree.report("osv", osv_report(""))
        status, output = self.tree.gate()
        self.assertEqual(status, 1)
        self.assertIn("UNKNOWN", output)

    def test_osv_waiver_matches_alias(self) -> None:
        self.tree.allow(waiver(id="CVE-2026-0002", targets=["osv"]))
        self.tree.report("osv", osv_report("8.1"))
        self.assertEqual(self.tree.gate()[0], 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
