#!/usr/bin/env python3
"""`./leonaid check` runs every Python self-test and check that CI runs.

CI's tools/ci/lint-types.sh and tools/ci/security.sh run Python scripts in the
pinned Python image (`python /workspace/<path>`) and on the runner
(`python3 "$root/<path>"`). Each of them must also run in the local check
(tools/dx/stdlib_checks.sh or a check group in ./leonaid), and every
tools/ci/*_test.py must run in both, so a test that only CI runs cannot
break main unnoticed again.
"""

from pathlib import Path
import re
import sys
import unittest

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parents[2])
CI_SCRIPTS = ("tools/ci/lint-types.sh", "tools/ci/security.sh")
# CI-only on purpose, with the reason.
CI_ONLY = {
    # Starts a full stack for the security leaf; covered by the test suites.
    "tools/testing/shared_stack.py": "stack runner, not a self-test",
}
INVOCATION = re.compile(
    r"""(?:\bpython\s+/workspace/|\bpython3\s+"\$root/)([\w./-]+\.py)"""
)


def ci_invocations() -> set[str]:
    found = set()
    for name in CI_SCRIPTS:
        text = (ROOT / name).read_text(encoding="utf-8")
        # Line continuations: "python \\\n  /workspace/x.py".
        text = re.sub(r"\\\n\s*", " ", text)
        found |= set(INVOCATION.findall(text))
    return found


def local_check_text() -> str:
    cli = (ROOT / "leonaid").read_text(encoding="utf-8")
    start = cli.index("check_stdlib() {")
    end = cli.index("\ncheck_all() {")
    return (
        cli[start:end] + (ROOT / "tools/dx/stdlib_checks.sh").read_text(encoding="utf-8")
    )


class CheckParityTests(unittest.TestCase):
    def test_every_ci_python_check_runs_locally(self):
        local = local_check_text()
        invocations = ci_invocations()
        self.assertGreater(len(invocations), 20, "CI scripts not parsed")
        missing = sorted(
            path for path in invocations if path not in CI_ONLY and path not in local
        )
        self.assertEqual(missing, [], "CI runs these, ./leonaid check does not")

    def test_every_ci_self_test_runs_in_ci_and_locally(self):
        local = local_check_text()
        invocations = ci_invocations()
        for path in sorted((ROOT / "tools/ci").glob("*_test.py")):
            name = path.relative_to(ROOT).as_posix()
            with self.subTest(name=name):
                self.assertIn(name, invocations, "not run by CI")
                self.assertIn(name, local, "not run by ./leonaid check")

    def test_allowlist_is_current(self):
        invocations = ci_invocations()
        for path in CI_ONLY:
            self.assertIn(path, invocations, f"{path}: drop it from CI_ONLY")


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
