"""Parallel test stacks: memory gate, override, slot locks and leaf scheduling.

Real files, flock and processes; the stacks are minimal in-process stand-ins
for the scheduling test (every CI shard exercises the real reset).
"""

import contextlib
import fcntl
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parallel_stacks
import shared_stack


class WantedTests(unittest.TestCase):
    def meminfo(self, gigabytes):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        path = directory / "meminfo"
        path.write_text(
            f"MemTotal: 1 kB\nMemAvailable: {int(gigabytes * 1024 * 1024)} kB\n"
        )
        return str(path)

    def test_two_stacks_only_with_enough_memory(self):
        self.assertEqual(
            parallel_stacks.wanted(23, {"LEONAID_MEMINFO": self.meminfo(20)})[0], 2
        )
        self.assertEqual(
            parallel_stacks.wanted(23, {"LEONAID_MEMINFO": self.meminfo(13.9)})[0], 1
        )
        self.assertEqual(
            parallel_stacks.wanted(23, {"LEONAID_MEMINFO": "/nonexistent"})[0], 1
        )
        # Never more stacks than leaves.
        self.assertEqual(
            parallel_stacks.wanted(1, {"LEONAID_MEMINFO": self.meminfo(64)})[0], 1
        )

    def test_ci_uses_one_stack_unless_asked(self):
        environ = {"LEONAID_MEMINFO": self.meminfo(64), "CI": "true"}
        self.assertEqual(parallel_stacks.wanted(23, environ)[0], 1)
        environ["LEONAID_TEST_STACKS"] = "2"
        self.assertEqual(parallel_stacks.wanted(23, environ)[0], 2)

    def test_explicit_count_overrides_the_memory_gate(self):
        environ = {"LEONAID_MEMINFO": self.meminfo(2), "LEONAID_TEST_STACKS": "3"}
        self.assertEqual(parallel_stacks.wanted(23, environ)[0], 3)
        environ["LEONAID_TEST_STACKS"] = "1"
        self.assertEqual(parallel_stacks.wanted(23, environ)[0], 1)
        environ["LEONAID_TEST_STACKS"] = "0"
        with self.assertRaises(ValueError):
            parallel_stacks.wanted(23, environ)


class SlotTests(unittest.TestCase):
    def test_additional_stacks_take_only_free_slots(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        # Another process (e.g. the slot wrapper of another suite) holds slot 1.
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import fcntl,sys,time; f=open(sys.argv[1],'a'); "
                "fcntl.flock(f, fcntl.LOCK_EX); print('ok', flush=True); time.sleep(30)",
                str(directory / "slot-1.lock"),
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), "ok")
        environ = {
            "LEONAID_STACK_SLOTS_DIR": str(directory),
            "LEONAID_STACK_SLOTS": "2",
        }
        held = parallel_stacks.take_slots(2, environ)
        self.addCleanup(lambda: [lock.close() for lock in held])
        self.assertEqual([Path(lock.name).name for lock in held], ["slot-2.lock"])
        # The held slot is really locked for everyone else.
        with (directory / "slot-2.lock").open("a") as other:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(parallel_stacks.take_slots(1, {}), [])


