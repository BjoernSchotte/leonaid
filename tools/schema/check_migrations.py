#!/usr/bin/env python3
"""Reject unaccompanied destructive operations in forward migrations."""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

DESTRUCTIVE_OPERATIONS = {"drop_column", "drop_constraint", "drop_table"}
REQUIRED_REFERENCES = {"BACKUP_REFERENCE", "DATA_MIGRATION_REFERENCE"}


def assignment_strings(tree: ast.Module) -> dict[str, str]:
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            values[target.id] = node.value.value
    return values


def operation_name(call: ast.Call) -> str | None:
    function = call.func
    if (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id == "op"
    ):
        return function.attr
    return None


def upgrade_function(tree: ast.Module) -> ast.FunctionDef | None:
    return next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
        ),
        None,
    )


def check_file(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as error:
        return [
            f"{path}: nicht lesbar oder syntaktisch ungültig: {type(error).__name__}"
        ]
    upgrade = upgrade_function(tree)
    if upgrade is None:
        return [f"{path}: upgrade() fehlt"]
    destructive: set[str] = set()
    for node in ast.walk(upgrade):
        if not isinstance(node, ast.Call):
            continue
        name = operation_name(node)
        if name in DESTRUCTIVE_OPERATIONS:
            destructive.add(str(name))
        if name == "execute" and node.args:
            first = node.args[0]
            if (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and "DROP " in first.value.upper()
            ):
                destructive.add("raw_sql_drop")
    if not destructive:
        return []
    references = assignment_strings(tree)
    missing = sorted(
        name for name in REQUIRED_REFERENCES if not references.get(name, "").strip()
    )
    if missing:
        return [
            f"{path}: destruktive Vorwärtsmigration {sorted(destructive)} "
            f"ohne {missing}"
        ]
    return []


def check_directory(directory: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("__"):
            continue
        problems.extend(check_file(path))
    if not list(directory.glob("*.py")):
        problems.append(f"{directory}: keine Migrationen gefunden")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "directory",
        type=Path,
        nargs="?",
        default=Path("migrations/versions"),
    )
    arguments = parser.parse_args()
    problems = check_directory(arguments.directory)
    if problems:
        for problem in problems:
            print(f"migration-policy: ERROR: {problem}", file=sys.stderr)
        return 1
    print("migration-policy: OK: keine unbelegte destruktive Vorwärtsmigration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
