"""Server texts that several surfaces show use a neutral address.

API error messages reach the back office and public pages ("Sie") as well
as the acquisition PWA ("du"), often through the same endpoint. The server
therefore words them without a personal address ("Bitte erneut
versuchen.", "Für … fehlt die Berechtigung."). Clients that want a personal
address map the stable error code per surface (see `actionErrorMessage`).

The mail builders are the only exception: their address is a product
decision per recipient and is listed in MAIL_BUILDERS until it is taken.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src" / "leonaid"

# Mail bodies and subjects keep their current address (open decision).
MAIL_BUILDERS = {
    ("application/email_changes.py", "_request_mail_events"),
    ("application/email_changes.py", "_completion_mail_events"),
    ("application/invitations.py", "_mail_event"),
    ("application/sessions.py", "_mail_event"),
}

PRONOUNS = re.compile(r"\b(du|dich|dir|dein|deine|deinen|deinem|deiner|deines)\b", re.I)
IMPERATIVES = (
    "lade|gib|prüfe|versuche|wähle|trage|nenne|melde|öffne|fordere|nutze|"
    "ergänze|hinterlege|entscheide|speichere|starte|kontaktiere|lege|wende|"
    "sende|schließe|gleiche|aktualisiere|warte|füge|ändere|entferne|"
    "korrigiere|wiederhole|kläre|erstelle|kopiere|antworte|bestätige"
)
# An imperative at a sentence start or after "Bitte", followed by its object.
IMPERATIVE = re.compile(
    rf"(?:^|[.!?:]\s+|\bBitte\s+)(?:{IMPERATIVES})\s+"
    r"(es|den|die|das|dem|einen|eine|sie|ihn|kurz|erneut|denselben|dieselbe)\b",
    re.I,
)
GERMAN = re.compile(r"[äöüß]|\b(der|die|das|und|nicht|bitte|ist|für)\b", re.I)


def _docstrings(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = node.body
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    found.add(id(value))
    return found


def _texts(path: Path) -> list[tuple[int, str, str | None]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstrings(tree)
    owner: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                owner.setdefault(id(child), node.name)
    texts: list[tuple[int, str, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                part.value if isinstance(part, ast.Constant) else "{}"
                for part in node.values
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in skip:
                continue
            text = node.value
        else:
            continue
        texts.append((node.lineno, text, owner.get(id(node))))
    return texts


def _personal(text: str) -> bool:
    if " " not in text or not GERMAN.search(text):
        return False
    return bool(PRONOUNS.search(text) or IMPERATIVE.search(text))


def test_server_texts_have_no_du_address() -> None:
    offenders = []
    for path in sorted(SOURCE.rglob("*.py")):
        relative = path.relative_to(SOURCE).as_posix()
        for line, text, function in _texts(path):
            if (relative, function) in MAIL_BUILDERS:
                continue
            if _personal(text):
                offenders.append(f"{relative}:{line}: {text[:100]!r}")
    assert offenders == []


def test_the_check_catches_both_forms() -> None:
    assert _personal("Bitte lade den Beleg neu.")
    assert _personal("Du darfst die Rechnungen nicht einsehen.")
    assert _personal("Die Sitzung ist abgelaufen. Melde dich erneut an.") is True
    assert not _personal("Zu viele Versuche. Bitte kurz warten und erneut versuchen.")
    assert not _personal("Bitte den Beleg neu laden.")
    assert not _personal("Bitte versuchen Sie es erneut.")


def test_mail_builders_exist() -> None:
    """Fails when a listed mail builder moves, so the exemption stays exact."""
    for relative, function in MAIL_BUILDERS:
        tree = ast.parse((SOURCE / relative).read_text(encoding="utf-8"))
        names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert function in names, f"{relative}:{function}"
