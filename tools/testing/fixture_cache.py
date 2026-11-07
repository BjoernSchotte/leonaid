"""Host-wide cache of synthetic test fixtures, shared by all local checkouts.

Entries are the CI fixture format (`ci_fixture.build`), keyed by `ci_fixture.key`,
so they contain only synthetic data and public synthetic credentials. Each stack
still imports an entry into its own volumes; nothing running is shared.

Locking (flock on `<key>.lock` next to the entry):
- exclusive while one process builds the entry; others wait instead of building
  the same fixture twice;
- shared while a stack imports it; pruning skips entries that are in use.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import re
import shutil
import stat
import time
from typing import Callable, TextIO

if __package__:
    from .ci_fixture import validate
else:
    from ci_fixture import validate

KEY = re.compile(r"[0-9a-f]{64}")
DEFAULT_KEEP = 3


def default_directory() -> Path:
    # LEONAID_FIXTURE_CACHE=off disables the cache (see local_stack.py).
    configured = os.environ.get("LEONAID_FIXTURE_CACHE")
    if configured and configured != "off":
        return Path(configured)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "leonaid/fixtures"


class FixtureCache:
    def __init__(
        self,
        directory: Path | None = None,
        *,
        keep: int | None = None,
        output: TextIO | None = None,
    ):
        self.directory = (directory or default_directory()).resolve()
        self.keep = (
            keep
            if keep is not None
            else int(os.environ.get("LEONAID_FIXTURE_CACHE_KEEP", DEFAULT_KEEP))
        )
        if self.keep < 1:
            raise ValueError("The fixture cache must keep at least one entry")
        self.output = output
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.directory.lstat()
        # Never import a fixture from a directory another user can write to.
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise RuntimeError(
                f"Fixture cache {self.directory} must be a private (0700) directory of the current user"
            )
        self.held: dict[str, TextIO] = {}

    def say(self, message: str) -> None:
        print(f"fixture-cache: {message}", flush=True, file=self.output)

    def _lock(self, key: str) -> TextIO:
        if not KEY.fullmatch(key):
            raise ValueError("Invalid fixture key")
        return (self.directory / f"{key}.lock").open("a")

    def _problem(self, root: Path, entry: Path) -> str | None:
        if entry.is_symlink() or not entry.is_dir():
            return "missing"
        try:
            validate(root, entry)
        except (ValueError, KeyError, OSError) as error:
            return str(error) or type(error).__name__
        return None

    def acquire(self, root: Path, key: str, build: Callable[[Path], None]) -> Path:
        """Return a validated entry for `key`; build it once if it is missing.

        The entry stays share-locked until `release(key)`, so a concurrent
        prune never removes it while a stack imports it. Only an exclusive
        holder deletes or creates an entry.
        """
        entry = self.directory / key
        lock = self._lock(key)
        try:
            fcntl.flock(lock, fcntl.LOCK_SH)
            if self._problem(root, entry) is None:
                self.say(f"using cached fixture {key[:12]}")
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    self.say(
                        f"waiting for another checkout to build fixture {key[:12]}"
                    )
                    fcntl.flock(lock, fcntl.LOCK_EX)
                # Re-check under the exclusive lock: another builder may be done.
                problem = self._problem(root, entry)
                if problem is not None:
                    if problem != "missing":
                        self.say(f"discarding invalid fixture {key[:12]}: {problem}")
                    if entry.is_symlink() or entry.is_file():
                        entry.unlink()
                    elif entry.exists():
                        shutil.rmtree(entry)
                    self._build(key, entry, build)
                os.utime(entry)
                # flock conversion is not atomic; the fresh mtime keeps this
                # newest entry out of a concurrent prune in between.
                fcntl.flock(lock, fcntl.LOCK_SH)
            os.utime(entry)  # Last use orders pruning.
        except BaseException:
            lock.close()
            raise
        self.held[key] = lock
        return entry

    def _build(self, key: str, entry: Path, build: Callable[[Path], None]) -> None:
        start = time.monotonic()
        staging = self.directory / f".build-{key}-{os.getpid()}"
        if staging.exists():
            shutil.rmtree(staging)
        self.say(f"building fixture {key[:12]} once for all checkouts")
        try:
            build(staging)
            staging.chmod(0o700)
            staging.rename(entry)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        self.say(f"built fixture {key[:12]} in {time.monotonic() - start:.1f}s")

    def release(self, key: str) -> None:
        lock = self.held.pop(key, None)
        if lock is not None:
            lock.close()

    def prune(self) -> list[str]:
        """Keep the `keep` most recently used entries; skip entries in use."""
        entries = sorted(
            (
                path
                for path in self.directory.iterdir()
                if KEY.fullmatch(path.name) and path.is_dir()
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        removed = []
        for entry in entries[self.keep :]:
            if entry.name in self.held:
                continue
            with self._lock(entry.name) as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                # The tiny lock file stays: unlinking it would let a waiting
                # process and a new one lock different inodes for one key.
                shutil.rmtree(entry)
                removed.append(entry.name)
        # Staging directories of interrupted builds: their key lock is free.
        for staging in self.directory.glob(".build-*"):
            key = staging.name.split("-")[1]
            if not KEY.fullmatch(key):
                continue
            with self._lock(key) as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                shutil.rmtree(staging)
        if removed:
            self.say(f"pruned {len(removed)} old fixture(s); keeping {self.keep}")
        return removed
