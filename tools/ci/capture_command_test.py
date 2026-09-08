"""Real subprocess output capture, without replacing commands or Docker APIs."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = (
    Path(sys.argv.pop(1)) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
)
sys.path.insert(0, str(ROOT))

from tools.ci.sanitize_artifacts import SanitizationFailure, sanitize_text  # noqa: E402


class CaptureTests(unittest.TestCase):
    def capture(self, source: str) -> tuple[subprocess.CompletedProcess[bytes], bytes]:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "command.log"
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "tools/ci/capture-command.sh"),
                    str(log),
                    sys.executable,
                    "-c",
                    source,
                ],
                capture_output=True,
                timeout=20,
            )
            return result, log.read_bytes()

    def test_stderr_between_stdout_character_bytes(self) -> None:
        source = (
            "import os; os.write(1,b'\\xe2'); "
            "os.write(2,b'version notice\\n'); os.write(1,b'\\x94\\x80\\n')"
        )
        merged = subprocess.run(
            [sys.executable, "-c", source],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=20,
        )
        with self.assertRaises(UnicodeDecodeError):
            merged.stdout.decode("utf-8")
        result, log = self.capture(source)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "─\n".encode())
        self.assertEqual(result.stderr, b"version notice\n")
        self.assertIn("─\n", log.decode("utf-8"))
        self.assertIn(b"--- stderr ---\nversion notice", log)
        sanitize_text(log, label="command.log", suffix=".log", secrets={})

    def test_child_failure_is_preserved(self) -> None:
        result, log = self.capture("import sys; print('failed'); sys.exit(23)")
        self.assertEqual(result.returncode, 23)
        self.assertIn(b"failed", log)

    def test_large_both_streams_are_drained(self) -> None:
        result, log = self.capture(
            "import os; os.write(1,b'a'*1048576); os.write(2,b'b'*1048576)"
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"a" * 1048576, log)
        self.assertIn(b"b" * 1048576, log)

    def test_invalid_original_bytes_still_fail_sanitization(self) -> None:
        result, log = self.capture("import os; os.write(1,b'\\xff')")
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"\xff", log)
        with self.assertRaises(SanitizationFailure):
            sanitize_text(log, label="command.log", suffix=".log", secrets={})

    def test_unwritable_log_is_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "tools/ci/capture-command.sh"),
                    directory,
                    sys.executable,
                    "-c",
                    "pass",
                ],
                capture_output=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 74)


if __name__ == "__main__":
    unittest.main()
