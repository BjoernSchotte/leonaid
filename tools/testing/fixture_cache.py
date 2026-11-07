"""Host-wide cache of synthetic test fixtures, shared by all local checkouts.

Entries are the CI fixture format (`ci_fixture.build`), keyed by `ci_fixture.key`,
so they contain only synthetic data and public synthetic credentials. Each stack
still imports an entry into its own volumes; nothing running is shared.

Locking (flock on `<key>.lock` next to the entry):
- exclusive while one process builds the entry; others wait instead of building
  the same fixture twice;
- shared while a stack imports it; pruning skips entries that are in use.

Bounds: at most `keep` entries and `max_bytes` in total, but entries used in
the last `min_age` seconds are never pruned. `./leonaid fixture-cache clear`
removes every entry that is not in use.
"""

from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time
from typing import Callable, TextIO

if __package__:
    from .ci_fixture import validate
else:
    from ci_fixture import validate

KEY = re.compile(r"[0-9a-f]{64}")
DEFAULT_KEEP = 3
DEFAULT_MAX_MB = 4096
# A just-built or just-used entry may be between flock conversion and import.
DEFAULT_MIN_AGE = 3600


def default_directory() -> Path:
    # LEONAID_FIXTURE_CACHE=off disables the cache (see local_stack.py).
    configured = os.environ.get("LEONAID_FIXTURE_CACHE")
    if configured and configured != "off":
        return Path(configured)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "leonaid/fixtures"


def size(path: Path) -> int:
    return sum(item.lstat().st_size for item in path.rglob("*") if item.is_file())


class FixtureCache:
    def __init__(
        self,
        directory: Path | None = None,
        *,
        keep: int | None = None,
        max_bytes: int | None = None,
        min_age: float | None = None,
        output: TextIO | None = None,
    ):
        self.directory = (directory or default_directory()).resolve()
        environment = os.environ.get
        self.keep = (
            keep
            if keep is not None
            else int(environment("LEONAID_FIXTURE_CACHE_KEEP", DEFAULT_KEEP))
        )
        self.max_bytes = (
            max_bytes
            if max_bytes is not None
            else int(environment("LEONAID_FIXTURE_CACHE_MAX_MB", DEFAULT_MAX_MB))
            * 1024
            * 1024
        )
        self.min_age = min_age if min_age is not None else DEFAULT_MIN_AGE
        if self.keep < 1 or self.max_bytes < 1:
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

    def _check(self, root: Path, entry: Path) -> tuple[dict | None, str | None]:
        """Return (metadata, None) for a valid entry, else (None, problem)."""
        if entry.is_symlink() or not entry.is_dir():
            return None, "missing"
        try:
            return validate(root, entry), None
        except (ValueError, KeyError, OSError) as error:
            return None, str(error) or type(error).__name__

    def acquire(
        self, root: Path, key: str, build: Callable[[Path], None]
    ) -> tuple[Path, dict]:
        """Return a validated entry for `key` and its manifest; build it once.

        The entry stays share-locked until `release(key)`, so a concurrent
        prune never removes it while a stack imports it. Only an exclusive
        holder deletes or creates an entry. The returned manifest was
        validated (all payload hashes) under the lock, so the import need not
        hash the entry again.
        """
        entry = self.directory / key
        lock = self._lock(key)
        try:
            fcntl.flock(lock, fcntl.LOCK_SH)
            metadata, problem = self._check(root, entry)
            if metadata is not None:
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
                metadata, problem = self._check(root, entry)
                if metadata is None:
                    if problem != "missing":
                        self.say(f"discarding invalid fixture {key[:12]}: {problem}")
                    if entry.is_symlink() or entry.is_file():
                        entry.unlink()
                    elif entry.exists():
                        shutil.rmtree(entry)
                    self._build(key, entry, build)
                    metadata, problem = self._check(root, entry)
                    if metadata is None:
                        raise RuntimeError(f"Built fixture is invalid: {problem}")
                os.utime(entry)
                # flock conversion is not atomic; prune skips entries used
                # within min_age, so the gap cannot lose this entry.
                fcntl.flock(lock, fcntl.LOCK_SH)
            os.utime(entry)  # Last use orders pruning.
        except BaseException:
            lock.close()
            raise
        self.held[key] = lock
        return entry, metadata

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

    def _entries(self) -> list[Path]:
        """Entries, most recently used first."""
        return sorted(
            (
                path
                for path in self.directory.iterdir()
                if KEY.fullmatch(path.name) and path.is_dir()
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    def _remove_if_free(self, entry: Path) -> bool:
        if entry.name in self.held:
            return False
        with self._lock(entry.name) as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            # The tiny lock file stays: unlinking it would let a waiting
            # process and a new one lock different inodes for one key.
            shutil.rmtree(entry)
            return True

    def _remove_stale_staging(self) -> None:
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

    def prune(self) -> list[str]:
        """Remove the least recently used entries beyond `keep` or `max_bytes`.

        Entries in use and entries used within `min_age` are never removed,
        so the cache may exceed its bounds while many checkouts are active.
        """
        now = time.time()
        removed = []
        total = 0
        for index, entry in enumerate(self._entries()):
            entry_size = size(entry)
            total += entry_size
            if index < self.keep and total <= self.max_bytes:
                continue
            if index == 0 or now - entry.stat().st_mtime < self.min_age:
                continue
            if self._remove_if_free(entry):
                removed.append(entry.name)
                total -= entry_size
        self._remove_stale_staging()
        if removed:
            self.say(
                f"pruned {len(removed)} old fixture(s); keeping at most {self.keep}"
                f" and {self.max_bytes // (1024 * 1024)} MB"
            )
        return removed

    def clear(self) -> tuple[list[str], list[str]]:
        """Remove every entry that is not in use; return (removed, busy)."""
        removed, busy = [], []
        for entry in self._entries():
            (removed if self._remove_if_free(entry) else busy).append(entry.name)
        self._remove_stale_staging()
        return removed, busy

    def status(self) -> str:
        entries = self._entries()
        total = sum(size(entry) for entry in entries)
        return (
            f"{self.directory}: {len(entries)} fixture(s), {total / 1024 / 1024:.0f} MB"
            f" (bounds: {self.keep} entries, {self.max_bytes // (1024 * 1024)} MB)"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["status", "clear"])
    args = parser.parse_args()
    cache = FixtureCache()
    if args.command == "clear":
        removed, busy = cache.clear()
        cache.say(f"removed {len(removed)} fixture(s)")
        if busy:
            cache.say(f"kept {len(busy)} fixture(s) in use by a running test")
    print(cache.status())
    return 0


if __name__ == "__main__":
    sys.exit(main())
