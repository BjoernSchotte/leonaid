"""Core search: query rules, role scopes from the central policies and merging."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from leonaid.application.invoices import may_read_invoices
from leonaid.application.search import (
    ActionScope,
    SearchCriteria,
    SearchHit,
    SearchQuery,
    SearchResultType,
    SearchService,
    contains_pattern,
    prefix_pattern,
    search_scope,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)
from leonaid.domain.policies import may_manage_action
from leonaid.entrypoints.fastapi.platform import create_app

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
ACTION_A = UUID("a0000000-0000-4000-8000-000000000001")
ACTION_B = UUID("b0000000-0000-4000-8000-000000000002")


def principal(
    *memberships: tuple[UUID, ActionRole],
    global_roles: frozenset[GlobalRole] = frozenset(),
    status: AccountStatus = AccountStatus.ACTIVE,
) -> IdentityPrincipal:
    user_id = uuid4()
    return IdentityPrincipal(
        account=UserAccount(user_id, f"{user_id}@example.test", "Klara", status),
        global_roles=global_roles,
        action_memberships=tuple(
            ActionMembership(
                id=uuid4(),
                action_id=action_id,
                action_name=f"Aktion {action_id}",
                user_id=user_id,
                role=role,
                active_from=NOW.replace(year=2025),
            )
            for action_id, role in memberships
        ),
    )


def hit(
    kind: SearchResultType,
    *,
    title: str,
    action_id: UUID | None = ACTION_A,
    prefix: bool = False,
    status: str | None = None,
    detail: str | None = None,
    action_name: str | None = "Krapfentaxi",
    position: int = 0,
) -> SearchHit:
    return SearchHit(
        type=kind,
        id=uuid4(),
        action_id=action_id,
        title=title,
        position=position,
        prefix_match=prefix,
        status=status,
        detail=detail,
        action_name=action_name,
    )


class RecordingRepository:
    def __init__(self, hits: tuple[SearchHit, ...] = ()) -> None:
        self.hits = hits
        self.criteria: list[SearchCriteria] = []

    async def search(self, criteria: SearchCriteria) -> tuple[SearchHit, ...]:
        self.criteria.append(criteria)
        return self.hits


# --- query rules -------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "a", " a ", "   ", "\t\n"])
def test_query_needs_two_visible_characters(raw: str) -> None:
    with pytest.raises(DomainInvariantError) as error:
        SearchQuery(raw)
    assert error.value.code == "search_query_invalid"


def test_query_is_trimmed_collapsed_and_bounded() -> None:
    assert SearchQuery("  Krapfen   Taxi ").text == "Krapfen Taxi"
    assert len(SearchQuery("x" * 80).text) == 80
    with pytest.raises(DomainInvariantError):
        SearchQuery("x" * 81)


@pytest.mark.parametrize("limit", [0, 21, -1])
def test_limit_stays_between_one_and_twenty(limit: int) -> None:
    with pytest.raises(DomainInvariantError) as error:
        SearchQuery("ab", limit)
    assert error.value.code == "search_limit_invalid"
    assert SearchQuery("ab").limit == 8


def test_like_wildcards_and_escape_characters_are_literal() -> None:
    assert contains_pattern("50%_a\\b") == "%50\\%\\_a\\\\b%"
    assert prefix_pattern("KT26_") == "KT26\\_%"


# --- scopes come from the same policies as the list endpoints ---------------


def test_system_admin_reads_every_core_type() -> None:
    scope = search_scope(principal(global_roles=frozenset({GlobalRole.SYSTEM_ADMIN})))
    assert scope.actions == ActionScope.everything()
    assert scope.orders == ActionScope.everything()
    assert scope.invoices == ActionScope.everything()
    assert scope.members == ActionScope.everything()


def test_charity_admin_reads_only_own_actions() -> None:
    actor = principal(
        (ACTION_A, ActionRole.CHARITY_ADMIN), (ACTION_B, ActionRole.ACQUIRER)
    )
    scope = search_scope(actor)
    only_a = ActionScope.of({ACTION_A})
    assert scope.actions == only_a
    assert scope.orders == only_a
    assert scope.invoices == only_a
    assert scope.members == only_a


@pytest.mark.parametrize("role", [ActionRole.ACQUIRER, ActionRole.DRIVER])
def test_member_without_finance_or_admin_role_reads_nothing(role: ActionRole) -> None:
    scope = search_scope(principal((ACTION_A, role)))
    for part in (scope.actions, scope.orders, scope.invoices, scope.members):
        assert part.is_empty


def test_finance_readers_read_invoices_only() -> None:
    action_reader = search_scope(principal((ACTION_A, ActionRole.FINANCE_READER)))
    assert action_reader.invoices == ActionScope.of({ACTION_A})
    assert action_reader.actions.is_empty and action_reader.orders.is_empty
    assert action_reader.members.is_empty

    for role in (GlobalRole.FINANCE_READER, GlobalRole.FINANCE_MANAGER):
        global_reader = search_scope(principal(global_roles=frozenset({role})))
        assert global_reader.invoices == ActionScope.everything()
        assert global_reader.actions.is_empty and global_reader.members.is_empty


def test_inactive_account_reads_nothing() -> None:
    scope = search_scope(
        principal(
            (ACTION_A, ActionRole.CHARITY_ADMIN),
            global_roles=frozenset({GlobalRole.SYSTEM_ADMIN}),
            status=AccountStatus.SUSPENDED,
        )
    )
    for part in (scope.actions, scope.orders, scope.invoices, scope.members):
        assert part.is_empty


@pytest.mark.parametrize(
    "actor",
    [
        principal((ACTION_A, ActionRole.CHARITY_ADMIN)),
        principal((ACTION_A, ActionRole.FINANCE_READER), (ACTION_B, ActionRole.DRIVER)),
        principal(global_roles=frozenset({GlobalRole.FINANCE_READER})),
        principal(global_roles=frozenset({GlobalRole.SYSTEM_ADMIN})),
        principal((ACTION_B, ActionRole.ACQUIRER)),
    ],
)
def test_scopes_agree_with_the_central_policies(actor: IdentityPrincipal) -> None:
    scope = search_scope(actor)
    for action_id in (ACTION_A, ACTION_B, uuid4()):
        assert scope.actions.allows(action_id) is may_manage_action(actor, action_id)
        assert scope.orders.allows(action_id) is may_manage_action(actor, action_id)
        assert scope.invoices.allows(action_id) is may_read_invoices(actor, action_id)


# --- service -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_without_invoice_permission_gets_no_invoice_results() -> None:
    # Charity admin of A, only acquirer in B: B's invoices are not readable.
    # A repository that wrongly returned one must still be filtered.
    invoice_b = hit(
        SearchResultType.INVOICE,
        title="KT26-0042",
        action_id=ACTION_B,
        detail="Musterwerk GmbH",
    )
    order_b = hit(
        SearchResultType.ORDER,
        title="KT26-0042 GmbH",
        action_id=ACTION_B,
        status="confirmed",
    )
    repository = RecordingRepository((invoice_b, order_b))
    service = SearchService(repository, clock=lambda: NOW)

    results = await service.search(
        principal(
            (ACTION_A, ActionRole.CHARITY_ADMIN), (ACTION_B, ActionRole.ACQUIRER)
        ),
        SearchQuery("KT26-0042"),
    )

    assert results == ()
    criteria = repository.criteria[0]
    assert criteria.scope.invoices == ActionScope.of({ACTION_A})
    assert criteria.contains == "%KT26-0042%"
    assert criteria.prefix == "KT26-0042%"
    assert criteria.evaluated_at == NOW

    acquirer = RecordingRepository((invoice_b,))
    assert (
        await SearchService(acquirer, clock=lambda: NOW).search(
            principal((ACTION_B, ActionRole.ACQUIRER)), SearchQuery("KT26-0042")
        )
        == ()
    )
    assert acquirer.criteria == []


@pytest.mark.asyncio
async def test_results_outside_the_readable_actions_are_dropped() -> None:
    inside = hit(SearchResultType.ACTION, title="Krapfentaxi", status="active")
    outside = hit(
        SearchResultType.ACTION,
        title="Krapfen fremd",
        action_id=ACTION_B,
        status="draft",
    )
    service = SearchService(RecordingRepository((inside, outside)), clock=lambda: NOW)

    results = await service.search(
        principal((ACTION_A, ActionRole.CHARITY_ADMIN)), SearchQuery("Krapfen")
    )

    assert [result.id for result in results] == [inside.id]


@pytest.mark.asyncio
async def test_no_repository_call_without_any_readable_type() -> None:
    repository = RecordingRepository()
    service = SearchService(repository, clock=lambda: NOW)

    assert (
        await service.search(
            principal((ACTION_A, ActionRole.DRIVER)), SearchQuery("ab")
        )
        == ()
    )
    assert repository.criteria == []


@pytest.mark.asyncio
async def test_results_are_ranked_merged_limited_and_point_to_admin_routes() -> None:
    action = hit(
        SearchResultType.ACTION, title="Krapfentaxi", prefix=True, status="active"
    )
    order = hit(
        SearchResultType.ORDER,
        title="Krapfenhaus GmbH",
        prefix=True,
        status="review_ready",
        detail="B-1042",
    )
    invoice = hit(
        SearchResultType.INVOICE,
        title="KT26-0001",
        detail="Krapfenhaus GmbH",
    )
    member = hit(
        SearchResultType.MEMBER,
        title="Anna Krapf",
        action_id=None,
        detail="anna@example.test",
        status="suspended",
        action_name=None,
    )
    late = hit(
        SearchResultType.ACTION, title="Zentrale Krapfen", status="archived", position=1
    )
    service = SearchService(
        RecordingRepository((member, late, invoice, order, action)),
        clock=lambda: NOW,
    )
    admin = principal(global_roles=frozenset({GlobalRole.SYSTEM_ADMIN}))

    results = await service.search(admin, SearchQuery("Krapf", limit=5))

    assert [(item.type, item.title, item.context, item.href) for item in results] == [
        (
            SearchResultType.ACTION,
            "Krapfentaxi",
            "Aktiv",
            f"/admin/actions/{ACTION_A}",
        ),
        (
            SearchResultType.ORDER,
            "Krapfenhaus GmbH",
            "B-1042 · Krapfentaxi · Prüfbereit",
            f"/admin/orders?action={ACTION_A}",
        ),
        (
            SearchResultType.ACTION,
            "Zentrale Krapfen",
            "Archiviert",
            f"/admin/actions/{ACTION_A}",
        ),
        (
            SearchResultType.INVOICE,
            "KT26-0001",
            "Krapfenhaus GmbH · Krapfentaxi",
            f"/admin/invoices?action={ACTION_A}",
        ),
        (
            SearchResultType.MEMBER,
            "Anna Krapf",
            "anna@example.test · Gesperrt",
            "/admin/members",
        ),
    ]
    assert repository_limit(service) == 5


def repository_limit(service: SearchService) -> int:
    repository = service._repository  # noqa: SLF001 - test inspects the fake
    assert isinstance(repository, RecordingRepository)
    return repository.criteria[0].limit


# --- HTTP contract -----------------------------------------------------------


def test_openapi_declares_the_bounded_search_operation() -> None:
    operation = create_app().openapi()["paths"]["/api/v1/search"]["get"]
    assert operation["operationId"] == "searchCore"
    parameters = {item["name"]: item for item in operation["parameters"]}
    assert parameters["q"]["required"] is True
    assert parameters["q"]["schema"]["minLength"] == 2
    assert parameters["q"]["schema"]["maxLength"] == 80
    assert parameters["limit"]["schema"]["minimum"] == 1
    assert parameters["limit"]["schema"]["maximum"] == 20
    assert parameters["limit"]["schema"]["default"] == 8
    assert {"401", "422"} <= set(operation["responses"])
