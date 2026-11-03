"""Navigation contributed by the surveys module."""

from __future__ import annotations

from leonaid.domain.identity import IdentityPrincipal
from leonaid.platform.navigation import NavigationItem


def navigation(principal: IdentityPrincipal) -> tuple[NavigationItem, ...]:
    # Every signed-in account may author surveys; the survey routes check
    # access. The PWA links to the shared web editor instead of shipping one.
    if not principal.account.can_authenticate:
        return ()
    return tuple(
        NavigationItem("surveys", "Umfragen", "/admin/surveys", surface)
        for surface in ("web", "pwa")
    )
