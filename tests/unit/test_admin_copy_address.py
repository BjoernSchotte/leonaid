"""Admin-only server texts address the reader with "Sie".

The system admin screens show the server's error message verbatim
(`actionErrorMessage`). These modules serve only system-admin endpoints,
so their German texts must not use the "du" address of the PWA.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from leonaid.adapters.postgres import feature_flags as postgres_feature_flags
from leonaid.adapters.postgres import legal_configuration as postgres_legal
from leonaid.application import legal_configuration, privacy

ADMIN_ONLY_MODULES = (
    legal_configuration,
    postgres_legal,
    privacy,
    postgres_feature_flags,
)

# Pronouns and the imperatives these modules used before the reword.
DU_FORMS = re.compile(
    r"\b(du|dich|dir|dein\w*|Lade|Bestätige|Gib|Prüfe|Versuche|versuche|"
    r"Wähle|Trage|Nenne)\b"
)


def _string_literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


@pytest.mark.parametrize(
    "module", ADMIN_ONLY_MODULES, ids=lambda module: module.__name__
)
def test_admin_only_texts_use_sie(module: object) -> None:
    path = Path(module.__file__)  # type: ignore[attr-defined]
    offenders = [
        f"{path.name}:{line}: {text}"
        for line, text in _string_literals(path)
        if DU_FORMS.search(text)
    ]
    assert offenders == []


def test_reworded_conflict_texts_are_pinned() -> None:
    texts = {
        text
        for module in ADMIN_ONLY_MODULES
        for _line, text in _string_literals(Path(module.__file__))
    }
    for expected in (
        "Bitte laden Sie die Konfiguration neu und versuchen Sie es erneut.",
        "Die Konfiguration wurde zwischenzeitlich geändert. Bitte laden Sie sie neu.",
        "Bitte geben Sie einen kurzen, nachvollziehbaren Sperrgrund an.",
        "Bitte bestätigen Sie die Löschung mit der exakt eingegebenen E-Mail-Adresse.",
        "Das Feature-Flag wurde zwischenzeitlich geändert. "
        "Bitte laden Sie den aktuellen Stand neu.",
    ):
        assert expected in texts
