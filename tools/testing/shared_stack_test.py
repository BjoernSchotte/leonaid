"""Process/lease checks; actual data reset semantics use shared_stack_live.py."""

import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
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


if __name__ == "__main__":
    unittest.main()
