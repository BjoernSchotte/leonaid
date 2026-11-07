"""Core and the frontends share the two base paths (specs/multi-domain §6.7)."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

from leonaid.platform.base_paths import ADMIN_BASE, PWA_BASE

ROOT = Path(__file__).resolve().parents[2]


def test_typescript_and_python_base_paths_are_equal() -> None:
    source = (ROOT / "packages/ui/src/lib/base-paths.ts").read_text(encoding="utf-8")
    values = dict(re.findall(r'export const (\w+) = "([^"]+)";', source))
    assert values == {"ADMIN_BASE": ADMIN_BASE, "PWA_BASE": PWA_BASE}


def test_caddy_route_table_reads_the_core_constants() -> None:
    spec = importlib.util.spec_from_file_location(
        "caddyfiles", ROOT / "tools/proxy/caddyfiles.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Dataclasses need their module in sys.modules while it executes.
    sys.modules["caddyfiles"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules["caddyfiles"]
    assert (module.ADMIN_BASE, module.PWA_BASE) == (ADMIN_BASE, PWA_BASE)


def test_base_paths_are_distinct_root_segments() -> None:
    for base in (ADMIN_BASE, PWA_BASE):
        assert re.fullmatch(r"/[a-z][a-z0-9-]*/", base)
    assert ADMIN_BASE != PWA_BASE
