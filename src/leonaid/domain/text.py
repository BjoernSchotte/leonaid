"""Checks for short, single-line text that people type into forms.

Names and addresses end up in mails, PDFs and admin lists. A line break or
an invisible format character (for example a bidi override such as U+202E)
in such a field can add a convincing paragraph to a mail or disguise an IBAN
or a link. Input refuses them; output strips them from data stored before.
"""

from __future__ import annotations

import unicodedata

# Control (Cc), format (Cf, including bidi controls and zero-width
# characters) and the Unicode line and paragraph separators.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})
_LINE_BREAKS = frozenset("\n\r\t")


def has_unsafe_characters(value: str, *, allow_line_breaks: bool = False) -> bool:
    """True when the text holds a control, format or line separator character.

    ``allow_line_breaks`` permits newline, carriage return and tab, for free
    text that may span lines (a message), never for a name or an address.
    """

    return any(
        unicodedata.category(character) in _UNSAFE_CATEGORIES
        and not (allow_line_breaks and character in _LINE_BREAKS)
        for character in value
    )


def single_line(value: str) -> str:
    """One line of plain text: format characters dropped, whitespace collapsed.

    Control characters and separators become spaces, so "a\\nb" stays two
    words on one line.
    """

    cleaned = "".join(
        ""
        if unicodedata.category(character) == "Cf"
        else " "
        if unicodedata.category(character) in _UNSAFE_CATEGORIES
        else character
        for character in value
    )
    return " ".join(cleaned.split())
