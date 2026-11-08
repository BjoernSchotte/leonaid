"""Every GitHub workflow and local action parses and can start.

GitHub rejects a run before any job ("startup_failure") when a workflow is
not valid YAML, a job has neither ``runs-on`` nor ``uses``, ``needs`` names a
missing job, or a called workflow requests more token permissions than its
caller grants (run 42503105752: select-suites.yml asked for actions: read,
api-contract.yml and pins.yml granted only contents: read). The text-based
tools/ci/workflow_contract.py cannot see these, so this test parses the
files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
LEVEL = {"none": 0, "read": 1, "write": 2}
# Scopes a job gets when neither it nor its workflow sets permissions: the
# repository default (restricted): contents and packages read.
DEFAULT = {"contents": "read", "packages": "read"}


def load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name}: not a mapping"
    return data


def workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


def granted(value: object) -> dict[str, str]:
    if value is None:
        return dict(DEFAULT)
    if value == "read-all":
        return {"*": "read"}
    if value == "write-all":
        return {"*": "write"}
    if value == {} or value == "{}":
        return {}
    assert isinstance(value, dict), f"unexpected permissions {value!r}"
    return {str(scope): str(level) for scope, level in value.items()}


def covers(grant: dict[str, str], scope: str, level: str) -> bool:
    have = grant.get(scope, grant.get("*", "none"))
    return LEVEL[have] >= LEVEL[level]


def requested(callee: dict[str, Any]) -> dict[str, str]:
    """Everything a called workflow's own levels and jobs ask for."""
    asked: dict[str, str] = {}
    blocks = [callee.get("permissions")] + [
        job.get("permissions") for job in callee.get("jobs", {}).values()
    ]
    for block in blocks:
        if isinstance(block, dict):
            for scope, level in block.items():
                if LEVEL[str(level)] > LEVEL[asked.get(str(scope), "none")]:
                    asked[str(scope)] = str(level)
    return asked


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_workflow_parses_and_jobs_can_start(path: Path) -> None:
    data = load(path)
    # YAML 1.1 reads the key "on" as True.
    assert "on" in data or True in data, f"{path.name}: no triggers"
    jobs = data.get("jobs")
    assert isinstance(jobs, dict) and jobs, f"{path.name}: no jobs"
    for name, job in jobs.items():
        assert isinstance(job, dict), f"{path.name}: job {name} is not a mapping"
        assert ("runs-on" in job) != ("uses" in job), (
            f"{path.name}: job {name} needs exactly one of runs-on and uses"
        )
        needs = job.get("needs", [])
        for need in [needs] if isinstance(needs, str) else needs:
            assert need in jobs, f"{path.name}: job {name} needs missing job {need}"
        if "runs-on" in job:
            assert job.get("steps"), f"{path.name}: job {name} has no steps"


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_called_workflows_get_the_permissions_they_request(path: Path) -> None:
    data = load(path)
    for name, job in data.get("jobs", {}).items():
        uses = job.get("uses", "")
        if not str(uses).startswith("./.github/workflows/"):
            continue
        callee = load(ROOT / str(uses)[2:])
        grant = granted(job.get("permissions", data.get("permissions")))
        missing = {
            scope: level
            for scope, level in requested(callee).items()
            if not covers(grant, scope, level)
        }
        assert not missing, (
            f"{path.name}: job {name} calls {uses}, which requests {missing}; "
            "grant them on the calling job"
        )


def test_reusable_api_callers_request_actions_read() -> None:
    """The Actions API lookups need actions: read in the called workflows.

    Without it they work only while the repository is public (the post-merge
    base lookup would quietly fall back to the complete suite, the fixture
    peer wait would wait its full time).
    """
    for name in ("select-suites.yml", "test-fixture.yml"):
        asked = requested(load(WORKFLOWS / name))
        assert asked.get("actions") == "read", f"{name}: requests {asked}"


def test_local_actions_parse() -> None:
    actions = sorted((ROOT / ".github/actions").glob("*/action.yml"))
    assert actions
    for path in actions:
        data = load(path)
        assert data.get("runs", {}).get("using") == "composite", path


def test_the_permission_check_catches_the_startup_failure() -> None:
    callee = {"permissions": {"actions": "read", "contents": "read"}, "jobs": {}}
    caller = granted({"contents": "read"})
    assert not covers(caller, "actions", requested(callee)["actions"])
    assert covers(granted({"actions": "read", "contents": "read"}), "actions", "read")
    assert not covers(granted(None), "actions", "read")
    assert covers(granted("write-all"), "checks", "write")
