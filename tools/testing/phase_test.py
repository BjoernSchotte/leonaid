"""Exercise real shell failures: timing must not turn a failed reset green."""

from pathlib import Path
import subprocess
import unittest


class PhaseTests(unittest.TestCase):
    def run_shell(self, script):
        return subprocess.run(
            [
                "sh",
                "-eu",
                "-c",
                '. "$1"; ' + script,
                "phase-test",
                str(Path(__file__).with_name("phase.sh").resolve()),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_function_stops_at_first_failure(self):
        result = self.run_shell(
            "operation() { false; echo SHOULD_NOT_RUN; }; phase reset-seed operation; echo ALSO_NOT_RUN"
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("NOT_RUN", result.stdout)
        self.assertRegex(result.stdout, r"test-phase: reset-seed seconds=\d+ exit=1")

    def test_nested_timers_keep_their_labels_and_failure(self):
        result = self.run_shell(
            'operation() { phase inner sh -c "exit 7"; echo SHOULD_NOT_RUN; }; phase outer operation'
        )
        self.assertEqual(result.returncode, 7)
        self.assertNotIn("NOT_RUN", result.stdout)
        self.assertRegex(result.stdout, r"test-phase: inner seconds=\d+ exit=7")
        self.assertRegex(result.stdout, r"test-phase: outer seconds=\d+ exit=7")

    def test_success_does_not_print_command_arguments(self):
        result = self.run_shell('phase success sh -c "exit 0" PRIVATE_CANARY')
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("PRIVATE_CANARY", result.stdout)
        self.assertRegex(result.stdout, r"test-phase: success seconds=\d+ exit=0")


if __name__ == "__main__":
    unittest.main()
