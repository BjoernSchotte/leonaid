"""Validate persisted seed receipts and files without replacing the renderer."""

import hashlib
import json
from pathlib import Path

from tools.typst.render_fixtures import fixture_cache_key, read_cached_manifest


def test_seed_pdf_cache_validates_inputs_renderer_and_bytes(tmp_path: Path) -> None:
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    fixture = source / "KT26-001.json"
    fixture.write_text("original")
    pdf = output / "invoice.pdf"
    pdf.write_bytes(b"synthetic persisted output")
    manifest = [
        {"filename": pdf.name, "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()}
    ]
    manifest_path = output / "render-manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    original_key = fixture_cache_key(source, "image-one")
    (output / ".render-cache.json").write_text(
        json.dumps(
            {
                "key": original_key,
                "manifestSha256": hashlib.sha256(
                    manifest_path.read_bytes()
                ).hexdigest(),
            }
        )
    )
    assert read_cached_manifest(output, original_key) == manifest
    assert read_cached_manifest(output, fixture_cache_key(source, "image-two")) is None
    fixture.write_text("changed input")
    assert read_cached_manifest(output, fixture_cache_key(source, "image-one")) is None
    pdf.write_bytes(b"damaged")
    assert read_cached_manifest(output, original_key) is None
    pdf.write_bytes(b"synthetic persisted output")
    assert read_cached_manifest(output, original_key) == manifest
    manifest_path.write_text("[]")
    assert read_cached_manifest(output, original_key) is None
    manifest_path.write_text(json.dumps(manifest))
    pdf.unlink()
    assert read_cached_manifest(output, original_key) is None
    pdf.symlink_to(fixture)
    assert read_cached_manifest(output, original_key) is None
