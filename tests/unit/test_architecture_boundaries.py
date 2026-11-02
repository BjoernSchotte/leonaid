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
        for path in sorted((ROOT / "src/leonaid" / layer).rglob("*.py")):
            forbidden = imported_roots(path) & FORBIDDEN_INFRASTRUCTURE
            modules = imported_modules(path)
            inward_violations = {
                module
                for module in modules
                if module.startswith(
                    (
                        "leonaid.adapters",
                        "leonaid.bootstrap",
                        "leonaid.entrypoints",
                        "leonaid.modules",
                    )
                )
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


def test_twenty_wire_fields_stay_inside_the_twenty_adapter() -> None:
    wire_fields = {
        "addressPostcode",
        "addressStreet1",
        "companyId",
        "firstName",
        "lastName",
        "leonaidMatchKey",
        "primaryEmail",
        "starting_after",
    }
    violations: list[str] = []
    roots = (
        ROOT / "src/leonaid/domain",
        ROOT / "src/leonaid/application",
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


def python_files(relative: str) -> list[Path]:
    return sorted((ROOT / "src/leonaid" / relative).rglob("*.py"))


def leonaid_imports(path: Path) -> set[str]:
    return {
        module
        for module in imported_modules(path)
        if module == "leonaid" or module.startswith("leonaid.")
    }


def test_platform_imports_no_business_module_bootstrap_or_process_code() -> None:
    violations = [
        f"{path.relative_to(ROOT)}: {module}"
        for path in python_files("platform")
        for module in leonaid_imports(path)
        if not module.startswith(("leonaid.platform", "leonaid.domain"))
    ]
    assert violations == []


def test_modules_import_neither_bootstrap_nor_process_entrypoints() -> None:
    violations = [
        f"{path.relative_to(ROOT)}: {module}"
        for path in python_files("modules")
        for module in leonaid_imports(path)
        if module.startswith(("leonaid.bootstrap", "leonaid.entrypoints"))
    ]
    assert violations == []


def module_name(path: Path) -> str:
    return path.relative_to(ROOT / "src/leonaid/modules").parts[0]


def test_modules_use_only_the_public_api_of_other_modules() -> None:
    violations: list[str] = []
    for path in python_files("modules"):
        if path.parent == ROOT / "src/leonaid/modules":
            continue
        owner = module_name(path)
        for imported in leonaid_imports(path):
            parts = imported.split(".")
            if parts[:2] != ["leonaid", "modules"] or len(parts) < 3:
                continue
            if parts[2] != owner and parts[3:] != ["api"]:
                violations.append(f"{path.relative_to(ROOT)}: {imported}")
    assert violations == []


def test_module_dependencies_are_acyclic() -> None:
    edges: dict[str, set[str]] = {}
    for path in python_files("modules"):
        if path.parent == ROOT / "src/leonaid/modules":
            continue
        owner = module_name(path)
        for imported in leonaid_imports(path):
            parts = imported.split(".")
            if parts[:2] == ["leonaid", "modules"] and len(parts) > 2:
                if parts[2] != owner:
                    edges.setdefault(owner, set()).add(parts[2])
    finished: set[str] = set()

    def visit(name: str, path: tuple[str, ...]) -> None:
        assert name not in path, " -> ".join((*path, name))
        if name in finished:
            return
        for dependency in sorted(edges.get(name, ())):
            visit(dependency, (*path, name))
        finished.add(name)

    for name in sorted(edges):
        visit(name, ())


def test_only_process_entrypoints_import_bootstrap() -> None:
    violations = [
        f"{path.relative_to(ROOT)}: {module}"
        for layer in ("domain", "application", "adapters", "platform", "modules")
        for path in python_files(layer)
        for module in leonaid_imports(path)
        if module.startswith("leonaid.bootstrap")
    ]
    assert violations == []
