#!/usr/bin/env python3
"""`./leonaid check` runs every Python self-test and check that CI runs.

CI's tools/ci/lint-types.sh and tools/ci/security.sh run Python scripts in
pinned images and on the runner. Each executed call must also be executed by
the local check (tools/dx/stdlib_checks.sh or a check group in ./leonaid), and
every tools/ci/*_test.py must run in both, so a test only CI runs cannot break
main unnoticed again. Calls are matched as executed commands; mentions in
comments do not count.
"""

from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parents[2])
CI_SCRIPTS = ("tools/ci/lint-types.sh", "tools/ci/security.sh")
LOCAL_SCRIPTS = ("tools/dx/stdlib_checks.sh",)
# CI-only on purpose, with the reason.
CI_ONLY = {
    # Starts a full stack for the security leaf; covered by the test suites.
    "tools/testing/shared_stack.py": "stack runner, not a self-test",
}
# `python[3] [-I] <script>` with the script as /workspace/…, "$root/…", "$w/…" or
# a repository-relative path.
CALL = re.compile(
    r"""(?<![\w/.-])python3?\s+(?:-I\s+)?(?:"?\$(?:root|w)/|/workspace/)?([\w.-]+(?:/[\w.-]+)+\.py)\b"""
)


def executed_calls(text: str) -> set[str]:
    """Repository-relative Python scripts a shell text executes."""
    text = re.sub(r"\\\n\s*", " ", text)  # Line continuations.
    calls = set()
    for line in text.splitlines():
        command = re.sub(r"(^|\s)#.*$", "", line)  # Comments are not calls.
        calls |= set(CALL.findall(command))
    return calls


def ci_calls(root: Path = ROOT) -> set[str]:
    return set().union(
        *(
            executed_calls((root / name).read_text(encoding="utf-8"))
            for name in CI_SCRIPTS
        )
    )


def local_calls(root: Path = ROOT) -> set[str]:
    cli = (root / "leonaid").read_text(encoding="utf-8")
    start = cli.index("check_stdlib() {")
    end = cli.index("\ncheck_all() {")
    texts = [cli[start:end]]
    texts += [(root / name).read_text(encoding="utf-8") for name in LOCAL_SCRIPTS]
    return set().union(*(executed_calls(text) for text in texts))


class CheckParityTests(unittest.TestCase):
    def test_every_ci_python_check_runs_locally(self) -> None:
        calls = ci_calls()
        self.assertGreater(len(calls), 20, "CI scripts not parsed")
        missing = sorted(calls - local_calls() - set(CI_ONLY))
        self.assertEqual(missing, [], "CI runs these, ./leonaid check does not")

    def test_every_ci_self_test_runs_in_ci_and_locally(self) -> None:
        calls, local = ci_calls(), local_calls()
        for path in sorted((ROOT / "tools/ci").glob("*_test.py")):
            name = path.relative_to(ROOT).as_posix()
            with self.subTest(name=name):
                self.assertIn(name, calls, "not run by CI")
                self.assertIn(name, local, "not run by ./leonaid check")

    def test_allowlist_is_current(self) -> None:
        for path in CI_ONLY:
            self.assertIn(path, ci_calls(), f"{path}: drop it from CI_ONLY")


class CallFormTests(unittest.TestCase):
    """Mutations: every call form CI uses is found; mentions are not calls."""

    def test_each_call_form_is_found(self) -> None:
        for line, expected in (
            ("  python /workspace/tools/ci/a_test.py /workspace", "tools/ci/a_test.py"),
            (
                "  python3 /workspace/tools/release/release_test.py",
                "tools/release/release_test.py",
            ),
            ('python3 "$root/tools/testing/b_test.py"', "tools/testing/b_test.py"),
            ('check x python "$w/tools/ci/c_test.py" "$w"', "tools/ci/c_test.py"),
            (
                "  python tools/openapi/generate.py --root /workspace",
                "tools/openapi/generate.py",
            ),
            ("run_python env X=1 python tools/x/y.py", "tools/x/y.py"),
            (
                '"$IMAGE" \\\n  python /workspace/tools/ci/d_test.py',
                "tools/ci/d_test.py",
            ),
        ):
            with self.subTest(line=line):
                self.assertEqual(executed_calls(line), {expected})

    def test_comments_and_other_tools_are_not_calls(self) -> None:
        for line in (
            "# python /workspace/tools/ci/a_test.py",
            "  # Runs python3 tools/x/y.py in CI only.",
            "ruff check tools/testing/phase_test.py tools/ci/a_test.py",
            "mypy tools/dx/check_parity_test.py",
        ):
            with self.subTest(line=line):
                self.assertEqual(executed_calls(line), set())

    def test_a_ci_call_missing_locally_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (*CI_SCRIPTS, *LOCAL_SCRIPTS, "leonaid"):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / CI_SCRIPTS[0]).write_text(
                "run_python uv run python tools/a/one.py\n"
                'docker run "$IMAGE" python3 /workspace/tools/a/two.py\n'
            )
            (root / CI_SCRIPTS[1]).write_text('python3 "$root/tools/a/three.py"\n')
            (root / LOCAL_SCRIPTS[0]).write_text(
                'check one python "$w/tools/a/one.py"\n'
                "# python3 /workspace/tools/a/two.py (only mentioned)\n"
            )
            (root / "leonaid").write_text(
                'check_stdlib() {\n  python3 "$root/tools/a/three.py"\n}\n'
                "\ncheck_all() {\n  python3 tools/a/two.py\n}\n"
            )
            # two.py runs only outside the check section and in a comment.
            self.assertEqual(ci_calls(root) - local_calls(root), {"tools/a/two.py"})


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
