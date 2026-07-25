from __future__ import annotations

import ast
from pathlib import Path

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


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_domain_and_application_do_not_import_concrete_infrastructure() -> None:
    violations: list[str] = []
    for layer in ("domain", "application"):
        for path in sorted((ROOT / "src/leonaid" / layer).glob("*.py")):
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
