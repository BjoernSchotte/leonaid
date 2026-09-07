"""Diagnostic metadata must not reproduce arbitrary service/test output."""

import importlib.util
import json
from pathlib import Path
import unittest
import tempfile
import subprocess

spec = importlib.util.spec_from_file_location(
    "diagnostics", Path(__file__).with_name("ci_diagnostics.py")
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DiagnosticsTests(unittest.TestCase):
    def test_private_values_are_never_serialized(self):
        raw = """Permission denied SECRET_CANARY_token answer=PRIVATE_CANARY_answer
email=private-person@example.com cookie=VERY_PRIVATE_COOKIE
/home/private-person/private-project/SECRET_CANARY_file.py:23
/workspace/tests/e2e/surveys-infrastructure.spec.mjs:9:1
File "/workspace/tools/surveys/foundation_acceptance.py", line 31
AssertionError: expected PRIVATE_CANARY_answer
"""
        public = {
            "tests/e2e/surveys-infrastructure.spec.mjs": 100,
            "tools/surveys/foundation_acceptance.py": 90,
        }
        report = module.classify(raw, public)
        self.assertEqual(report["observedMarkers"], ["assertion", "permission-denied"])
        self.assertEqual(
            report["publicLocations"],
            [
                {"file": "tests/e2e/surveys-infrastructure.spec.mjs", "line": 9},
                {"file": "tools/surveys/foundation_acceptance.py", "line": 31},
            ],
        )
        for marker in ("CANARY", "private-person", "COOKIE", "expected"):
            self.assertNotIn(marker, json.dumps(report))

    def test_unknown_paths_and_impossible_lines_are_discarded(self):
        report = module.classify(
            "tests/private/customer.ts:1 tests/public.ts:999999 tests/public.ts:0",
            {"tests/public.ts": 10},
        )
        self.assertEqual(report, {"observedMarkers": [], "publicLocations": []})

    def test_collector_uses_only_manifest_logs_and_tracked_public_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            public = root / "tests/public.py"
            public.parent.mkdir()
            public.write_text("pass\n")
            subprocess.run(["git", "add", "tests/public.py"], cwd=root, check=True)
            manifest = root / "tools/surveys/gate.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"checks": [{"id": "core"}]}))
            logs = root / ".artifacts/surveys-gate/private-fixture"
            logs.mkdir(parents=True)
            (logs / "1-core.log").write_text(
                "ModuleNotFoundError SECRET_CANARY\ntests/public.py:1"
            )
            (logs / "1-private-answer.log").write_text("Permission denied")
            secret = root / "secret"
            secret.write_text("Pool overlaps SECRET_CANARY")
            (logs / "2-core.log").symlink_to(secret)
            report = module.collect(root)
            self.assertEqual(len(report["diagnostics"]), 1)
            self.assertEqual(
                report["diagnostics"][0]["observedMarkers"], ["python-module-missing"]
            )
            self.assertNotIn("CANARY", json.dumps(report))
            self.assertNotIn("private-answer", json.dumps(report))

    def test_docker_failure_has_fixed_category_without_daemon_details(self):
        report = module.classify("Pool overlaps PRIVATE_NETWORK_NAME", {})
        self.assertEqual(
            report, {"observedMarkers": ["subnet-overlap"], "publicLocations": []}
        )


if __name__ == "__main__":
    unittest.main()
