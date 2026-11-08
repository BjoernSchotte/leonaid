"""Process/lease checks; actual data reset semantics use shared_stack_live.py."""

import importlib.util
import re
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "shared_stack", Path(__file__).with_name("shared_stack.py")
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
ROOT = Path(__file__).resolve().parents[2]


class SharedStackTests(unittest.TestCase):
    def stack(self):
        stack = module.SharedStack(ROOT, "golden")
        self.addCleanup(stack.close)
        values = {
            "project": stack.project,
            "integration_key": "",
            "shared_root": str(ROOT),
            "shared_token": stack.token,
        }
        (stack.directory / "context.env").write_text(
            "".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items())
        )
        return stack

    def borrow(self, stack, token):
        return subprocess.run(
            [
                "/bin/sh",
                "-eu",
                "-c",
                'root=$1; proof=$2; shared_services=api; . "$root/tools/testing/borrow_stack.sh"',
                "test-borrow",
                str(ROOT),
                str(stack.directory),
            ],
            env=dict(
                os.environ,
                LEONAID_TEST_STACK=str(stack.directory),
                LEONAID_TEST_STACK_TOKEN=token,
            ),
            capture_output=True,
            text=True,
        )

    def test_active_leaf_excludes_parent_reset(self):
        stack = self.stack()
        (stack.directory / "in-use").mkdir()
        with self.assertRaises(FileExistsError):
            stack.prepare()
        self.assertFalse(stack.owned)
        self.assertTrue((stack.directory / "in-use").is_dir())

    def test_active_leaf_excludes_another_process_without_releasing_its_lease(self):
        stack = self.stack()
        (stack.directory / "in-use").mkdir()
        result = self.borrow(stack, stack.token)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already in use", result.stderr)
        self.assertTrue((stack.directory / "in-use").is_dir())

    def test_wrong_invocation_cannot_borrow_or_lock(self):
        stack = self.stack()
        result = self.borrow(stack, "another-invocation")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("different invocation", result.stderr)
        self.assertFalse((stack.directory / "in-use").exists())

    def test_parallel_runs_have_separate_projects_and_leases(self):
        first, second = self.stack(), self.stack()
        self.assertNotEqual(first.project, second.project)
        self.assertNotEqual(first.directory, second.directory)
        self.assertNotEqual(first.token, second.token)
        (first.directory / "in-use").mkdir()
        subprocess.run(["mkdir", str(second.directory / "in-use")], check=True)
        self.assertTrue((first.directory / "in-use").is_dir())
        self.assertTrue((second.directory / "in-use").is_dir())


class VerifiedResetTests(unittest.TestCase):
    """The reset proves an empty fixture: digests must match the first restore."""

    def stack(self, kind="survey"):
        stack = module.SharedStack(ROOT, kind)
        self.addCleanup(shutil.rmtree, stack.directory, True)
        stack.volumes = [
            f"{stack.project}_core-postgres-data",
            f"{stack.project}_rustfs-data",
            f"{stack.project}_twenty-postgres-data",
        ]
        return stack

    def test_first_restore_records_and_a_clean_reset_matches(self):
        stack = self.stack()
        stack.verify_digests("0 " + "a" * 64 + "\n1 " + "b" * 64 + "\n2 " + "c" * 64)
        stack.preserving = True
        stack.verify_digests("0 " + "a" * 64 + "\n1 " + "b" * 64)

    def test_leftover_state_refuses_the_next_check(self):
        stack = self.stack()
        stack.verify_digests("0 " + "a" * 64 + "\n1 " + "b" * 64 + "\n2 " + "c" * 64)
        stack.preserving = True
        with self.assertRaisesRegex(RuntimeError, "left state behind.*rustfs-data"):
            stack.verify_digests("0 " + "a" * 64 + "\n1 " + "d" * 64)

    def test_a_missing_or_extra_volume_digest_is_refused(self):
        stack = self.stack()
        with self.assertRaisesRegex(RuntimeError, "digest covers"):
            stack.verify_digests("0 " + "a" * 64)
        stack.verify_digests("0 " + "a" * 64 + "\n1 " + "b" * 64 + "\n2 " + "c" * 64)
        stack.preserving = True
        # A preserved Twenty volume must not be restored or compared.
        with self.assertRaisesRegex(RuntimeError, "digest covers"):
            stack.verify_digests(
                "0 " + "a" * 64 + "\n1 " + "b" * 64 + "\n2 " + "c" * 64
            )
        with self.assertRaisesRegex(RuntimeError, "Unreadable"):
            stack.verify_digests("7 " + "a" * 64)

    def test_only_survey_stacks_preserve_twenty(self):
        survey, golden = self.stack(), self.stack("golden")
        self.assertIn("twenty-server", survey.preserved_services)
        self.assertEqual(golden.preserved_services, frozenset())
        self.assertEqual(golden.preserved_volumes, frozenset())

    def test_preserved_containers_survive_quiesce_only_while_preserving(self):
        stack = self.stack()
        rows = "c1 api\nc2 twenty-server\nc3 twenty-postgres\nc4 \n"
        stack.call = lambda args, capture=False: rows
        self.assertEqual(stack.active_containers(), ["c1", "c2", "c3", "c4"])
        stack.preserving = True
        self.assertEqual(stack.active_containers(), ["c1", "c4"])

    def test_survey_fixture_never_gets_the_crm_key(self):
        fake = type(sys)("ci_fixture")
        fake.is_synthetic = lambda root, text: True
        fake.validate = lambda root, directory: None
        original = sys.modules.get("ci_fixture")
        sys.modules["ci_fixture"] = fake
        self.addCleanup(
            lambda: sys.modules.pop("ci_fixture")
            if original is None
            else sys.modules.__setitem__("ci_fixture", original)
        )
        for kind, expected in (("survey", ""), ("golden", "k" * 40)):
            stack = self.stack(kind)
            stack.fixture_metadata = {
                "integrationKey": "k" * 40,
                "volumes": ["core-postgres-data"],
                "files": [],
            }
            stack.root = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, stack.root)
            (stack.root / ".env.local").write_text("")
            stack.call = lambda args, capture=False: ""
            stack.inventory = lambda resource, s=stack: [
                s.project + "_core-postgres-data"
            ]
            stack.copy_volumes = lambda mode: None
            stack.import_fixture(Path("/nonexistent"))
            self.assertEqual(stack.env["TWENTY_INTEGRATION_API_KEY"], expected, kind)