class SchedulingTests(unittest.TestCase):
    class Stack:
        def __init__(self, name, broken=False, delay=0.0):
            self.project = name
            self.prepared = 0
            self.broken = broken
            self.delay = delay

        def prepare(self):
            self.prepared += 1
            time.sleep(self.delay)
            if self.broken:
                raise RuntimeError("restore failed")
            return {}

    def leaves(self, count, failing=None, body=""):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        self.marks = directory / "started"
        self.marks.mkdir()
        scripts = []
        for index in range(count):
            path = directory / f"leaf-{index}.sh"
            code = 3 if index == failing else 0
            path.write_text(
                f"touch {self.marks}/{index}\n{body}echo leaf {index}\n"
                f"sleep 0.3\nexit {code}\n"
            )
            scripts.append(str(path))
        return scripts

    def runner(self, stacks, scripts, keep_going=False):
        return shared_stack.LeafRunner(
            Path("/"), stacks, scripts, keep_going, threading.Lock()
        )

    def test_every_leaf_runs_once_spread_over_the_stacks(self):
        stacks = [self.Stack("a"), self.Stack("b")]
        scripts = self.leaves(6)
        results = self.runner(stacks, scripts).run()
        self.assertEqual(sorted(script for script, _ in results), sorted(scripts))
        self.assertTrue(all(code == 0 for _, code in results))
        self.assertEqual(sum(stack.prepared for stack in stacks), 6)
        self.assertTrue(all(stack.prepared for stack in stacks))

    def test_a_failure_stops_new_leaves_unless_keep_going(self):
        scripts = self.leaves(6, failing=0)
        results = self.runner([self.Stack("a"), self.Stack("b")], scripts).run()
        self.assertIn((scripts[0], 3), results)
        self.assertLess(len(results), 6)
        results = self.runner(
            [self.Stack("a"), self.Stack("b")], scripts, keep_going=True
        ).run()
        self.assertEqual(len(results), 6)

    def test_cancel_starts_no_leaf_and_returns_after_all_workers(self):
        for stacks in (
            [self.Stack("a", delay=0.5)],
            [self.Stack("a", delay=0.5), self.Stack("b", delay=0.5)],
        ):
            scripts = self.leaves(6, body="sleep 5\n")
            runner = self.runner(stacks, scripts, keep_going=True)
            # Cancel while every worker is still inside prepare().
            timer = threading.Timer(0.2, runner.cancel)
            timer.start()
            begin = time.monotonic()
            runner.run()
            self.assertLess(time.monotonic() - begin, 3)
            self.assertEqual(list(self.marks.iterdir()), [])
            # The Timer thread itself may still be returning from cancel();
            # only the runner's workers must be gone.
            timer.join(timeout=5)
            self.assertEqual(threading.active_count(), 1)

    def test_cancel_terminates_running_leaves(self):
        scripts = self.leaves(4, body="sleep 30\n")
        runner = self.runner([self.Stack("a"), self.Stack("b")], scripts, True)
        threading.Timer(1.0, runner.cancel).start()
        begin = time.monotonic()
        results = runner.run()
        self.assertLess(time.monotonic() - begin, 10)
        self.assertEqual(len(list(self.marks.iterdir())), 2)
        self.assertTrue(all(code != 0 for _, code in results))
        self.assertTrue(all(child.poll() is not None for child in runner.children))

    def test_undecodable_output_never_drops_a_failure(self):
        scripts = self.leaves(2, failing=0, body="printf '\\377\\376'\n")
        console = io.StringIO()
        with contextlib.redirect_stdout(console):
            results = self.runner(
                [self.Stack("a"), self.Stack("b")], scripts, True
            ).run()
        self.assertIn((scripts[0], 3), results)
        self.assertEqual(len(results), 2)
        # The console (and a CI log of it) only ever gets valid UTF-8.
        self.assertIn("\ufffd", console.getvalue())
        console.getvalue().encode("utf-8")

    def test_a_broken_stack_is_retired_and_its_leaf_requeued(self):
        scripts = self.leaves(5)
        runner = self.runner(
            [self.Stack("a"), self.Stack("broken", broken=True)], scripts, True
        )
        results = runner.run()
        self.assertEqual(sorted(script for script, _ in results), sorted(scripts))
        self.assertTrue(all(code == 0 for _, code in results))
        self.assertEqual(len(runner.problems), 1)
        # Without any healthy stack, every leaf fails instead of vanishing.
        runner = self.runner([self.Stack("broken", broken=True)], scripts, True)
        results = runner.run()
        self.assertEqual(len(results), 5)
        self.assertTrue(all(code == 1 for _, code in results))

    def test_a_late_broken_stack_still_finds_a_healthy_worker(self):
        scripts = self.leaves(2)
        runner = self.runner(
            [self.Stack("a"), self.Stack("broken", broken=True, delay=1.5)],
            scripts,
            True,
        )
        results = runner.run()
        self.assertEqual(sorted(results), sorted((s, 0) for s in scripts))
        self.assertEqual(runner.problems, ["stack broken failed to reset"])

    def test_a_leaf_ignoring_sigterm_is_killed_after_the_grace_period(self):
        scripts = self.leaves(1, body="trap '' TERM\nsleep 60\n")
        original = shared_stack.KILL_AFTER_SECONDS
        shared_stack.KILL_AFTER_SECONDS = 1
        self.addCleanup(setattr, shared_stack, "KILL_AFTER_SECONDS", original)
        runner = self.runner([self.Stack("a")], scripts, True)
        threading.Timer(0.5, runner.cancel).start()
        begin = time.monotonic()
        results = runner.run()
        self.assertLess(time.monotonic() - begin, 10)
        self.assertEqual(results, [(scripts[0], 137)])

    def test_signal_exit_codes_follow_the_shell(self):
        self.assertEqual(shared_stack.exit_status(-15), 143)
        self.assertEqual(shared_stack.exit_status(3), 3)


if __name__ == "__main__":
    unittest.main()
