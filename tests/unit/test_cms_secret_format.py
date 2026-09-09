"""Real-file checks for EmDash key creation and lossless legacy representation."""

import base64
import subprocess
import sys
from pathlib import Path


def test_cms_key_conversion_preserves_material_and_other_values(tmp_path: Path) -> None:
    template = tmp_path / "template"
    output = tmp_path / "environment"
    template.write_text(
        "CMS_ENCRYPTION_KEY=emdash_enc_v1___GENERATE_URLSAFE_32__\nUNCHANGED=value\n"
    )
    original = bytes(range(32))
    output.write_text(f"CMS_ENCRYPTION_KEY={original.hex()}\nUNCHANGED=keep-me\n")
    script = Path(__file__).resolve().parents[2] / "tools/dx/generate_secrets.py"
    subprocess.run(
        [sys.executable, str(script), str(template), str(output)],
        check=True,
        capture_output=True,
    )
    rendered = output.read_text()
    key = rendered.splitlines()[0].split("=", 1)[1]
    assert key.startswith("emdash_enc_v1_")
    assert (
        base64.urlsafe_b64decode(key.removeprefix("emdash_enc_v1_") + "=") == original
    )
    assert "UNCHANGED=keep-me\n" in rendered
    subprocess.run(
        [sys.executable, str(script), str(template), str(output)],
        check=True,
        capture_output=True,
    )
    assert output.read_text() == rendered


def test_new_cms_key_has_32_bytes_and_versioned_prefix(tmp_path: Path) -> None:
    template = tmp_path / "template"
    output = tmp_path / "environment"
    template.write_text("CMS_ENCRYPTION_KEY=emdash_enc_v1___GENERATE_URLSAFE_32__\n")
    script = Path(__file__).resolve().parents[2] / "tools/dx/generate_secrets.py"
    subprocess.run(
        [sys.executable, str(script), str(template), str(output)],
        check=True,
        capture_output=True,
    )
    key = output.read_text().strip().split("=", 1)[1]
    assert key.startswith("emdash_enc_v1_")
    assert len(base64.urlsafe_b64decode(key.removeprefix("emdash_enc_v1_") + "=")) == 32
