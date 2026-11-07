"""Failed survey checks get a sanitized, bounded excerpt; nothing else does."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "excerpt", Path(__file__).with_name("ci_failure_excerpt.py")
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SECRET = "s3cr3t-session-value-0123456789"


class ExcerptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / ".env.local").write_text(f"LEONAID_SESSION_SECRET={SECRET}\n")
        self.gate = self.root / ".artifacts/surveys-gate"
        (self.gate / "results").mkdir(parents=True)
        (self.gate / "private-abc").mkdir()
        self.destination = self.root / "out"

    def report(self, *checks):
        (self.gate / "results/run.json").write_text(
            json.dumps({"checks": [dict(c) for c in checks]})
        )

    def log(self, name, text):
        (self.gate / f"private-abc/{name}.log").write_text(text)

    def test_failed_check_prints_failure_lines_tail_and_redacts_secrets(self):
        self.report(
            {"id": "runner", "pass": 1, "exitCode": 0},
            {"id": "permissions", "pass": 1, "exitCode": 1},
        )
        filler = "".join(f"step {n}\n" for n in range(400))
        self.log("1-runner", "passing output\n")
        self.log(
            "1-permissions",
            "  ✘ 3 [chromium] › survey-permissions.spec.mjs:41 › owner edits\n"
            "\x1b[31mError: expect(received).toBe(expected)\x1b[0m\n"
            + filler
            + f"api-1 | token={SECRET}\napi-1 | container unhealthy\n",
        )
        printed = module.export(self.root, self.destination)
        self.assertEqual([label for label, _ in printed], ["1-permissions"])
        text = printed[0][1]
        self.assertIn("survey-permissions.spec.mjs:41 › owner edits", text)
        self.assertIn("Error: expect(received).toBe(expected)", text)
        self.assertNotIn("\x1b[", text)
        self.assertIn("container unhealthy", text)
        self.assertNotIn(SECRET, text)
        self.assertIn("[REDACTED:LEONAID_SESSION_SECRET]", text)
        self.assertNotIn("step 10\n", text)  # bounded: only the tail
        written = (self.destination / "1-permissions.log").read_text()
        self.assertEqual(written, text)

    def test_personal_data_withholds_the_excerpt(self):
        self.report({"id": "editor", "pass": 1, "exitCode": 1})
        self.log("1-editor", "Error: mail to person@example.com failed\n")
        printed = module.export(self.root, self.destination)
        self.assertEqual(len(printed), 1)
        self.assertIn("withheld", printed[0][1])
        self.assertNotIn("person@example.com", printed[0][1])

    def test_foundation_checks_include_their_harness_log(self):
        self.report({"id": "foundation-diagnostics", "pass": 1, "exitCode": 2})
        harness = self.root / ".artifacts/foundation-acceptance"
        harness.mkdir(parents=True)
        (harness / "infrastructure.log").write_text("Timeout waiting for api\n")
        printed = dict(module.export(self.root, self.destination))
        self.assertIn("Timeout waiting for api", printed["foundation-diagnostics-harness"])

    def test_no_failure_no_excerpt_and_unsafe_ids_ignored(self):
        self.report(
            {"id": "runner", "pass": 1, "exitCode": 0},
            {"id": "../../etc/passwd", "pass": 1, "exitCode": 1},
        )
        self.log("1-runner", "Error: harmless\n")
        self.assertEqual(module.export(self.root, self.destination), [])


if __name__ == "__main__":
    unittest.main()
