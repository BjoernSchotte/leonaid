"""Navigation contributed by the surveys module."""

from __future__ import annotations

from leonaid.domain.identity import IdentityPrincipal
from leonaid.platform.navigation import NavigationItem


def navigation(_principal: IdentityPrincipal) -> tuple[NavigationItem, ...]:
    # Every signed-in account may author surveys; the survey routes check access.
    return (NavigationItem("surveys", "Umfragen", "/admin/surveys", "web"),)
