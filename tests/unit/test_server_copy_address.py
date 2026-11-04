"""Server texts that several surfaces show use a neutral address.

API error messages reach the back office and public pages ("Sie") as well
as the acquisition PWA ("du"), often through the same endpoint. The server
therefore words them without a personal address ("Bitte erneut
versuchen.", "Für … fehlt die Berechtigung."). Clients that want a personal
address map the stable error code per surface (see `actionErrorMessage`).

The member mail builders are the only exception: login code, invitation
and e-mail change mails address members with "du", like the member sign-in
pages (Björn, 2026-11-04). Mails to non-members use "Sie"; see
test_mail_address.py.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "src" / "leonaid"

# Member mails: "du" by decision (see the module docstring).
MAIL_BUILDERS = {
    ("application/email_changes.py", "_request_mail_events"),
    ("application/email_changes.py", "_completion_mail_events"),
    ("application/invitations.py", "_mail_event"),
    ("application/sessions.py", "_mail_event"),
}

# Informal pronouns as whole words ("Dublin", "Produkt" do not match).
PRONOUNS = re.compile(
    r"\b(du|dich|dir|dein\w*|euch|euer|eure\w*)\b",
    re.I,
)
IMPERATIVES = (
    "lade|lad|gib|vergib|prüfe|prüf|versuche|wähle|trage|nenne|melde|öffne|"
    "fordere|nutze|verwende|ergänze|hinterlege|entscheide|speichere|starte|"
    "kontaktiere|informiere|lege|wende|sende|schicke|schließe|gleiche|"
    "aktualisiere|warte|füge|ändere|entferne|lösche|korrigiere|wiederhole|"
    "kläre|erstelle|kopiere|antworte|bestätige|achte|beachte|schau|sieh|lies|"
    "stelle|setze|nimm|lass|klicke"
)
# A du-imperative at a clause start: text or sentence start, after
# "Bitte", after "und"/"oder" or after a comma, followed by another word.
IMPERATIVE = re.compile(
    rf"(?:^|[.!?:;]\s+|\bBitte\s+|\b(?:und|oder)\s+|,\s+)(?:{IMPERATIVES})\b(?=\s+\w)",
    re.I,
)


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
    if " " not in text:
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


@pytest.mark.parametrize(
    "text",
    [
        "Bitte lade den Beleg neu.",
        "Du darfst die Rechnungen nicht einsehen.",
        "Die Sitzung ist abgelaufen. Melde dich erneut an.",
        # Former misses: no umlaut and no stop word.
        "Du kannst nur deine eigenen Akquise-Bestellungen aufrufen.",
        "Du darfst Mitglieder nur in selbst verwalteten Aktionen einsehen.",
        "Von dir dokumentierte Kontakte in dieser Charity-Aktion.",
        # Former misses: imperative without an article after it.
        "Prüfe Berechtigung, Eingaben und Anmeldung.",
        "Den Code kopieren. Wiederhole erst danach die betroffene Aktion.",
        # Mid-sentence imperative after a conjunction or comma.
        "Die Liste ist veraltet und prüfe sie bitte erneut.",
        "Der Stand hat sich geändert, lade ihn neu.",
        "Ihr habt das schon, schickt es euch zu.",
    ],
)
def test_the_check_catches_informal_texts(text: str) -> None:
    assert _personal(text)


@pytest.mark.parametrize(
    "text",
    [
        "Zu viele Versuche. Bitte kurz warten und erneut versuchen.",
        "Bitte den Beleg neu laden.",
        "Bitte versuchen Sie es erneut.",
        "Lieferung nach Dublin ist nicht möglich.",
        "Das Produkt ist durch den Import dauerhaft gesperrt.",
        "Selbst dokumentierte Kontakte in dieser Charity-Aktion.",
    ],
)
def test_the_check_accepts_neutral_texts(text: str) -> None:
    assert not _personal(text)


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
