"""Sequential survey gate; publish only structured metadata, never child output."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from uuid import uuid4


def load_manifest(root: Path) -> dict:
    manifest = json.loads((root / "tools/surveys/gate.json").read_text())
    assert manifest["schemaVersion"] == 1
    groups = manifest["groups"]
    checks = manifest["checks"]
    assert len(groups) == len(set(groups)) and groups and checks
    ids = [check["id"] for check in checks]
    assert len(ids) == len(set(ids))
    for check in checks:
        assert re.fullmatch(r"[a-z][a-z0-9-]*", check["id"])
        assert check["group"] in groups
        assert check["argv"] and all(isinstance(v, str) for v in check["argv"])
        assert check["argv"][0] in {"./leonaid", "sh", "python3"}
        if check["argv"][0] == "./leonaid":
            assert len(check["argv"]) == 2
            assert check["argv"][1] in {
                "test-surveys-core",
                "test-surveys-validation-candidate",
                "test-surveys-dependencies",
                "test-surveys-migrations",
                "test-surveys-package",
            }, "Aggregate recursion or unknown leaf command"
        else:
            script = Path(check["argv"][1])
            assert not script.is_absolute() and ".." not in script.parts
            assert (root / script).is_file()
    modes = set(
        re.findall(
            r'\$mode" = ([a-z-]+)',
            (root / "tools/surveys/infrastructure.sh").read_text(),
        )
    )
    declared = [
        mode for check in checks for mode in check.get("infrastructureModes", [])
    ]
    assert set(declared) == modes and len(declared) == len(set(declared)), (
        "Unmapped or repeated infrastructure mode"
    )
    for reference in manifest["manualReviewRequired"]:
        assert (root / reference.split("#")[0]).is_file()
    return manifest


@contextmanager
def exclusive_run(directory: Path):
    """One aggregate runner per checkout; independent worktrees do not share it."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(
                "Another survey aggregate is running in this checkout"
            ) from None
        yield


def save_report(path: Path, report: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    os.replace(temporary, path)


def execute(argv: list[str], root: Path, log: Path) -> int:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("LEONAID_CI_")
    }
    interrupted = False
    with log.open("x") as output:
        log.chmod(0o600)
        try:
            process = subprocess.Popen(
                argv,
                cwd=root,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError:
            return 127

        def stop(signum, frame):
            nonlocal interrupted
            interrupted = True
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)

        previous = {
            sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)
        }
        try:
            while True:
                try:
                    code = process.wait(timeout=30)
                    return 130 if interrupted else (code if code >= 0 else 128 - code)
                except subprocess.TimeoutExpired:
                    print(
                        "Survey check still running; waiting for its process and cleanup.",
                        flush=True,
                    )
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def run(root: Path, manifest: dict, groups: list[str], repeat: int) -> int:
    directory = root / ".artifacts/surveys-gate"
    selected = [check for check in manifest["checks"] if check["group"] in groups]
    assert selected
    with exclusive_run(directory):
        private = Path(tempfile.mkdtemp(prefix="private-", dir=directory))
        published = directory / "results"
        published.mkdir(exist_ok=True)
        report_path = published / f"{uuid4().hex}.json"
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
        assert re.fullmatch("[0-9a-f]{40,64}", commit)
        report = {
            "schemaVersion": 1,
            "commit": commit,
            "manifestSha256": hashlib.sha256(
                (root / "tools/surveys/gate.json").read_bytes()
            ).hexdigest(),
            "startedAt": datetime.now(timezone.utc).isoformat(),
            "groups": groups,
            "requestedPasses": repeat,
            "checksPerPass": len(selected),
            "status": "running",
            "automatedGatePassed": False,
            "manualReviewRequired": manifest["manualReviewRequired"],
            "checks": [],
        }
        save_report(report_path, report)
        for iteration in range(1, repeat + 1):
            for check in selected:
                name = check["id"]
                print(f"Survey gate pass {iteration}/{repeat}: {name}", flush=True)
                start = time.monotonic()
                code = execute(
                    [part.replace("{root}", str(root)) for part in check["argv"]],
                    root,
                    private / f"{iteration}-{name}.log",
                )
                report["checks"].append(
                    {
                        "id": name,
                        "group": check["group"],
                        "pass": iteration,
                        "exitCode": code,
                        "seconds": round(time.monotonic() - start, 3),
                    }
                )
                if code:
                    report.update(
                        status="interrupted" if code == 130 else "failed",
                        finishedAt=datetime.now(timezone.utc).isoformat(),
                    )
                    save_report(report_path, report)
                    print(
                        f"FAIL: {name}, exit {code}. Child diagnostics remain in the private local run directory.",
                        flush=True,
                    )
                    return code
                save_report(report_path, report)
                print(f"PASS: {name}", flush=True)
        report.update(
            status="passed",
            automatedGatePassed=True,
            finishedAt=datetime.now(timezone.utc).isoformat(),
        )
        save_report(report_path, report)
        print(
            f"PASS: {len(selected)} survey checks across {repeat} complete pass(es). Manual acceptance remains a separate review.",
            flush=True,
        )
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--group", action="append", default=[])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = load_manifest(root)
    if args.repeat < 1 or args.repeat > 10:
        parser.error("--repeat must be between 1 and 10")
    if any(group not in manifest["groups"] for group in args.group):
        parser.error("Unknown group; use --list for the manifest")
    groups = list(dict.fromkeys(args.group or manifest["groups"]))
    if args.list:
        print(json.dumps({**manifest, "selectedGroups": groups}, indent=2))
        return 0
    try:
        return run(root, manifest, groups, args.repeat)
    except RuntimeError:
        print(
            "Survey gate refused: another aggregate holds this checkout lock.",
            flush=True,
        )
        return 75


if __name__ == "__main__":
    raise SystemExit(main())
