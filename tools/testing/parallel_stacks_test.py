"""Parallel test stacks: memory gate, override, slot locks and leaf scheduling.

Real files, flock and processes; the stacks are minimal in-process stand-ins
for the scheduling test (their reset is covered by shared_stack_live.py).
"""

import fcntl
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
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
        def __init__(self, name):
            self.project = name
            self.prepared = 0

        def prepare(self):
            self.prepared += 1
            return {}

    def leaves(self, count, failing=None):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        scripts = []
        for index in range(count):
            path = directory / f"leaf-{index}.sh"
            code = 3 if index == failing else 0
            path.write_text(f"echo leaf {index}\nsleep 0.3\nexit {code}\n")
            scripts.append(str(path))
        return scripts

    def run_leaves(self, stacks, scripts, keep_going=False):
        return shared_stack.run_leaves(
            Path("/"), stacks, scripts, keep_going, threading.Lock(), set()
        )

    def test_every_leaf_runs_once_spread_over_the_stacks(self):
        stacks = [self.Stack("a"), self.Stack("b")]
        scripts = self.leaves(6)
        results = self.run_leaves(stacks, scripts)
        self.assertEqual(sorted(script for script, _ in results), sorted(scripts))
        self.assertTrue(all(code == 0 for _, code in results))
        self.assertEqual(sum(stack.prepared for stack in stacks), 6)
        self.assertTrue(all(stack.prepared for stack in stacks))

    def test_a_failure_stops_new_leaves_unless_keep_going(self):
        scripts = self.leaves(6, failing=0)
        results = self.run_leaves([self.Stack("a"), self.Stack("b")], scripts)
        self.assertIn((scripts[0], 3), results)
        self.assertLess(len(results), 6)
        results = self.run_leaves(
            [self.Stack("a"), self.Stack("b")], scripts, keep_going=True
        )
        self.assertEqual(len(results), 6)


if __name__ == "__main__":
    unittest.main()
