from __future__ import annotations

from pathlib import Path

import pytest

from tools.openapi.check_frontend import violations


def test_frontend_boundary_rejects_direct_fetch_and_generated_import(
    tmp_path: Path,
) -> None:
    source = tmp_path / "feature.ts"
    source.write_text(
        """
        import type { ApiErrorResponse } from "../api-client/src/generated";
        export const load = () => fetch("/api/v1/platform");
        """,
        encoding="utf-8",
    )

    problems = violations((tmp_path,))

    assert len(problems) == 2
    assert "direkter API-fetch" in problems[0]
    assert "generiertes Transportartefakt" in problems[1]


@pytest.mark.parametrize(
    ("filename", "route"),
    [
        ("client.tsx", '"/api/participation"'),
        ("client.tsx", '"/api/diagnostics"'),
        ("editor.tsx", '"/api/editor"'),
        ("exports.tsx", '"/api/exports"'),
        ("exports.tsx", '"/api/export-source"'),
        ("exports.tsx", "`/api/exports/${encodeURIComponent(id)}`"),
        ("exports.tsx", "`/api/exports/${encodeURIComponent(id)}/download`"),
    ],
)
def test_independent_host_uses_only_its_reviewed_routes(
    tmp_path: Path, filename: str, route: str
) -> None:
    source = tmp_path / filename
    source.write_text(f"fetch({route}, {{}});", encoding="utf-8")
    client = tmp_path / "client.tsx"
    assert violations((tmp_path,), independent_client=client) == []
    assert violations((tmp_path,))


@pytest.mark.parametrize(
    ("filename", "expression"),
    [
        ("editor.tsx", 'fetch("/api/v1/surveys")'),
        ("exports.tsx", 'fetch("/api/v1/platform")'),
        ("exports.tsx", 'fetch("/api/exports/unreviewed")'),
        ("exports.tsx", "fetch(`/api/exports/${id}`)"),
        ("exports.tsx", "fetch(`/api/exports/${encodeURIComponent(id)}/other`)"),
        ("editor.tsx", 'fetch("/api/participation")'),
        ("unreviewed.tsx", 'fetch("/api/editor")'),
        ("editor.tsx", 'import type { X } from "../api-client/src/generated"'),
    ],
)
def test_independent_host_does_not_bypass_leonaid_boundary(
    tmp_path: Path, filename: str, expression: str
) -> None:
    (tmp_path / filename).write_text(expression, encoding="utf-8")
    assert violations((tmp_path,), independent_client=tmp_path / "client.tsx")
