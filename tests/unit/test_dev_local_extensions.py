"""Guards for uncommitted local dev extensions (.local/dev).

The dev stack may load a committed overlay that mounts .local/dev into the
proxy, plus a developer's own compose.override.yml. These guards keep the
mechanism dev-only: the base stack and the pilot never reference it, the
overlay adds nothing but read-only proxy mounts, and the Caddyfile imports the
snippets only at the documented place.
"""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = "infra/compose/compose.dev-local.yml"
DEV_CADDYFILE = "infra/proxy/Caddyfile"
LOCAL_IMPORT = "import /etc/caddy/local.d/*.caddy"
LOCAL_MARKERS = (".local/dev", "local.d", "local-static", "compose.dev-local")


def _compose(relative: str) -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(
        (ROOT / relative).read_text(encoding="utf-8")
    )
    return document


def _block(text: str, name: str) -> str:
    match = re.search(rf"^\({name}\) \{{\n(.*?)^\}}", text, re.M | re.S)
    assert match, f"{DEV_CADDYFILE} lacks ({name})"
    return match.group(1)


@pytest.mark.parametrize(
    "path",
    sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "infra/pilot").rglob("*")
        if path.is_file() and path.suffix != ".md"
    ),
)
def test_pilot_runtime_never_references_local_dev(path: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    for marker in LOCAL_MARKERS:
        assert marker not in text, f"{path} references {marker}"


def test_pilot_runtime_files_are_covered() -> None:
    covered = {
        path.name
        for path in (ROOT / "infra/pilot").rglob("*")
        if path.is_file() and path.suffix != ".md"
    }
    assert {"compose.yml", "Caddyfile", "Caddyfile.test"} <= covered


def test_base_compose_has_no_local_mounts() -> None:
    text = (ROOT / "infra/compose/compose.yml").read_text(encoding="utf-8")
    for marker in LOCAL_MARKERS:
        assert marker not in text
    for name, service in _compose("infra/compose/compose.yml")["services"].items():
        for volume in service.get("volumes", []):
            if isinstance(volume, str):
                source = volume.split(":", 1)[0]
            else:
                source = str(volume.get("source", ""))
            assert ".local" not in source, f"{name} mounts {source}"


def test_dev_overlay_only_adds_read_only_proxy_mounts() -> None:
    overlay = _compose(OVERLAY)
    assert set(overlay) == {"services"}
    assert set(overlay["services"]) == {"proxy"}
    proxy = overlay["services"]["proxy"]
    assert set(proxy) == {"volumes"}
    assert proxy["volumes"] == [
        "../../.local/dev/caddy.d:/etc/caddy/local.d:ro",
        "../../.local/dev/static:/srv/local-static:ro",
    ]


def test_caddy_imports_local_snippets_inside_routes_before_catch_all() -> None:
    text = (ROOT / DEV_CADDYFILE).read_text(encoding="utf-8")
    assert text.count(LOCAL_IMPORT) == 1
    routes = _block(text, "leonaid_routes")
    assert LOCAL_IMPORT in routes
    catch_all = routes.index("\n\thandle {\n")
    assert routes.index(LOCAL_IMPORT) < catch_all
    assert "\n\thandle" not in routes[catch_all + 1 :].split("\n", 1)[1]


def _cli_functions() -> str:
    script = (ROOT / "leonaid").read_text(encoding="utf-8")
    match = re.search(
        r"^dev_local_enabled\(\) \{\n.*?^\}\n\ncompose\(\) \{\n.*?^\}\n",
        script,
        re.M | re.S,
    )
    assert match, "leonaid lacks dev_local_enabled() and compose()"
    return match.group(0)


def _compose_files(
    root: Path, project: str | None, default_project: str = "leonaid"
) -> list[str]:
    """Run the CLI's compose() with a stub docker and return its --file values.

    `default_project` is what the CLI derives for the checkout: "leonaid" for
    the main checkout, leonaid-wt-<checksum> for a linked worktree.
    """
    project_line = (
        "unset LEONAID_COMPOSE_PROJECT"
        if project is None
        else f"LEONAID_COMPOSE_PROJECT='{project}'; export LEONAID_COMPOSE_PROJECT"
    )
    program = "\n".join(
        (
            "set -eu",
            f"root='{root}'",
            project_line,
            f"default_project='{default_project}'",
            "dev_project=${LEONAID_COMPOSE_PROJECT:-$default_project}",
            "compose_queue_store_guard() { :; }",
            "docker() { printf '%s\\n' \"$@\"; }",
            _cli_functions(),
            "compose up --detach",
        )
    )
    shell = shutil.which("sh")
    assert shell
    result = subprocess.run(
        [shell, "-c", program], check=True, capture_output=True, text=True
    )
    arguments = result.stdout.splitlines()
    assert arguments[-2:] == ["up", "--detach"]
    assert arguments[arguments.index("--project-name") + 1] == (
        project or default_project
    )
    return [arguments[i + 1] for i, value in enumerate(arguments) if value == "--file"]


def test_cli_loads_no_local_files_without_opt_in(tmp_path: Path) -> None:
    assert _compose_files(tmp_path, None) == [f"{tmp_path}/infra/compose/compose.yml"]
    assert not (tmp_path / ".local").exists()


def test_cli_loads_overlay_and_override_for_the_dev_project(tmp_path: Path) -> None:
    (tmp_path / ".local/dev").mkdir(parents=True)
    base = f"{tmp_path}/infra/compose/compose.yml"
    overlay = f"{tmp_path}/{OVERLAY}"
    assert _compose_files(tmp_path, None) == [base, overlay]
    assert (tmp_path / ".local/dev/caddy.d").is_dir()
    assert (tmp_path / ".local/dev/static").is_dir()

    (tmp_path / ".local/dev/compose.override.yml").write_text("services: {}\n")
    override = f"{tmp_path}/.local/dev/compose.override.yml"
    assert _compose_files(tmp_path, "leonaid") == [base, overlay, override]


def test_worktree_dev_project_loads_its_own_local_files(tmp_path: Path) -> None:
    (tmp_path / ".local/dev").mkdir(parents=True)
    base = f"{tmp_path}/infra/compose/compose.yml"
    overlay = f"{tmp_path}/{OVERLAY}"
    assert _compose_files(tmp_path, None, "leonaid-wt-42") == [base, overlay]
    # The main checkout's project is another project from a worktree's view.
    assert _compose_files(tmp_path, "leonaid", "leonaid-wt-42") == [base]


@pytest.mark.parametrize("project", ["leonaid-shared-0123", "leonaid-production"])
def test_cli_never_loads_local_files_for_other_projects(
    tmp_path: Path, project: str
) -> None:
    (tmp_path / ".local/dev").mkdir(parents=True)
    (tmp_path / ".local/dev/compose.override.yml").write_text("services: {}\n")
    assert _compose_files(tmp_path, project) == [
        f"{tmp_path}/infra/compose/compose.yml"
    ]
