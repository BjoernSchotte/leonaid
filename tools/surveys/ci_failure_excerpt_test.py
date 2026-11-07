"""Failed survey checks get a sanitized, bounded excerpt; nothing else does."""

import importlib.util
import json
import os
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
        self.destination = self.root / "out/failure-excerpts.json"

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
        written = json.loads(self.destination.read_text())
        self.assertEqual(
            written["excerpts"], [{"source": "1-permissions", "text": text}]
        )

    def test_compose_progress_does_not_crowd_out_the_tail(self):
        self.report({"id": "runner", "pass": 1, "exitCode": 1})
        noise = "".join(
            f" Container leonaid-surveys-1-2-api-{n}  Started\n"
            f' Volume "leonaid-surveys-1-2_data-{n}"  Created\n api  Built\n'
            for n in range(300)
        )
        self.log("1-runner", "Error: runner page never rendered\n" + noise)
        text = module.export(self.root, self.destination)[0][1]
        self.assertIn("Error: runner page never rendered", text)
        self.assertNotIn("Started", text)
        self.assertNotIn("Built", text)

    def excerpt_of(self, text):
        self.report({"id": "runner", "pass": 1, "exitCode": 1})
        self.log("1-runner", text)
        printed = module.export(self.root, self.destination)
        self.assertEqual(len(printed), 1)
        return printed[0][1]

    def test_runtime_credentials_are_redacted_by_shape(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJlLXZhbHVl"
        opaque = "Qm9yZWFsLXNlc3Npb24tVmFsdWUtNzc3OTk4ODg3Nw"
        hexkey = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
        cases = {
            "Authorization: Bearer abc.def-ghi_jkl": "abc.def-ghi_jkl",
            "authorization=Basic dXNlcjpwYXNz": "dXNlcjpwYXNz",
            "GET /x with bearer QWERTY123qwerty": "QWERTY123qwerty",
            "Cookie: leonaid_session=sessval12345; theme=dark": "sessval12345",
            "set-cookie: leonaid_session=setval67890; Path=/": "setval67890",
            "goto https://public.test/surveys/s1?token=tokval4242&x=1": "tokval4242",
            "https://public.test/login?code=codeval9191": "codeval9191",
            "https://s3/x?X-Amz-Signature=amzsig5150&X-Amz-Date=1": "amzsig5150",
            "https://s3/x?X-Amz-Credential=credval6161": "credval6161",
            "request failed; password: pwval5678": "pwval5678",
            '{"apiKey": "jsonkey8080"}': "jsonkey8080",
            "postgres://leonaid:dbpass1212@core-postgres/leonaid": "dbpass1212",
            f"jwt {jwt}": jwt,
            f"opaque {opaque} value": opaque,
            f"hash {hexkey}": hexkey,
        }
        text = self.excerpt_of("".join(f"Error: {line}\n" for line in cases))
        for line, secret in cases.items():
            self.assertNotIn(secret, text, line)
        self.assertIn("[REDACTED]", text)
        # Lower-case Compose names and paths stay readable.
        readable = self.excerpt_of(
            "Error: leonaid-surveys-198279663-14188-core-postgres-1 failed in "
            "tools/surveys/foundation_acceptance.py\n"
        )
        self.assertIn("leonaid-surveys-198279663-14188-core-postgres-1", readable)

    def test_secret_straddling_the_line_cut_is_redacted_whole(self):
        line = "x" * (module.MAX_LINE - 5) + " " + SECRET + "\n"
        text = self.excerpt_of("Error: long line follows\n" + line)
        self.assertNotIn(SECRET[:5], text)
        opaque = "Zx9" * 20
        text = self.excerpt_of("x" * (module.MAX_LINE - 10) + " " + opaque + "\n")
        self.assertNotIn(opaque[:9], text)

    def test_runtime_twenty_key_from_the_prepared_fixture_is_redacted(self):
        fixture = self.root / "fixture"
        fixture.mkdir()
        key = "twentyruntimekey00000000000000000000"
        (fixture / "manifest.json").write_text(json.dumps({"integrationKey": key}))
        os.environ["LEONAID_CI_FIXTURE"] = str(fixture)
        self.addCleanup(os.environ.pop, "LEONAID_CI_FIXTURE", None)
        text = self.excerpt_of(f"Error: twenty said {key} is invalid\n")
        self.assertNotIn(key, text)
        self.assertIn("[REDACTED:TWENTY_INTEGRATION_API_KEY]", text)

    def test_leftover_credential_keyword_withholds_the_excerpt(self):
        text = self.excerpt_of('Error: rejected bearer "Abc123456xyz"\n')
        self.assertIn("withheld", text)
        self.assertNotIn("Abc123456xyz", text)
        # Ordinary prose about tokens is not withheld.
        text = self.excerpt_of("Error: token validation failed for invitation\n")
        self.assertIn("token validation failed", text)

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
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
