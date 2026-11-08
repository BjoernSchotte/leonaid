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


def triggers_of(data: dict[str, Any]) -> set[str]:
    on = data.get("on", data.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(item) for item in on}
    return {str(item) for item in (on or {})}


MAIN_ONLY = "github.ref == 'refs/heads/main'"
NOT_PULL_REQUEST = "github.event_name != 'pull_request'"
TAG_ONLY = "github.ref_type == 'tag'"


def package_writers(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (name, job)
        for name, job in data.get("jobs", {}).items()
        if covers(
            granted(job.get("permissions", data.get("permissions"))),
            "packages",
            "write",
        )
    ]


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_packages_write_only_in_main_only_jobs(path: Path) -> None:
    """Only runs on main may push images (decision E-020).

    A pull request (forks included) could otherwise publish content under a
    content hash main also builds. The grant stays on the job, never on the
    workflow, and the job's condition pins it to main outside pull requests.
    """
    data = load(path)
    top = data.get("permissions")
    assert top is None or not covers(granted(top), "packages", "write"), (
        f"{path.name}: packages: write belongs on the publishing job only"
    )
    triggers = triggers_of(data)
    writers = package_writers(data)
    assert not ("pull_request_target" in triggers and writers), path.name
    for name, job in writers:
        condition = str(job.get("if", ""))
        # Release images: only a pushed tag (maintainers only) publishes.
        release = TAG_ONLY in condition and "pull_request" not in triggers
        assert MAIN_ONLY in condition or release, (
            f"{path.name}: job {name} must run on main (or a release tag) only"
        )
        assert NOT_PULL_REQUEST in condition or "pull_request" not in triggers, (
            f"{path.name}: job {name} must not run for pull requests"
        )
        for step in job.get("steps", []):
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert (step.get("with") or {}).get("persist-credentials") is False, (
                    f"{path.name}: job {name} must not persist the checkout token"
                )


def test_packages_write_check_sees_every_grant() -> None:
    job = {"if": MAIN_ONLY, "permissions": {"packages": "write"}, "steps": []}
    writers = package_writers({"permissions": {"contents": "read"}, "jobs": {"p": job}})
    assert [name for name, _ in writers] == ["p"]
    assert package_writers({"permissions": "write-all", "jobs": {"x": {}}})
    assert not package_writers({"permissions": {"contents": "read"}, "jobs": {"x": {}}})


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_image_jobs_honour_the_prebuilt_kill_switch(path: Path) -> None:
    """CI_PREBUILT_IMAGES=off (repository variable) must reach the action."""
    text = path.read_text(encoding="utf-8")
    uses = text.count("uses: ./.github/actions/build-cache")
    if not uses:
        return
    env = load(path).get("env") or {}
    assert (
        text.count('prebuilt: "false"') == uses
        or env.get("CI_PREBUILT_IMAGES") == "${{ vars.CI_PREBUILT_IMAGES }}"
    ), f"{path.name}: set env CI_PREBUILT_IMAGES to vars.CI_PREBUILT_IMAGES"
