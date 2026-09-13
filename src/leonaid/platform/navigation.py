"""Transport-neutral navigation contribution contract."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NavigationItem:
    key: str
    label: str
    href: str
    surface: str
