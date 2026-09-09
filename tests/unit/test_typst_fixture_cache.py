"""Cached seed PDFs must invalidate on inputs, image changes or damaged output."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from tools.typst import render_fixtures


def test_seed_pdf_cache_validates_inputs_renderer_and_bytes(tmp_path: Path) -> None:
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    fixture = source / "KT26-001.json"
    fixture.write_text("original")
    calls = []

    def render(source: Path, output: Path) -> list[dict[str, object]]:
        calls.append(1)
        content = fixture.read_bytes()
        (output / "invoice.pdf").unlink(missing_ok=True)
        (output / "invoice.pdf").write_bytes(content)
        manifest: list[dict[str, object]] = [
            {
                "filename": "invoice.pdf",
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ]
        (output / "render-manifest.json").write_text(json.dumps(manifest))
        return manifest

    with patch.object(render_fixtures, "render_directory", side_effect=render):
        render_fixtures.cached_manifest(source, output, "image-one")
        render_fixtures.cached_manifest(source, output, "image-one")
        assert len(calls) == 1
        (output / "invoice.pdf").write_bytes(b"damaged")
        render_fixtures.cached_manifest(source, output, "image-one")
        assert len(calls) == 2
        fixture.write_text("changed input")
        render_fixtures.cached_manifest(source, output, "image-one")
        assert len(calls) == 3
        render_fixtures.cached_manifest(source, output, "image-two")
        assert len(calls) == 4
        (output / "render-manifest.json").write_text("[]")
        render_fixtures.cached_manifest(source, output, "image-two")
        assert len(calls) == 5
        (output / "invoice.pdf").unlink()
        (output / "invoice.pdf").symlink_to(fixture)
        render_fixtures.cached_manifest(source, output, "image-two")
        assert len(calls) == 6
