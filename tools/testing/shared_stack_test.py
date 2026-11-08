"""Process/lease and reset-digest checks; every survey shard exercises the real reset."""

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

    ALL = {"0", "1", "2"}
    CORE = {"0", "1"}

    def test_first_restore_records_and_a_clean_reset_matches(self):
        stack = self.stack()
        stack.verify_digests(
            "0 " + "a" * 64 + "\n1 " + "b" * 64 + "\n2 " + "c" * 64, self.ALL
        )
        stack.preserving = True
        stack.verify_digests("0 " + "a" * 64 + "\n1 " + "b" * 64, self.CORE)

    def test_leftover_state_refuses_the_next_check(self):
        stack = self.stack()
        stack.verify_digests(
            "0 " + "a" * 64 + "\n1 " + "b" * 64 + "\n2 " + "c" * 64, self.ALL
        )
        stack.preserving = True
        with self.assertRaisesRegex(RuntimeError, "left state behind.*rustfs-data"):
            stack.verify_digests("0 " + "a" * 64 + "\n1 " + "d" * 64, self.CORE)

    def test_a_missing_volume_digest_is_refused(self):
        stack = self.stack()
        with self.assertRaisesRegex(RuntimeError, "digest covers"):
            stack.verify_digests("0 " + "a" * 64, self.CORE)


class SurveyTwentyIsolationTests(unittest.TestCase):
    """Twenty is not reset between survey checks, so no survey check may use it."""

    PATTERN = re.compile(r"twenty|crm|:3000|/rest/|/graphql", re.IGNORECASE)
    # Subnet allocation names every Compose network, crm-data included.
    ALLOWED = {"tools/surveys/network_override.py"}

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