class SurveyTwentyIsolationTests(unittest.TestCase):
    """Twenty is not reset between survey checks, so no survey check may use it."""

    PATTERN = re.compile(r"twenty|crm|:3000|/rest/|/graphql", re.IGNORECASE)
    # Credential redaction only (it names the key to remove it from logs).
    # Subnet allocation names every Compose network, crm-data included.
    ALLOWED = {
        "tools/surveys/ci_failure_excerpt.py",
        "tools/surveys/ci_failure_excerpt_test.py",
        "tools/surveys/network_override.py",
    }

    def test_no_survey_check_or_spec_references_twenty(self):
        paths = sorted(
            [*ROOT.glob("tools/surveys/*"), *ROOT.glob("tests/e2e/surveys-*.spec.mjs")]
        )
        self.assertTrue(paths)
        offenders = [
            f"{path.relative_to(ROOT)}:{number}"
            for path in paths
            if path.is_file() and str(path.relative_to(ROOT)) not in self.ALLOWED
            for number, line in enumerate(path.read_text().splitlines(), 1)
            if self.PATTERN.search(line)
        ]
        self.assertEqual(offenders, [])


class LeafSequenceTests(unittest.TestCase):
    """main(): every leaf gets prepare(); --keep-going runs leaves after a failure."""

    def run_main(self, *arguments):
        prepared = []

        class FakeStack:
            def __init__(self, root, kind):
                self.kind = kind

            def prepare(self):
                prepared.append(self.kind)
                return {}

            def close(self):
                prepared.append("closed")

        directory = Path(tempfile.mkdtemp(prefix="leonaid-shared-stack-test-"))
        self.addCleanup(shutil.rmtree, directory)
        failing = directory / "failing.sh"
        failing.write_text("exit 3\n")
        marker = directory / "second-ran"
        passing = directory / "passing.sh"
        passing.write_text(f"touch {shlex.quote(str(marker))}\n")
        original_stack, original_argv = module.SharedStack, sys.argv
        module.SharedStack = FakeStack
        sys.argv = ["shared_stack.py", *arguments, "core", str(failing), str(passing)]
        try:
            code = module.main()
        finally:
            module.SharedStack, sys.argv = original_stack, original_argv
        return code, marker.exists(), prepared

    def test_first_failure_stops_by_default(self):
        code, second_ran, prepared = self.run_main()
        self.assertEqual(code, 3)
        self.assertFalse(second_ran)
        self.assertEqual(prepared, ["core", "closed"])

    def test_keep_going_runs_every_leaf_and_keeps_the_failure(self):
        code, second_ran, prepared = self.run_main("--keep-going")
        self.assertEqual(code, 3)
        self.assertTrue(second_ran)
        self.assertEqual(prepared, ["core", "core", "closed"])


if __name__ == "__main__":
    unittest.main()
