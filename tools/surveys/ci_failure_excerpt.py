"""Print and export a sanitized excerpt of each failed survey check's log.

`ci_diagnostics.py` exports fixed categories only; a failed CI shard also
needs the failing test names, the assertion message and the last service
lines to be diagnosable. This script takes, per failed check of this run, the
lines that look like failures plus the log tail, and passes them through the
same sanitizer as every other CI artifact (tools/ci/sanitize_artifacts.py):
known secrets from `.env.local` and the run's `*.env` files are redacted, and
an excerpt with a personal e-mail, phone or private canary signature is
withheld (fail closed) instead of printed. Raw logs stay private.

Usage: ci_failure_excerpt.py ROOT DESTINATION
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ci import sanitize_artifacts  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
FAILURE_LINE = re.compile(
    r"(✘|✗|×|\bFAIL|\bfailed\b|Error\b|error:|AssertionError|Traceback|"
    r"expect\(|Expected|Received|Timeout|timed out|unhealthy|exit code|exited with)",
)
MAX_FAILURE_LINES = 80
TAIL_LINES = 150
MAX_LINE = 400
READ_BYTES = 4 * 1024 * 1024
# Logs of checks that run their own foundation harness.
FOUNDATION_LOGS = {
    "foundation-diagnostics": "infrastructure",
    "foundation-failure": "infrastructure-failure",
}


def failed_checks(root: Path) -> list[tuple[int, str]]:
    failed: set[tuple[int, str]] = set()
    for report in sorted((root / ".artifacts/surveys-gate/results").glob("*.json")):
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for check in data.get("checks", []) if isinstance(data, dict) else []:
            if (
                isinstance(check, dict)
                and check.get("exitCode")
                and isinstance(check.get("pass"), int)
                and re.fullmatch(r"[a-z][a-z0-9-]*", str(check.get("id", "")))
            ):
                failed.add((check["pass"], check["id"]))
    return sorted(failed)


def read_tail(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        return ""
    with path.open("rb") as stream:
        size = path.stat().st_size
        stream.seek(max(0, size - READ_BYTES))
        return stream.read().decode("utf-8", errors="replace")


def excerpt(text: str) -> str:
    lines = [ANSI.sub("", line)[:MAX_LINE] for line in text.splitlines()]
    tail_start = max(0, len(lines) - TAIL_LINES)
    failures = [
        f"{number + 1}: {line}"
        for number, line in enumerate(lines[:tail_start])
        if FAILURE_LINE.search(line)
    ][-MAX_FAILURE_LINES:]
    parts = []
    if failures:
        parts += ["--- failure lines before the tail (line: text) ---", *failures]
    parts += [f"--- last {len(lines) - tail_start} lines ---", *lines[tail_start:]]
    return "\n".join(parts) + "\n"


def secrets(root: Path) -> dict[str, str]:
    found = sanitize_artifacts.secrets_from(root / ".env.local")
    for directory in (
        root / ".artifacts/surveys-gate",
        root / ".artifacts/foundation-acceptance",
    ):
        if directory.is_dir():
            for env_file in directory.rglob("*.env"):
                if not env_file.is_symlink():
                    found.update(sanitize_artifacts.secrets_from(env_file))
    return found


def logs_for(root: Path, iteration: int, check: str) -> list[tuple[str, Path]]:
    found = [
        (f"{iteration}-{check}", path)
        for path in sorted(
            (root / ".artifacts/surveys-gate").glob(f"private-*/{iteration}-{check}.log")
        )
    ]
    if check in FOUNDATION_LOGS:
        name = FOUNDATION_LOGS[check]
        found.append(
            (f"{check}-harness", root / f".artifacts/foundation-acceptance/{name}.log")
        )
    return found


def export(root: Path, destination: Path) -> list[tuple[str, str]]:
    """Write sanitized excerpts; return (label, public text) for printing."""
    known = secrets(root)
    destination.mkdir(parents=True, exist_ok=True)
    printed = []
    for iteration, check in failed_checks(root):
        for label, path in logs_for(root, iteration, check):
            raw = read_tail(path)
            if not raw:
                continue
            target = destination / f"{label}.log"
            try:
                result = sanitize_artifacts.sanitize_text(
                    excerpt(raw).encode("utf-8"),
                    label=target.name,
                    suffix=".log",
                    secrets=known,
                )
                public = result.payload.decode("utf-8")
            except sanitize_artifacts.SanitizationFailure as error:
                # The reason names only the rule and the file, never the data.
                public = f"Excerpt withheld by the artifact sanitizer: {error}\n"
            target.write_text(public, encoding="utf-8")
            target.chmod(0o644)
            printed.append((label, public))
    return printed


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 64
    printed = export(Path(argv[1]).resolve(), Path(argv[2]))
    for label, public in printed:
        print(f"::group::Sanitized failure excerpt: {label}")
        print(public, end="")
        print("::endgroup::")
    print(f"survey-failure-excerpt: {len(printed)} sanitized excerpt(s) written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
