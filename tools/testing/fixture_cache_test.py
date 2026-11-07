"""Host fixture cache: build once under a lock, reuse, prune, never share in use.

Real files, archives, processes and flock; no Docker. The producer writes a
real (tiny) fixture in the CI format, exactly what `ci_fixture.validate` checks.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ci_fixture import (
    environment,
    is_synthetic,
    is_synthetic_subset,
    key,
    write_environment,
)
from fixture_cache import FixtureCache

ROOT = Path(__file__).resolve().parents[2]
KEY = key(ROOT)


def produce(target: Path, *, fixture_key: str = KEY) -> None:
    target.mkdir(mode=0o700)
    state = target / "state"
    state.write_text("synthetic database fixture")
    archive = target / "volume-0.tar"
    with tarfile.open(archive, "w") as output:
        output.add(state, arcname="state")
    state.unlink()
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "key": fixture_key,
                "syntheticOnly": True,
                "integrationKey": "",
                "volumes": ["core-postgres-data"],
                "files": {
                    "volume-0.tar": hashlib.sha256(archive.read_bytes()).hexdigest()
                },
            }
        )
    )


class FixtureCacheTests(unittest.TestCase):
    def cache(self, **options):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(directory)])
        options.setdefault("min_age", 0)
        cache = FixtureCache(directory / "fixtures", **options)
        self.addCleanup(lambda: [cache.release(k) for k in list(cache.held)])
        return cache

    def test_builds_once_then_reuses(self):
        cache = self.cache()
        builds = []

        def build(target):
            builds.append(target)
            produce(target)

        entry, metadata = cache.acquire(ROOT, KEY, build)
        self.assertEqual(metadata["key"], KEY)
        cache.release(KEY)
        self.assertEqual(cache.acquire(ROOT, KEY, build)[0], entry)
        self.assertEqual(len(builds), 1)
        self.assertEqual(entry.stat().st_mode & 0o777, 0o700)
        self.assertFalse(list(cache.directory.glob(".build-*")))

    def test_corrupt_entry_is_rebuilt(self):
        cache = self.cache()
        entry, _ = cache.acquire(ROOT, KEY, produce)
        cache.release(KEY)
        with (entry / "volume-0.tar").open("ab") as output:
            output.write(b"changed")
        builds = []
        cache.acquire(ROOT, KEY, lambda target: (builds.append(1), produce(target)))
        self.assertEqual(builds, [1])

    def test_failed_build_leaves_no_entry(self):
        cache = self.cache()

        def broken(target):
            target.mkdir()
            raise RuntimeError("setup failed")

        with self.assertRaisesRegex(RuntimeError, "setup failed"):
            cache.acquire(ROOT, KEY, broken)
        self.assertFalse((cache.directory / KEY).exists())
        self.assertFalse(list(cache.directory.glob(".build-*")))

    def test_concurrent_checkout_waits_for_the_builder(self):
        cache = self.cache()
        # Another process holds the build lock and produces the entry.
        script = (
            "import fcntl,sys,time\n"
            "sys.path.insert(0, sys.argv[3])\n"
            "from fixture_cache_test import produce\n"
            "from pathlib import Path\n"
            "lock = open(sys.argv[1] + '.lock', 'a')\n"
            "fcntl.flock(lock, fcntl.LOCK_EX)\n"
            "print('locked', flush=True)\n"
            "time.sleep(1)\n"
            "produce(Path(sys.argv[1]), fixture_key=sys.argv[2])\n"
        )
        builder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(cache.directory / KEY),
                KEY,
                str(Path(__file__).resolve().parent),
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(builder.stdout.readline().strip(), "locked")
        builds = []
        entry, _ = cache.acquire(ROOT, KEY, lambda target: builds.append(target))
        self.assertEqual(builder.wait(), 0)
        builder.stdout.close()
        self.assertEqual(builds, [])
        self.assertTrue((entry / "manifest.json").is_file())

    def test_prune_keeps_recent_and_in_use_entries(self):
        cache = self.cache(keep=1)
        old = [format(n, "064x") for n in (1, 2)]
        for index, name in enumerate(old):
            (cache.directory / name).mkdir()
            stamp = time.time() - 1000 * (index + 1)
            os.utime(cache.directory / name, (stamp, stamp))
        # The oldest entry is being imported by another process.
        busy = (cache.directory / f"{old[1]}.lock").open("a")
        self.addCleanup(busy.close)
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import fcntl,sys,time; f=open(sys.argv[1],'a'); "
                "fcntl.flock(f, fcntl.LOCK_SH); print('ok', flush=True); time.sleep(30)",
                busy.name,
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        # Cleanups run last-in first-out: kill, then reap and close the pipe.
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), "ok")
        current, _ = cache.acquire(ROOT, KEY, produce)
        self.assertEqual(cache.prune(), [old[0]])
        self.assertTrue(current.is_dir())
        self.assertTrue((cache.directory / old[1]).is_dir())
        self.assertFalse((cache.directory / old[0]).exists())
        # Interrupted build staging of a free key is removed as well.
        staging = cache.directory / f".build-{old[0]}-123"
        staging.mkdir()
        cache.prune()
        self.assertFalse(staging.exists())

    def test_recently_used_entries_survive_pruning(self):
        cache = self.cache(keep=1, min_age=3600)
        cache.acquire(ROOT, KEY, produce)
        recent = cache.directory / format(1, "064x")
        recent.mkdir()
        stamp = time.time() - 60
        os.utime(recent, (stamp, stamp))
        self.assertEqual(cache.prune(), [])
        self.assertTrue(recent.is_dir())

    def test_byte_bound_and_clear(self):
        cache = self.cache(keep=3, max_bytes=1500)
        names = [format(n, "064x") for n in (1, 2)]
        for index, name in enumerate(names):
            entry = cache.directory / name
            entry.mkdir()
            (entry / "volume-0.tar").write_bytes(b"x" * 1000)
            stamp = time.time() - 1000 * (index + 1)
            os.utime(entry, (stamp, stamp))
        # Two old 1000-byte entries exceed 1500 bytes: the older one goes.
        self.assertEqual(cache.prune(), [names[1]])
        cache.acquire(ROOT, KEY, produce)
        removed, busy = cache.clear()
        self.assertEqual(removed, [names[0]])
        self.assertEqual(busy, [KEY])
        cache.release(KEY)
        self.assertEqual(cache.clear(), ([KEY], []))

    def test_refuses_a_directory_others_can_write(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(directory)])
        directory.chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, "private"):
            FixtureCache(directory)


class SyntheticEnvironmentTests(unittest.TestCase):
    def test_host_ports_may_differ_secrets_may_not(self):
        local = environment(ROOT, "28090", "28091")
        self.assertTrue(is_synthetic(ROOT, local))
        self.assertTrue(is_synthetic(ROOT, environment(ROOT)))
        self.assertIn("LEONAID_HTTPS_PORT=28091\n", local)
        changed = local.replace("LEONAID_ENV=local", "LEONAID_ENV=local\nEXTRA=1")
        self.assertFalse(is_synthetic(ROOT, changed))
        name, value = next(
            line.split("=", 1)
            for line in local.splitlines()
            if "PASSWORD" in line and "=" in line
        )
        self.assertFalse(
            is_synthetic(ROOT, local.replace(f"{name}={value}", f"{name}=other"))
        )

    def test_settings_added_to_the_template_keep_a_file_synthetic(self):
        local = environment(ROOT, "28090", "28091")
        older = "\n".join(
            line for line in local.splitlines() if not line.startswith("LEONAID_ENV=")
        )
        self.assertFalse(is_synthetic(ROOT, older))
        self.assertTrue(is_synthetic_subset(ROOT, older))
        self.assertFalse(is_synthetic_subset(ROOT, older + "\nUNKNOWN_SETTING=1\n"))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / ".env.local"
            target.write_text(older)
            write_environment(ROOT, target, "28090", "28091")
            self.assertEqual(target.read_text(), local)

    def test_compose_project_is_per_checkout(self):
        local = environment(ROOT, "28090", "28091", "leonaid-wt-42")
        self.assertIn("LEONAID_COMPOSE_PROJECT=leonaid-wt-42\n", local)
        self.assertTrue(is_synthetic(ROOT, local))
        self.assertFalse(is_synthetic(ROOT, local.replace("leonaid-wt-42", "Bad")))
        # A synthetic file from before the setting existed is rewritten.
        older = local.replace("LEONAID_COMPOSE_PROJECT=leonaid-wt-42\n", "")
        self.assertTrue(is_synthetic_subset(ROOT, older))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / ".env.local"
            target.write_text(older)
            write_environment(ROOT, target, "28090", "28091", "leonaid-wt-42")
            self.assertEqual(target.read_text(), local)

    def test_never_replaces_generated_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / ".env.local"
            write_environment(ROOT, target, "28090", "28091")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            write_environment(ROOT, target, "28090", "28091")
            target.write_text(target.read_text().replace("=local", "=localx", 1))
            with self.assertRaisesRegex(ValueError, "generated secrets"):
                write_environment(ROOT, target, "28090", "28091")


if __name__ == "__main__":
    unittest.main()
