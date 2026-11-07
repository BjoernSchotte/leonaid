#!/usr/bin/env python3
"""The pre-push hook runs check-fast, blocks a failing push, honours --no-verify."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HOOK = Path(__file__).resolve().with_name("pre-push")


class PrePushHookTests(unittest.TestCase):
    def repository(self, directory: Path, cli: str) -> Path:
        remote = directory / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        work = directory / "work"
        subprocess.run(["git", "init", "-q", str(work)], check=True)
        (work / "leonaid").write_text(cli)
        (work / "leonaid").chmod(0o755)
        git = ["git", "-C", str(work), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "add", "leonaid"], check=True)
        subprocess.run([*git, "commit", "-qm", "init"], check=True)
        hooks = work / ".git/hooks"
        shutil.copy(HOOK, hooks / "pre-push")
        (hooks / "pre-push").chmod(0o755)
        return work

    def push(self, work: Path, *options: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(work), "push", *options, "../remote.git", "HEAD:main"],
            capture_output=True,
            text=True,
        )

    def test_failing_check_blocks_the_push_unless_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "ran"
            work = self.repository(
                Path(directory),
                "#!/bin/sh\ncase $1 in\n  check-fast) touch "
                f"{marker}; exit 1 ;;\nesac\n",
            )
            result = self.push(work)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(marker.exists())
            self.assertIn("check-fast", result.stderr)
            marker.unlink()
            self.assertEqual(self.push(work, "--no-verify").returncode, 0)
            self.assertFalse(marker.exists())

    def test_passing_check_and_older_branches_push(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = self.repository(
                Path(directory),
                "#!/bin/sh\ncase $1 in\n  check-fast) exit 0 ;;\nesac\n",
            )
            self.assertEqual(self.push(work).returncode, 0)
        with tempfile.TemporaryDirectory() as directory:
            # A CLI without check-fast (an older branch): nothing to run.
            work = self.repository(Path(directory), "#!/bin/sh\nexit 1\n")
            self.assertEqual(self.push(work).returncode, 0)


if __name__ == "__main__":
    unittest.main()
