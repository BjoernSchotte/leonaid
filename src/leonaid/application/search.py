"""Role-filtered core search across actions, orders, invoices and members.

Module objects (tasks, knowledge pages, materials, inbox cases) are searched by
their own modules. Sponsors live in Twenty and LeonAid keeps no local copy of
them, so they are not searched here; a CRM call per keystroke is not an option.

Every scope comes from the same policies that guard the list endpoints, so a
result never shows an object the account could not open there.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from leonaid.application.errors import PermissionDenied
from leonaid.application.identity import STATUS_LABELS, member_directory_scope
from leonaid.application.invoices import may_read_all_invoices, may_read_invoices
from leonaid.domain.actions import CharityActionStatus
from leonaid.domain.commitments import CommitmentStatus
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import AccountStatus, IdentityPrincipal
from leonaid.domain.policies import may_manage_action

SEARCH_QUERY_MIN_LENGTH = 2
SEARCH_QUERY_MAX_LENGTH = 80
SEARCH_LIMIT_DEFAULT = 8
SEARCH_LIMIT_MAX = 20


class SearchResultType(StrEnum):
    ACTION = "action"
    ORDER = "order"
    INVOICE = "invoice"
    # Part of the contract for the palette; not produced while sponsors exist
    # only in Twenty (see module docstring).
    SPONSOR = "sponsor"
    MEMBER = "member"


# Equal-rank results are grouped in this order.
TYPE_ORDER: dict[SearchResultType, int] = {
    kind: index for index, kind in enumerate(SearchResultType)
}

ACTION_STATUS_LABELS: dict[CharityActionStatus, str] = {
    CharityActionStatus.DRAFT: "Entwurf",
    CharityActionStatus.SCHEDULED: "Geplant",
    CharityActionStatus.ACTIVE: "Aktiv",
    CharityActionStatus.COMPLETED: "Abgeschlossen",
    CharityActionStatus.ARCHIVED: "Archiviert",
}

ORDER_STATUS_LABELS: dict[CommitmentStatus, str] = {
    CommitmentStatus.DRAFT: "Entwurf",
    CommitmentStatus.REVIEW_READY: "Prüfbereit",
    CommitmentStatus.CONFIRMED: "Bestätigt",
    CommitmentStatus.INVOICED: "Fakturiert",
    CommitmentStatus.CANCELLED: "Storniert",
}


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """User input, trimmed and with inner whitespace collapsed."""

    text: str
    limit: int = SEARCH_LIMIT_DEFAULT

    def __post_init__(self) -> None:
        normalized = " ".join(self.text.split())
        if not SEARCH_QUERY_MIN_LENGTH <= len(normalized) <= SEARCH_QUERY_MAX_LENGTH:
            raise DomainInvariantError(
                "search_query_invalid",
                f"Der Suchbegriff muss {SEARCH_QUERY_MIN_LENGTH} bis "
                f"{SEARCH_QUERY_MAX_LENGTH} Zeichen lang sein.",
            )
        if not 1 <= self.limit <= SEARCH_LIMIT_MAX:
            raise DomainInvariantError(
                "search_limit_invalid",
                f"Es sind 1 bis {SEARCH_LIMIT_MAX} Suchtreffer möglich.",
            )
        object.__setattr__(self, "text", normalized)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def contains_pattern(text: str) -> str:
    """An ILIKE pattern (escape character ``\\``) matching ``text`` anywhere."""

    return f"%{_escape_like(text)}%"


def prefix_pattern(text: str) -> str:
    """An ILIKE pattern (escape character ``\\``) matching ``text`` at the start."""

    return f"{_escape_like(text)}%"


@dataclass(frozen=True, slots=True)
class ActionScope:
    """A set of readable actions, or all of them."""

    all_actions: bool = False
    action_ids: frozenset[UUID] = field(default_factory=frozenset)

    @classmethod
    def everything(cls) -> ActionScope:
        return cls(all_actions=True)

    @classmethod
    def of(cls, action_ids: set[UUID] | frozenset[UUID]) -> ActionScope:
        return cls(action_ids=frozenset(action_ids))

    @property
    def is_empty(self) -> bool:
        return not self.all_actions and not self.action_ids

    def allows(self, action_id: UUID) -> bool:
        return self.all_actions or action_id in self.action_ids


NO_ACTIONS = ActionScope()


@dataclass(frozen=True, slots=True)
class SearchScope:
    actions: ActionScope
    orders: ActionScope
    invoices: ActionScope
    # Members with a current membership in these actions.
    members: ActionScope

    @property
    def is_empty(self) -> bool:
        return all(
            part.is_empty
            for part in (self.actions, self.orders, self.invoices, self.members)
        )


def _scope_where(
    actor: IdentityPrincipal,
    *,
    all_actions: bool,
    allows: Callable[[IdentityPrincipal, UUID], bool],
) -> ActionScope:
    if all_actions:
        return ActionScope.everything()
    return ActionScope.of(
        {
            membership.action_id
            for membership in actor.action_memberships
            if allows(actor, membership.action_id)
        }
    )


def search_scope(actor: IdentityPrincipal) -> SearchScope:
    """Readable actions per result type, taken from the central policies.

    Actions and orders follow the action-management policy of
    ``GET /actions/{id}`` and ``GET /actions/{id}/commitments``, invoices the
    finance read policy of ``GET /actions/{id}/invoices`` and members the
    scope of the member directory.
    """

    if not actor.account.can_authenticate:
        return SearchScope(NO_ACTIONS, NO_ACTIONS, NO_ACTIONS, NO_ACTIONS)
    managed = _scope_where(
        actor,
        all_actions=actor.is_system_admin,
        allows=may_manage_action,
    )
    invoices = _scope_where(
        actor,
        all_actions=may_read_all_invoices(actor),
        allows=may_read_invoices,
    )
    try:
        member_actions = member_directory_scope(actor)
    except PermissionDenied:
        members = NO_ACTIONS
    else:
        members = (
            ActionScope.everything()
            if member_actions is None
            else ActionScope.of(set(member_actions))
        )
    return SearchScope(
        actions=managed,
        orders=managed,
        invoices=invoices,
        members=members,
    )


@dataclass(frozen=True, slots=True)
class SearchCriteria:
    contains: str
    prefix: str
    limit: int
    scope: SearchScope
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One stored match; the repository returns at most ``limit`` per type.

    ``position`` is the row's place in its type's result (prefix matches
    first, then by title in the database collation). The merge keeps that
    order, so the merged top results are always among the fetched rows.
    """

    type: SearchResultType
    id: UUID
    action_id: UUID | None
    title: str
    position: int
    prefix_match: bool
    status: str | None = None
    detail: str | None = None
    action_name: str | None = None


