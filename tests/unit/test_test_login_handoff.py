from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.dx.generate_test_logins import (
    LOGIN_PERSONAS,
    check_test_logins,
    load_dataset,
    render_test_logins,
    write_test_logins,
)


ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DATASET = ROOT / "tests/fixtures/golden/v1/dataset.json"


def test_renders_every_internal_poc_persona_from_golden_data() -> None:
    content = render_test_logins(load_dataset(GOLDEN_DATASET))

    for persona in LOGIN_PERSONAS:
        assert f"## {persona.heading}" in content
        assert f"`{persona.email}`" in content
        assert persona.destination_url in content
    assert "## Öffentlicher Besteller oder Sponsor" in content
    assert "Kein Login erforderlich" in content
    assert "http://127.0.0.1:8080/mail/" in content
    assert "sechsstelligen Code" in content


def test_writes_private_deterministic_local_handoff(tmp_path: Path) -> None:
    output = tmp_path / "test-logins.md"

    write_test_logins(GOLDEN_DATASET, output)
    first_content = output.read_bytes()
    write_test_logins(GOLDEN_DATASET, output)

    assert output.read_bytes() == first_content
    assert output.stat().st_mode & 0o777 == 0o600
    check_test_logins(GOLDEN_DATASET, output)


def test_rejects_missing_or_misconfigured_persona(tmp_path: Path) -> None:
    dataset = load_dataset(GOLDEN_DATASET)
    dataset["users"] = [
        user
        for user in dataset["users"]
        if user["email"] != "finn.finanzen@leonaid.invalid"
    ]
    corrupted = tmp_path / "dataset.json"
    corrupted.write_text(json.dumps(dataset), encoding="utf-8")

    with pytest.raises(ValueError, match="Golden-Login fehlt"):
        render_test_logins(load_dataset(corrupted))
