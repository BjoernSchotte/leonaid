"""Checks for short, single-line text that people type into forms.

Names and addresses end up in mails, PDFs and admin lists. A line break or
an invisible format character (for example a bidi override such as U+202E)
in such a field can add a convincing paragraph to a mail or disguise an IBAN
or a link. Input refuses them; output strips them from data stored before.
"""

from __future__ import annotations

import unicodedata

# Control (Cc), format (Cf, including bidi controls and zero-width
# characters), surrogates (Cs: a lone one cannot even be stored as UTF-8),
# private use (Co), unassigned (Cn) and the Unicode line and paragraph
# separators.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
# Letters and symbols that render as nothing: a "name" made of them looks
# blank, or pads text to push it out of view.
BLANK_CHARACTERS = frozenset(
    {
        "ᅟ",  # Hangul choseong filler
        "ᅠ",  # Hangul jungseong filler
        "⠀",  # Braille pattern blank
        "ㅤ",  # Hangul filler
        "ﾠ",  # Halfwidth Hangul filler
    }
)
_LINE_BREAKS = frozenset("\n\r\t")
# What turns a name or an address line into a link or a mail address in a
# mail client. Real names and addresses never contain these.
_LINK_MARKERS = ("://", "www.", "@")


def has_unsafe_characters(value: str, *, allow_line_breaks: bool = False) -> bool:
    """True when the text holds a control, format, surrogate, private-use,
    unassigned, line separator or visually blank character.

    ``allow_line_breaks`` permits newline, carriage return and tab, for free
    text that may span lines (a message), never for a name or an address.
    """

    return any(
        (
            unicodedata.category(character) in _UNSAFE_CATEGORIES
            or character in BLANK_CHARACTERS
        )
        and not (allow_line_breaks and character in _LINE_BREAKS)
        for character in value
    )


def has_link_markers(value: str) -> bool:
    """True when a name or address line holds a URL or a mail address."""

    lowered = value.casefold()
    return any(marker in lowered for marker in _LINK_MARKERS)


def single_line(value: str) -> str:
    """One line of plain text: hidden characters dropped, whitespace collapsed.

    Control characters and separators become spaces, so "a\\nb" stays two
    words on one line; format, surrogate, private-use, unassigned and blank
    characters are dropped.
    """

    def keep(character: str) -> str:
        category = unicodedata.category(character)
        if category in {"Cc", "Zl", "Zp"}:
            return " "
        if category in _UNSAFE_CATEGORIES or character in BLANK_CHARACTERS:
            return ""
        return character

    return " ".join("".join(keep(character) for character in value).split())
