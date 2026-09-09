"""Process-level checks for the survey gate; these do not replace service tests."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("survey_gate", HERE / "gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class GateTests(unittest.TestCase):
    def test_ci_suites_partition_every_check_and_keep_recovery_nightly(self):
        manifest = gate.load_manifest(ROOT)
        pr = set(gate.ci_shards(manifest, "pr"))
        nightly = set(gate.ci_shards(manifest, "nightly"))
        self.assertFalse(pr & nightly)
        self.assertEqual(pr | nightly, set(gate.ci_shards(manifest, "all")))
        nightly_checks = {
            check for name in nightly for check in manifest["ciShards"][name]
        }
        required = {c["id"] for c in manifest["checks"] if c["group"] == "recovery"} | {
            "restore-receipts",
            "export-recovery",
        }
        self.assertTrue(required <= nightly_checks)
        self.assertEqual(len(nightly_checks), 13)
        with self.assertRaises(ValueError):
            gate.ci_shards(manifest, "unknown")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Synthetic",
                "-c",
                "user.email=synthetic@example.invalid",
                "commit",
                "--quiet",
                "--allow-empty",
                "-m",
                "fixture",
            ],
            cwd=self.root,
            check=True,
        )
        (self.root / "tools/surveys").mkdir(parents=True)
        (self.root / "tools/surveys/gate.json").write_text("{}")

    def manifest(self, checks):
        return {
            "groups": ["fixture"],
            "checks": checks,
            "manualReviewRequired": ["review-still-required"],
        }

    def check(self, name, source):
        return {"id": name, "group": "fixture", "argv": [sys.executable, "-c", source]}

    def report(self):
        reports = list((self.root / ".artifacts/surveys-gate/results").glob("*.json"))
        self.assertEqual(len(reports), 1)
        return json.loads(reports[0].read_text())

    def test_failure_stops_sequence_and_never_publishes_child_output(self):
        manifest = self.manifest(
            [
                self.check(
                    "first", "print('PRIVATE_ANSWER_AND_TOKEN'); raise SystemExit(23)"
                ),
                self.check(
                    "must-not-run",
                    "from pathlib import Path; Path('unexpected').touch()",
                ),
            ]
        )
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            self.assertEqual(gate.run(self.root, manifest, ["fixture"], 2), 23)
        report = self.report()
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["automatedGatePassed"])
        self.assertEqual([c["id"] for c in report["checks"]], ["first"])
        self.assertFalse((self.root / "unexpected").exists())
        self.assertNotIn(
            "PRIVATE_ANSWER_AND_TOKEN", captured.getvalue() + json.dumps(report)
        )
        logs = list((self.root / ".artifacts/surveys-gate").glob("private-*/*.log"))
        self.assertEqual(len(logs), 1)
        self.assertIn("PRIVATE_ANSWER_AND_TOKEN", logs[0].read_text())
        self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)

    def test_repeat_executes_every_selected_check_each_time(self):
        source = "from pathlib import Path; p=Path('count'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')"
        manifest = self.manifest([self.check("one", source), self.check("two", source)])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate.run(self.root, manifest, ["fixture"], 2), 0)
        self.assertEqual((self.root / "count").read_text(), "4")
        report = self.report()
        self.assertEqual([c["pass"] for c in report["checks"]], [1, 1, 2, 2])
        self.assertTrue(report["automatedGatePassed"])
        self.assertEqual(report["manualReviewRequired"], ["review-still-required"])

    def test_missing_executable_returns_failure(self):
        self.assertEqual(
            gate.execute(
                ["/definitely-missing-survey-test-program"],
                self.root,
                self.root / "private.log",
            ),
            127,
        )

    def test_shard_runs_only_assigned_checks_once(self):
        source = "from pathlib import Path; p=Path('count'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')"
        manifest = self.manifest([self.check("one", source), self.check("two", source)])
        manifest["ciShards"] = {"first": ["one"], "second": ["two"]}
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate.run(self.root, manifest, ["fixture"], 1, "second"), 0)
        self.assertEqual((self.root / "count").read_text(), "1")
        report = self.report()
        self.assertEqual(report["shard"], "second")
        self.assertEqual([c["id"] for c in report["checks"]], ["two"])

    def test_checkout_lock_excludes_a_second_process_and_releases(self):
        directory = self.root / "lock"
        source = f"import runpy; m=runpy.run_path({str(HERE / 'gate.py')!r}); from pathlib import Path\nwith m['exclusive_run'](Path({str(directory)!r})): print('entered')"
        with gate.exclusive_run(directory):
            result = subprocess.run(
                [sys.executable, "-c", source], capture_output=True, text=True
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("entered", result.stdout)
        result = subprocess.run(
            [sys.executable, "-c", source], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "entered")

    def test_signal_reaches_owned_child_and_waits_for_cleanup(self):
        child = self.root / "child.py"
        child.write_text(
            "import signal,time\nfrom pathlib import Path\ndef stop(*args):\n Path('cleaned').touch()\n raise SystemExit(0)\nsignal.signal(signal.SIGTERM,stop)\nPath('ready').touch()\nwhile True: time.sleep(0.05)\n"
        )
        source = f"import runpy; from pathlib import Path; m=runpy.run_path({str(HERE / 'gate.py')!r}); raise SystemExit(m['execute']([{sys.executable!r},{str(child)!r}], Path({str(self.root)!r}), Path({str(self.root / 'signal.log')!r})))"
        process = subprocess.Popen(
            [sys.executable, "-c", source],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 10
            while not (self.root / "ready").exists():
                self.assertIsNone(process.poll())
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
            os.kill(process.pid, signal.SIGTERM)
            process.communicate(timeout=10)
            self.assertEqual(process.returncode, 130)
            self.assertTrue((self.root / "cleaned").exists())
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_repository_inventory_includes_every_infrastructure_mode_once(self):
        manifest = gate.load_manifest(ROOT)
        self.assertEqual(
            set(manifest["groups"]), {check["group"] for check in manifest["checks"]}
        )
        self.assertTrue(any(check["id"] == "journeys" for check in manifest["checks"]))
        self.assertTrue(
            any(check["id"] == "pilot-survey-recovery" for check in manifest["checks"])
        )

    def test_manifest_rejects_missing_mode_and_recursive_aggregate(self):
        original = gate.load_manifest(ROOT)
        for check in original["checks"]:
            if check["argv"][0] != "./leonaid":
                target = self.root / check["argv"][1]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text((ROOT / check["argv"][1]).read_text())
        for reference in original["manualReviewRequired"]:
            target = self.root / reference.split("#")[0]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
        for change in ("missing", "recursive", "unassigned", "duplicate"):
            with self.subTest(change=change):
                manifest = json.loads(json.dumps(original))
                if change == "missing":
                    manifest["checks"] = [
                        c for c in manifest["checks"] if c["id"] != "journeys"
                    ]
                elif change == "recursive":
                    next(c for c in manifest["checks"] if c["id"] == "core")["argv"][
                        1
                    ] = "test-surveys"
                elif change == "unassigned":
                    manifest["ciShards"].pop(next(iter(manifest["ciShards"])))
                else:
                    manifest["ciShards"]["duplicate"] = ["journeys"]
                (self.root / "tools/surveys/gate.json").write_text(json.dumps(manifest))
                with self.assertRaises(AssertionError):
                    gate.load_manifest(self.root)


if __name__ == "__main__":
    unittest.main()
