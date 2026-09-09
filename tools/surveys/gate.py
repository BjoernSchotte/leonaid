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
import sys
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
    shards = manifest["ciShards"]
    nightly = manifest["nightlyShards"]
    assert nightly and len(nightly) == len(set(nightly))
    assert set(nightly) < set(shards), "Nightly shards must be a proper subset"
    assigned = [name for names in shards.values() for name in names]
    assert set(assigned) == set(ids) and len(assigned) == len(ids), (
        "CI shards must contain every check exactly once"
    )
    assert all(
        re.fullmatch(r"[a-z][a-z0-9-]*", name) and names
        for name, names in shards.items()
    )
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


def ci_shards(manifest: dict, suite: str) -> list[str]:
    """Partition CI execution without dropping checks from the local aggregate."""
    if suite not in {"pr", "nightly", "all"}:
        raise ValueError(f"Unknown CI suite: {suite}")
    return [
        name
        for name in manifest["ciShards"]
        if suite == "all" or (name in manifest["nightlyShards"]) == (suite == "nightly")
    ]


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


def execute(
    argv: list[str],
    root: Path,
    log: Path,
    image_cache: Path | None = None,
    stack_env: dict | None = None,
) -> int:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("LEONAID_CI_")
    }
    env.pop("LEONAID_TEST_STACK", None)
    env.pop("LEONAID_TEST_STACK_TOKEN", None)
    if stack_env:
        env.update(stack_env)
    env.pop("LEONAID_SURVEY_IMAGE_CACHE", None)
    if image_cache is not None:
        env["LEONAID_SURVEY_IMAGE_CACHE"] = str(image_cache)
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


def shareable(check: dict, manifest: dict) -> bool:
    nightly = {
        name
        for shard in manifest.get("nightlyShards", [])
        for name in manifest["ciShards"][shard]
    }
    return (
        check["argv"][:2]
        in (
            ["sh", "tools/surveys/infrastructure.sh"],
            ["sh", "tools/surveys/lifecycle_concurrency.sh"],
        )
        and check["id"] not in nightly
        and check["group"] != "foundation"
    )


@contextmanager
def shared_checks(
    root: Path, selected: list[dict], manifest: dict, private: Path, iteration: int
):
    reuse = not os.environ.get("CI") and os.environ.get("LEONAID_TEST_FRESH") != "1"
    prepared = bool(os.environ.get("LEONAID_CI_FIXTURE"))
    if sum(shareable(check, manifest) for check in selected) < (
        1 if reuse or prepared else 2
    ):
        yield None
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.testing.shared_stack import SharedStack

    with (private / f"{iteration}-shared-stack.log").open("x") as log:
        os.chmod(log.name, 0o600)
        cache = None
        if reuse:
            from tools.testing.local_stack import LocalStack

            cache = LocalStack(root, output=log)
            stack = cache.stack
        else:
            stack = SharedStack(root, "survey", log)

        def interrupted(signum, frame):
            raise KeyboardInterrupt

        previous = {
            sig: signal.signal(sig, interrupted)
            for sig in (signal.SIGINT, signal.SIGTERM)
        }
        try:
            yield stack
        finally:
            try:
                if cache:
                    cache.close()
                else:
                    stack.close()
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)


def run(
    root: Path,
    manifest: dict,
    groups: list[str],
    repeat: int,
    shard: str | None = None,
    suite: str = "all",
    check_id: str | None = None,
) -> int:
    directory = root / ".artifacts/surveys-gate"
    selected = [check for check in manifest["checks"] if check["group"] in groups]
    if shard is not None:
        selected = [c for c in selected if c["id"] in manifest["ciShards"][shard]]
        groups = list(dict.fromkeys(c["group"] for c in selected))
    allowed = (
        {
            name
            for part in ci_shards(manifest, suite)
            for name in manifest["ciShards"][part]
        }
        if suite != "all"
        else {c["id"] for c in selected}
    )
    selected = [c for c in selected if c["id"] in allowed]
    if check_id is not None:
        selected = [c for c in selected if c["id"] == check_id]
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
            "shard": shard,
            "requestedPasses": repeat,
            "checksPerPass": len(selected),
            "status": "running",
            "automatedGatePassed": False,
            "manualReviewRequired": manifest["manualReviewRequired"],
            "checks": [],
        }
        save_report(report_path, report)
        for iteration in range(1, repeat + 1):
            with shared_checks(root, selected, manifest, private, iteration) as stack:
                for check in selected:
                    name = check["id"]
                    print(f"Survey gate pass {iteration}/{repeat}: {name}", flush=True)
                    start = time.monotonic()
                    try:
                        stack_env = (
                            stack.prepare()
                            if stack and shareable(check, manifest)
                            else None
                        )
                        code = execute(
                            [
                                part.replace("{root}", str(root))
                                for part in check["argv"]
                            ],
                            root,
                            private / f"{iteration}-{name}.log",
                            None if stack_env else private / f"images-{iteration}",
                            stack_env,
                        )
                    except (OSError, RuntimeError, subprocess.CalledProcessError):
                        code = 1

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
    parser.add_argument("--check", help="Run one explicitly selected manifest check")
    parser.add_argument("--group", action="append", default=[])
    parser.add_argument("--shard", help="Run one complete CI shard from the manifest")
    parser.add_argument(
        "--suite",
        choices=["pr", "nightly", "all"],
        help="Defaults to pr; recovery requires explicit selection",
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = load_manifest(root)
    if args.repeat < 1 or args.repeat > 10:
        parser.error("--repeat must be between 1 and 10")
    if any(group not in manifest["groups"] for group in args.group):
        parser.error("Unknown group; use --list for the manifest")
    if args.shard and (args.shard not in manifest["ciShards"] or args.group):
        parser.error("Use a known --shard without --group")
    if args.check and (
        args.group
        or args.shard
        or args.check not in {c["id"] for c in manifest["checks"]}
    ):
        parser.error("Use a known --check without --group or --shard")
    groups = list(dict.fromkeys(args.group or manifest["groups"]))
    suite = args.suite or (
        "all" if args.check or args.shard or "recovery" in args.group else "pr"
    )
    if args.list:
        print(
            json.dumps(
                {
                    **manifest,
                    "selectedGroups": groups,
                    "selectedShard": args.shard,
                    "selectedSuite": suite,
                    "selectedCheck": args.check,
                },
                indent=2,
            )
        )
        return 0
    try:
        return run(root, manifest, groups, args.repeat, args.shard, suite, args.check)
    except RuntimeError:
        print(
            "Survey gate refused: another aggregate holds this checkout lock.",
            flush=True,
        )
        return 75


if __name__ == "__main__":
    raise SystemExit(main())
