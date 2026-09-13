from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_INFRASTRUCTURE = {
    "asyncpg",
    "boto3",
    "botocore",
    "fastapi",
    "httpx",
    "psycopg",
    "smtplib",
    "sqlalchemy",
}


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def imported_modules(path: Path, package: str | None = None) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                if package is None:
                    raise ValueError(f"Relative import needs package context: {path}")
                module = resolve_name("." * node.level + module, package)
            modules.add(module)
            # Also catch `from leonaid.modules import tasks` and relative siblings.
            modules.update(f"{module}.{alias.name}" for alias in node.names)
    return modules


def test_domain_and_application_do_not_import_concrete_infrastructure() -> None:
    violations: list[str] = []
    for layer in ("domain", "application"):
        for path in sorted((ROOT / "src/leonaid" / layer).rglob("*.py")):
            forbidden = imported_roots(path) & FORBIDDEN_INFRASTRUCTURE
            modules = imported_modules(path)
            inward_violations = {
                module
                for module in modules
                if module.startswith(("leonaid.adapters", "leonaid.entrypoints"))
            }
            if forbidden or inward_violations:
                violations.append(
                    f"{path.relative_to(ROOT)}: {sorted(forbidden | inward_violations)}"
                )
    assert violations == []


def module_boundary_violations(root: Path) -> list[str]:
    """Check explicit Python imports; SQL ownership still needs code review."""
    violations: list[str] = []
    edges: dict[str, set[str]] = {}
    for area in ("platform", "modules", "bootstrap"):
        for path in sorted((root / area).rglob("*.py")):
            relative = path.relative_to(root)
            parts = relative.parts
            source = parts[1] if area == "modules" and len(parts) > 2 else None
            package = ".".join(("leonaid", *parts[:-1]))
            imports = imported_modules(path, package)
            is_logic = area != "bootstrap" and (
                path.stem in {"api", "service", "domain", "models", "contracts"}
                or "domain" in parts
                or "application" in parts
            )
            for target in sorted(imports):
                target_parts = target.split(".")
                if target_parts[0] != "leonaid":
                    if is_logic and target_parts[0] in FORBIDDEN_INFRASTRUCTURE:
                        violations.append(f"{relative}: infrastructure {target}")
                    continue
                destination = target_parts[1] if len(target_parts) > 1 else ""
                if area == "platform" and destination in {
                    "modules",
                    "bootstrap",
                    "entrypoints",
                }:
                    violations.append(f"{relative}: platform back-reference {target}")
                if area == "modules" and destination in {"bootstrap", "entrypoints"}:
                    violations.append(f"{relative}: module back-reference {target}")
                if (
                    source is not None
                    and destination == "modules"
                    and len(target_parts) > 2
                    and target_parts[2] != source
                ):
                    other = target_parts[2]
                    edges.setdefault(source, set()).add(other)
                    if len(target_parts) < 4 or target_parts[3] != "api":
                        violations.append(f"{relative}: private module import {target}")
                if is_logic and destination == "adapters":
                    violations.append(f"{relative}: concrete adapter {target}")
                if (
                    is_logic
                    and destination in {"modules", "platform"}
                    and any(
                        part in {"adapters", "repository", "routes", "jobs"}
                        for part in target_parts[2:]
                    )
                ):
                    violations.append(f"{relative}: concrete adapter {target}")

    visited: set[str] = set()

    def visit(module: str, stack: tuple[str, ...]) -> None:
        if module in stack:
            violations.append("module cycle: " + " -> ".join((*stack, module)))
            return
        if module in visited:
            return
        for dependency in sorted(edges.get(module, set())):
            visit(dependency, (*stack, module))
        visited.add(module)

    for module in sorted(edges):
        visit(module, ())
    return violations


def test_modular_platform_boundaries() -> None:
    assert module_boundary_violations(ROOT / "src/leonaid") == []


@pytest.mark.parametrize(
    ("file", "code", "reason"),
    [
        ("platform/db.py", "import leonaid.modules.tasks.api", "back-reference"),
        ("platform/db.py", "from ..modules import tasks", "back-reference"),
        ("modules/tasks/jobs.py", "from ...bootstrap import worker", "back-reference"),
        (
            "modules/tasks/jobs.py",
            "import leonaid.entrypoints.worker",
            "back-reference",
        ),
        ("modules/tasks/api.py", "from ..inbox.repository import Inbox", "private"),
        ("modules/tasks/api.py", "from .. import inbox", "private"),
        ("modules/tasks/domain/rules.py", "import asyncpg", "infrastructure"),
        ("modules/tasks/models.py", "import asyncpg", "infrastructure"),
        (
            "modules/tasks/domain/rules.py",
            "from ..adapters.postgres import TaskRepository",
            "adapter",
        ),
        (
            "modules/tasks/service.py",
            "from .repository import Tasks",
            "adapter",
        ),
        (
            "platform/application/jobs.py",
            "from ..adapters.queue import Queue",
            "adapter",
        ),
        (
            "modules/tasks/service.py",
            "from leonaid.adapters import postgres",
            "adapter",
        ),
    ],
)
def test_boundary_checker_rejects_forbidden_imports(
    tmp_path: Path, file: str, code: str, reason: str
) -> None:
    path = tmp_path / file
    path.parent.mkdir(parents=True)
    path.write_text(code)
    assert any(reason in error for error in module_boundary_violations(tmp_path))


def test_boundary_checker_accepts_public_apis_but_rejects_cycles(
    tmp_path: Path,
) -> None:
    for name in ("tasks", "knowledge"):
        (tmp_path / "modules" / name).mkdir(parents=True)
    (tmp_path / "modules/knowledge/api.py").write_text(
        "from ..tasks.api import create_task"
    )
    assert module_boundary_violations(tmp_path) == []
    (tmp_path / "modules/tasks/api.py").write_text(
        "from leonaid.modules.knowledge.api import read_page"
    )
    assert any("cycle" in error for error in module_boundary_violations(tmp_path))


def test_fastapi_routes_only_depend_on_application_and_domain_layers() -> None:
    path = ROOT / "src/leonaid/entrypoints/fastapi/routes.py"
    modules = imported_modules(path)
    forbidden = {
        module
        for module in modules
        if module.startswith(("leonaid.adapters", "leonaid.configuration"))
        or module.split(".", 1)[0] in FORBIDDEN_INFRASTRUCTURE - {"fastapi"}
    }
    assert forbidden == set()


def test_twenty_wire_fields_stay_inside_the_twenty_adapter() -> None:
    wire_fields = {
        "addressPostcode",
        "addressStreet1",
        "companyId",
        "firstName",
        "lastName",
        "primaryEmail",
        "starting_after",
    }
    violations: list[str] = []
    roots = (
        ROOT / "src/leonaid/domain",
        ROOT / "src/leonaid/application",
        ROOT / "src/leonaid/modules",
        ROOT / "apps",
        ROOT / "packages/features",
        ROOT / "packages/ui",
    )
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.suffix not in {".py", ".ts", ".tsx", ".astro"}:
                continue
            content = path.read_text(encoding="utf-8")
            found = sorted(field for field in wire_fields if field in content)
            if found:
                violations.append(f"{path.relative_to(ROOT)}: {found}")
    assert violations == []