class SearchRepository(Protocol):
    async def search(self, criteria: SearchCriteria) -> tuple[SearchHit, ...]: ...


@dataclass(frozen=True, slots=True)
class SearchResult:
    id: UUID
    type: SearchResultType
    title: str
    context: str
    href: str


def _context(*parts: str | None) -> str:
    return " · ".join(part for part in parts if part)


def _result(hit: SearchHit) -> SearchResult:
    match hit.type:
        case SearchResultType.ACTION:
            context = ACTION_STATUS_LABELS[CharityActionStatus(str(hit.status))]
            href = f"/admin/actions/{hit.action_id}"
        case SearchResultType.ORDER:
            context = _context(
                hit.detail,
                hit.action_name,
                ORDER_STATUS_LABELS[CommitmentStatus(str(hit.status))],
            )
            href = f"/admin/orders?action={hit.action_id}"
        case SearchResultType.INVOICE:
            context = _context(hit.detail, hit.action_name)
            # The invoice list opens the hit in its pane, in the view that
            # shows every status.
            href = f"/admin/invoices?action={hit.action_id}&view=all&open={hit.id}"
        case SearchResultType.MEMBER:
            status = AccountStatus(str(hit.status))
            context = _context(
                hit.detail,
                None if status is AccountStatus.ACTIVE else STATUS_LABELS[status],
            )
            # The member list opens the hit in its pane.
            href = f"/admin/members?open={hit.id}"
        case _:
            raise ValueError(f"Unsupported core search result: {hit.type}")
    return SearchResult(
        id=hit.id,
        type=hit.type,
        title=hit.title,
        context=context,
        href=href,
    )


def _readable(hit: SearchHit, scope: SearchScope) -> bool:
    """Second check after the SQL scope: drop anything outside the policy."""

    if hit.type is SearchResultType.MEMBER:
        return not scope.members.is_empty
    allowed = {
        SearchResultType.ACTION: scope.actions,
        SearchResultType.ORDER: scope.orders,
        SearchResultType.INVOICE: scope.invoices,
    }.get(hit.type, NO_ACTIONS)
    return hit.action_id is not None and allowed.allows(hit.action_id)


class SearchService:
    def __init__(
        self,
        repository: SearchRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def search(
        self,
        actor: IdentityPrincipal,
        query: SearchQuery,
    ) -> tuple[SearchResult, ...]:
        scope = search_scope(actor)
        if scope.is_empty:
            return ()
        hits = await self._repository.search(
            SearchCriteria(
                contains=contains_pattern(query.text),
                prefix=prefix_pattern(query.text),
                limit=query.limit,
                scope=scope,
                evaluated_at=self._clock(),
            )
        )
        ranked = sorted(
            (hit for hit in hits if _readable(hit, scope)),
            key=lambda hit: (
                not hit.prefix_match,
                TYPE_ORDER[hit.type],
                hit.position,
            ),
        )
        return tuple(_result(hit) for hit in ranked[: query.limit])
