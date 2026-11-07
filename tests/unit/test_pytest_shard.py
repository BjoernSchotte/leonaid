"""The check's pytest shards run every collected test exactly once."""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def passed(tmp_path: Path, shard: str | None) -> set[str]:
    environment = {**os.environ, "PYTHONPATH": str(ROOT)}
    environment.pop("LEONAID_PYTEST_SHARD", None)
    if shard is not None:
        environment["LEONAID_PYTEST_SHARD"] = shard
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tools.dx.pytest_shard",
            "-p",
            "no:cacheprovider",
            "-v",
            "--rootdir",
            str(tmp_path),
            str(tmp_path / "test_sample.py"),
        ],
        env=environment,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode in (0, 5), result.stdout + result.stderr
    return set(re.findall(r"(test_\w+\[\d+\]) PASSED", result.stdout))


def test_shards_partition_the_collection(tmp_path: Path) -> None:
    (tmp_path / "test_sample.py").write_text(
        "import pytest\n\n"
        "@pytest.mark.parametrize('n', range(7))\n"
        "def test_case(n):\n    assert n >= 0\n"
    )
    everything = passed(tmp_path, None)
    assert len(everything) == 7
    shards = [passed(tmp_path, f"{index}/3") for index in range(3)]
    assert set().union(*shards) == everything
    assert sum(len(shard) for shard in shards) == 7
    assert all(shards)


def test_invalid_shard_is_refused(tmp_path: Path) -> None:
    (tmp_path / "test_sample.py").write_text("def test_case():\n    pass\n")
    environment = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "LEONAID_PYTEST_SHARD": "3/3",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tools.dx.pytest_shard",
            "-q",
            "-p",
            "no:cacheprovider",
            str(tmp_path / "test_sample.py"),
        ],
        env=environment,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "Invalid LEONAID_PYTEST_SHARD" in result.stdout + result.stderr
