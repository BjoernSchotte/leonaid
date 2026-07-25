from __future__ import annotations

from pathlib import Path

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
