"""Ensure regression collision/read failures never invoke Docker mutations."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


FAKE_DOCKER = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ["LEONAID_GUARD_CALLS"]).open("a") as stream:
    stream.write(json.dumps(args) + "\\n")
mode = os.environ["LEONAID_GUARD_CASE"]
selected = os.environ.get("LEONAID_GUARD_PROJECT_PREFIX")
if selected and not any(arg.startswith("label=com.docker.compose.project=" + selected) for arg in args):
    raise SystemExit(0)
if mode == "inventory-error":
    raise SystemExit(64)
kind = {"ps": "containers", "volume": "volumes", "network": "networks"}.get(args[0])
if kind is None:
    raise SystemExit("Unexpected Docker operation")
if mode == kind:
    print("existing-owned-elsewhere")
"""


class RegressionIsolationTests(unittest.TestCase):
    def test_collision_and_inventory_failure_do_not_clean_other_resources(self):
        root = Path(__file__).resolve().parents[2]
        for suite in (
            "compose/test.sh",
            "surveys/infrastructure.sh",
            "surveys/restic_recovery.sh",
            "core/test.sh",
            "schema/test.sh",
            "outbox/test.sh",
            "openapi/test.sh",
            "twenty/test.sh",
            "twenty/gateway_test.sh",
            "twenty/import_test.sh",
            "invitations/test.sh",
            "sessions/test.sh",
            "matching/test.sh",
            "assignments/test.sh",
            "activities/test.sh",
            "actions/test.sh",
            "pwa/test.sh",
            "templates/test.sh",
            "action_admin/test.sh",
            "commitments/test.sh",
            "activity_feed/test.sh",
            "invoices/test.sh",
            "typst/test.sh",
            "storage/test.sh",
            "documents/test.sh",
            "mail_relay/test.sh",
            "invoice_delivery/test.sh",
            "invoice_settlements/test.sh",
            "feature_flags/test.sh",
            "operations/test.sh",
            "ui_system/test.sh",
            "dashboard/test.sh",
            "ux_acceptance/test.sh",
            "security/test.sh",
            "privacy/test.sh",
            "testkit/test.sh",
            "golden_journey/test.sh",
            "backup/test.sh",
            "upgrade/test.sh",
            "seed/test.sh",
            "identity/test.sh",
            "policy/test.sh",
            "public_actions/test.sh",
            "public_orders/test.sh",
        ):
            for case in ("containers", "volumes", "networks", "inventory-error"):
                with (
                    self.subTest(suite=suite, case=case),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    temporary = Path(directory)
                    docker = temporary / "docker"
                    docker.write_text(FAKE_DOCKER)
                    docker.chmod(0o700)
                    calls = temporary / "calls.jsonl"
                    result = subprocess.run(
                        ["sh", str(root / "tools" / suite), str(root)],
                        env={
                            **os.environ,
                            "PATH": str(temporary) + os.pathsep + os.environ["PATH"],
                            "LEONAID_GUARD_CASE": case,
                            "LEONAID_GUARD_CALLS": str(calls),
                        },
                        capture_output=True,
                        timeout=10,
                    )
                    self.assertEqual(
                        result.returncode, 64 if case == "inventory-error" else 1
                    )
                    observed = [
                        json.loads(line) for line in calls.read_text().splitlines()
                    ]
                    expected = {
                        "containers": 1,
                        "volumes": 2,
                        "networks": 3,
                        "inventory-error": 1,
                    }[case]
                    self.assertEqual(len(observed), expected)
                    self.assertEqual(observed[0][:2], ["ps", "-aq"])
                    if expected >= 2:
                        self.assertEqual(observed[1][:3], ["volume", "ls", "-q"])
                    if expected == 3:
                        self.assertEqual(observed[2][:3], ["network", "ls", "-q"])
                    self.assertTrue(all("--filter" in call for call in observed))
                    self.assertFalse(
                        any(
                            "compose" in call or "rm" in call or "down" in call
                            for call in observed
                        )
                    )

    def test_operator_target_collision_rejects_before_source_acquisition(self):
        root = Path(__file__).resolve().parents[2]
        for suite, source_prefix, target_prefix in (
            ("backup/test.sh", "leonaid-poc112-source-", "leonaid-restore-poc112-"),
            (
                "upgrade/test.sh",
                "leonaid-poc113-upgrade-",
                "leonaid-restore-poc113-rollback-",
            ),
            (
                "surveys/restic_recovery.sh",
                "leonaid-poc112-surveys-",
                "leonaid-restore-surveys-",
            ),
        ):
            for case in ("containers", "volumes", "networks", "inventory-error"):
                with (
                    self.subTest(suite=suite, case=case),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    temporary = Path(directory)
                    docker = temporary / "docker"
                    docker.write_text(FAKE_DOCKER)
                    docker.chmod(0o700)
                    calls = temporary / "calls.jsonl"
                    result = subprocess.run(
                        ["sh", str(root / "tools" / suite), str(root)],
                        env={
                            **os.environ,
                            "PATH": str(temporary) + os.pathsep + os.environ["PATH"],
                            "LEONAID_GUARD_CASE": case,
                            "LEONAID_GUARD_CALLS": str(calls),
                            "LEONAID_GUARD_PROJECT_PREFIX": target_prefix,
                        },
                        capture_output=True,
                        timeout=10,
                    )
                    self.assertEqual(
                        result.returncode, 64 if case == "inventory-error" else 1
                    )
                    observed = [
                        json.loads(line) for line in calls.read_text().splitlines()
                    ]
                    expected = {
                        "containers": 4,
                        "volumes": 5,
                        "networks": 6,
                        "inventory-error": 4,
                    }[case]
                    self.assertEqual(len(observed), expected)
                    self.assertTrue(all("--filter" in call for call in observed))
                    self.assertTrue(
                        all(source_prefix in call[-1] for call in observed[:3])
                    )
                    self.assertTrue(
                        all(target_prefix in call[-1] for call in observed[3:])
                    )
                    self.assertEqual(
                        [call[0] for call in observed[:3]], ["ps", "volume", "network"]
                    )
                    self.assertEqual(
                        [call[0] for call in observed[3:]],
                        ["ps", "volume", "network"][: expected - 3],
                    )


if __name__ == "__main__":
    unittest.main()
