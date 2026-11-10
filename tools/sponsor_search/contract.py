#!/usr/bin/env python3
"""Real PostgreSQL/Twenty/API contract for the sponsor search (bundle §9).

Runs on the Golden seed with the real Twenty of the test stack. It proves
the three ways the index is filled (assignment creation, changed pass, full
pass), the request budget, the stop on a real 429, and that every sponsor
hit opens through the endpoint behind its target for each role.

``forget-index`` and ``worker-loop`` frame the proof of the worker process
(``tools/testing/acquisition_contracts.sh``): the index is emptied, the
real worker starts, and its own loop must fill the index again.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

import asyncpg
import httpx
from pydantic import SecretStr

from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.sponsor_search import AsyncpgSponsorSearchIndex
from leonaid.adapters.twenty.gateway import TwentyCrmGateway, TwentyGatewaySettings
from leonaid.application.activities import CRM_PARTY_GONE_LABEL
from leonaid.application.crm import (
    CompanyData,
    CompanyUpdate,
    CrmGatewayError,
    CrmPartyKind,
)
from leonaid.application.sponsor_search import (
    SYNC_REQUEST_BUDGET,
    SponsorSearchSync,
    SyncReport,
)
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)
from tools.seed.golden import TwentyClient

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
SIMONE_ID = UUID("10000000-0000-4000-8000-000000000001")  # system admin
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")  # charity admin
FELIX_ID = UUID("10000000-0000-4000-8000-000000000003")  # admin elsewhere
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")  # acquirer
BERND_ID = UUID("10000000-0000-4000-8000-000000000005")  # acquirer
CARLA_ID = UUID("10000000-0000-4000-8000-000000000006")  # acquirer
SESSION_NAMESPACE = UUID("5b0f2c0e-6a39-4f0c-9d56-3d1a6d1e7a55")
ZONE = ZoneInfo("Europe/Berlin")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Missing environment variable: {name}")
    return value


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ContractFailure(message)


def token_for(user_id: UUID) -> str:
    return f"sponsor-search-{user_id}-server-session-token-value"


async def seed_sessions(connection: asyncpg.Connection[Any]) -> dict[UUID, str]:
    now = datetime.now(timezone.utc)
    users = (SIMONE_ID, KLARA_ID, FELIX_ID, ANNA_ID, BERND_ID, CARLA_ID)
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])", list(users)
    )
    tokens: dict[UUID, str] = {}
    for user_id in users:
        tokens[user_id] = token_for(user_id)
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at, last_seen_at,
                fresh_login_at, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $5, $5, $5)
            """,
            uuid5(SESSION_NAMESPACE, str(user_id)),
            user_id,
            session_token_digest(tokens[user_id]),
            now + SESSION_LIFETIME,
            now,
        )
    return tokens


class Api:
    def __init__(self, client: httpx.AsyncClient, tokens: dict[UUID, str]) -> None:
        self._client = client
        self._tokens = tokens

    async def request(
        self,
        user_id: UUID,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        body: Mapping[str, object] | None = None,
    ) -> httpx.Response:
        return await self._client.request(
            method,
            path,
            cookies={SESSION_COOKIE_NAME: self._tokens[user_id]},
            headers={"X-Request-ID": f"sponsor-search:{uuid4()}"},
            params=params,
            json=body,
        )

    async def sponsor_hits(self, user_id: UUID, query: str) -> list[dict[str, str]]:
        response = await self.request(
            user_id, "GET", "/api/v1/search", params={"q": query, "limit": 20}
        )
        response.raise_for_status()
        return [
            item for item in response.json()["results"] if item["type"] == "sponsor"
        ]

    async def board(self, user_id: UUID, scope: str) -> httpx.Response:
        return await self.request(
            user_id,
            "GET",
            f"/api/v1/actions/{ACTION_ID}/acquisition/activity-board",
            params={"scope": scope, "limit": 100},
        )

    async def open_hit(
        self, user_id: UUID, hit: Mapping[str, str], *, gone: bool = False
    ) -> None:
        """Open the hit through the endpoint behind its target page.

        ``gone``: Twenty no longer has the party; the row says so.
        """

        web = f"/admin/acquisition?action={ACTION_ID}&open={hit['id']}"
        app = f"/app/sponsors?action={ACTION_ID}&assignment={hit['id']}"
        check(hit["href"] in {web, app}, f"Unexpected sponsor target: {hit['href']}")
        board = await self.board(
            user_id, "action" if hit["href"] == web else "personal"
        )
        check(
            board.status_code == 200,
            f"Target board answered {board.status_code} for {hit['href']}",
        )
        item = next(
            (
                entry
                for entry in board.json()["workItems"]
                if entry["assignmentId"] == hit["id"]
            ),
            None,
        )
        check(item is not None, f"Board does not show the hit {hit['href']}")
        assert item is not None
        check(
            item["partyDisplayName"]
            == (CRM_PARTY_GONE_LABEL if gone else hit["title"]),
            "The hit's title is not the sponsor's name on its board",
        )
        detail = await self.request(
            user_id,
            "GET",
            f"/api/v1/actions/{ACTION_ID}/acquisition/assignments/{hit['id']}",
        )
        check(detail.status_code == 200, "The assignment detail does not open")


def targets(hits: list[dict[str, str]]) -> dict[str, str]:
    return {hit["id"]: hit["href"].split("?")[0] for hit in hits}


class Stack:
    """The real services of the proof."""

    def __init__(
        self,
        connection: asyncpg.Connection[Any],
        pool: asyncpg.Pool[Any],
        gateway: TwentyCrmGateway,
        api: Api,
    ) -> None:
        self.connection = connection
        self.gateway = gateway
        self.api = api
        self.index = AsyncpgSponsorSearchIndex(pool)

    def sync(self, budget: int = SYNC_REQUEST_BUDGET) -> SponsorSearchSync:
        return SponsorSearchSync(
            self.index, self.gateway, zone=ZONE, request_budget=budget
        )

    async def run(
        self, *, budget: int = SYNC_REQUEST_BUDGET, force_full: bool = False
    ) -> SyncReport:
        """One sync run; the report must count the requests really sent."""

        before = self.gateway.requests_sent
        report = await self.sync(budget).run_once(force_full=force_full)
        sent = self.gateway.requests_sent - before
        check(
            report.requests == sent and sent <= budget,
            f"Run sent {sent} CRM requests, reported {report.requests}, "
            f"budget {budget}",
        )
        return report

    async def entry(self, twenty_id: UUID) -> asyncpg.Record | None:
        return await self.connection.fetchrow(
            "SELECT * FROM sponsor_search_entry WHERE twenty_id = $1", twenty_id
        )

    async def forget_index(self) -> None:
        await self.connection.execute("DELETE FROM sponsor_search_entry")
        await self.connection.execute(
            "UPDATE sponsor_search_sync SET full_pass_completed_at = NULL, "
            "full_pass_after_kind = NULL, full_pass_after_id = NULL"
        )

    async def index_matches_twenty(self) -> int:
        """Every referenced party that Twenty has is in the index, as Twenty has it."""

        rows = await self.connection.fetch(
            """
            SELECT DISTINCT twenty_company_id AS company, twenty_person_id AS person
            FROM acquisition_assignment
            """
        )
        company_ids = tuple(row["company"] for row in rows if row["company"])
        person_ids = tuple(row["person"] for row in rows if row["person"])
        expected: dict[UUID, tuple[str, str | None]] = {}
        for company in await self.gateway.get_companies(
            company_ids, correlation_id="sponsor-search:verify-companies"
        ):
            expected[company.twenty_id] = (company.data.name, company.data.address.city)
        for person in await self.gateway.get_people(
            person_ids, correlation_id="sponsor-search:verify-people"
        ):
            expected[person.twenty_id] = (
                f"{person.data.given_name} {person.data.family_name}",
                None,
            )
        entries = {
            row["twenty_id"]: (row["display_name"], row["city"])
            for row in await self.connection.fetch(
                "SELECT twenty_id, display_name, city FROM sponsor_search_entry"
            )
        }
        check(bool(expected), "The Golden seed has no referenced CRM party")
        check(
            entries == expected,
            f"Index differs from Twenty: {entries!r} != {expected!r}",
        )
        return len(expected)


async def prove_first_full_pass(stack: Stack) -> None:
    await stack.forget_index()
    report = await stack.run()
    check(
        report.mode == "full" and report.complete and report.requests >= 1,
        f"First run was not a complete full pass: {report!r}",
    )
    parties = await stack.index_matches_twenty()
    check(report.written == parties, "Full pass did not write every party once")
    state = await stack.index.sync_state()
    check(
        state.full_pass_completed_at is not None and state.full_pass_after is None,
        "Full pass did not record its completion",
    )
    # A company carries its city; a person has none in Twenty.
    check(
        await stack.connection.fetchval(
            "SELECT count(*) FROM sponsor_search_entry "
            "WHERE party_kind = 'company' AND city IS NOT NULL"
        )
        > 0,
        "No company entry has a city",
    )
    check(
        await stack.connection.fetchval(
            "SELECT count(*) FROM sponsor_search_entry "
            "WHERE party_kind = 'person' AND city IS NOT NULL"
        )
        == 0,
        "A person entry has a city",
    )
    again = await stack.run()
    check(
        again.mode == "changed" and again.complete,
        f"A second run repeated the full pass: {again!r}",
    )


async def prove_assignment_creation(stack: Stack, token: str) -> UUID:
    """A new sponsor is found at once, per role, and opens at its target."""

    name = f"Suchindex {token} GmbH"
    city = f"Indexhausen {token}"
    draft = {"companyName": name, "postalCode": "86150", "city": city}
    path = f"/api/v1/actions/{ACTION_ID}/acquisition/sponsor-match"
    resolved = await stack.api.request(
        ANNA_ID,
        "POST",
        f"{path}/resolve",
        body={
            "commandId": str(uuid4()),
            "sponsor": draft,
            "expectedStatus": "no_match",
            "selectedTwentyId": None,
            "confirmExistingAssignments": False,
        },
    )
    resolved.raise_for_status()
    payload = resolved.json()
    check(payload["outcome"] == "created", "The sponsor was not created")
    company_id = UUID(payload["twentyId"])
    anna_assignment = payload["assignmentId"]
    entry = await stack.entry(company_id)
    check(
        entry is not None
        and (entry["party_kind"], entry["display_name"], entry["city"])
        == ("company", name, city),
        "Assignment creation did not write the search entry",
    )
    # Name and city only: the table has no other column of the party.
    columns = {
        row["column_name"]
        for row in await stack.connection.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'sponsor_search_entry'"
        )
    }
    check(
        columns
        == {
            "party_kind",
            "twenty_id",
            "display_name",
            "city",
            "synced_at",
            "erased_at",
        },
        f"sponsor_search_entry holds more than name and city: {sorted(columns)}",
    )

    anna = await stack.api.sponsor_hits(ANNA_ID, token)
    check(
        targets(anna) == {anna_assignment: "/app/sponsors"},
        f"Acquirer does not find the own sponsor in the app: {anna!r}",
    )
    check(
        anna[0]["title"] == name and anna[0]["context"].endswith(f" · {city}"),
        f"Hit does not show name, action and city: {anna[0]!r}",
    )
    await stack.api.open_hit(ANNA_ID, anna[0])
    # The city finds the sponsor too.
    check(
        targets(await stack.api.sponsor_hits(ANNA_ID, city.lower()))
        == {anna_assignment: "/app/sponsors"},
        "The city does not find the sponsor",
    )
    check(
        await stack.api.sponsor_hits(BERND_ID, token) == [],
        "An acquirer finds a sponsor of another acquirer",
    )
    check(
        await stack.api.sponsor_hits(FELIX_ID, token) == [],
        "The admin of another action finds the sponsor",
    )
    for manager in (KLARA_ID, SIMONE_ID):
        hits = await stack.api.sponsor_hits(manager, token)
        check(
            targets(hits) == {anna_assignment: "/admin/acquisition"},
            f"Manager does not find the sponsor in the web pipeline: {hits!r}",
        )
        # For the system admin this is the board that used to answer 403.
        await stack.api.open_hit(manager, hits[0])

    # A second acquirer for the same sponsor: one hit per assignment.
    assigned = await stack.api.request(
        KLARA_ID,
        "POST",
        f"/api/v1/actions/{ACTION_ID}/acquisition/assignments",
        body={
            "partyKind": "company",
            "partyId": str(company_id),
            "acquirerUserId": str(BERND_ID),
        },
    )
    check(assigned.status_code == 201, "Proactive assignment was not created")
    bernd_assignment = assigned.json()["assignment"]["id"]
    klara = await stack.api.sponsor_hits(KLARA_ID, token)
    check(
        targets(klara)
        == {
            anna_assignment: "/admin/acquisition",
            bernd_assignment: "/admin/acquisition",
        },
        f"Manager does not get one hit per assignment: {klara!r}",
    )
    for hit in klara:
        await stack.api.open_hit(KLARA_ID, hit)
    bernd = await stack.api.sponsor_hits(BERND_ID, token)
    check(
        targets(bernd) == {bernd_assignment: "/app/sponsors"},
        f"The second acquirer does not find the own assignment: {bernd!r}",
    )
    await stack.api.open_hit(BERND_ID, bernd[0])

    # A handed-over assignment leaves the former acquirer's search.
    current = await stack.api.request(
        BERND_ID,
        "GET",
        f"/api/v1/actions/{ACTION_ID}/acquisition/assignments/{bernd_assignment}",
    )
    current.raise_for_status()
    handed = await stack.api.request(
        KLARA_ID,
        "POST",
        f"/api/v1/actions/{ACTION_ID}/acquisition/assignments/"
        f"{bernd_assignment}/handover",
        body={
            "revision": current.json()["assignment"]["revision"],
            "targetAcquirerUserId": str(CARLA_ID),
        },
    )
    check(handed.status_code == 200, f"Handover failed: {handed.text}")
    carla_assignment = handed.json()["target"]["id"]
    check(
        await stack.api.sponsor_hits(BERND_ID, token) == [],
        "The former acquirer still finds the handed-over sponsor",
    )
    carla = await stack.api.sponsor_hits(CARLA_ID, token)
    check(
        targets(carla) == {carla_assignment: "/app/sponsors"},
        f"The new acquirer does not find the sponsor: {carla!r}",
    )
    await stack.api.open_hit(CARLA_ID, carla[0])
    # The manager still sees all three, the handed-over one included.
    klara = await stack.api.sponsor_hits(KLARA_ID, token)
    check(
        set(targets(klara)) == {anna_assignment, bernd_assignment, carla_assignment},
        "The manager does not see every assignment after the handover",
    )
    for hit in klara:
        await stack.api.open_hit(KLARA_ID, hit)
    return company_id


async def prove_changed_pass(stack: Stack, company_id: UUID, token: str) -> str:
    """A rename in Twenty reaches the index; a party without entry is not added."""

    renamed = f"Umgetauft {token} AG"
    await stack.gateway.update_company(
        uuid4(),
        company_id,
        CompanyUpdate(name=renamed),
        correlation_id="sponsor-search:rename",
    )
    unassigned, _receipt = await stack.gateway.create_company(
        uuid4(),
        CompanyData(name=f"Unzugeordnet {token} KG"),
        correlation_id="sponsor-search:unassigned",
    )
    report = await stack.run()
    check(
        report.mode == "changed" and report.complete and report.written >= 1,
        f"Changed pass did not refresh the renamed sponsor: {report!r}",
    )
    # One page per kind at least: companies and people.
    check(report.requests >= len(CrmPartyKind), "Changed pass skipped a party kind")
    entry = await stack.entry(company_id)
    check(
        entry is not None and entry["display_name"] == renamed,
        "The index kept the old name",
    )
    check(
        await stack.entry(unassigned.twenty_id) is None,
        "The changed pass added a party without an assignment",
    )
    check(
        len(await stack.api.sponsor_hits(KLARA_ID, f"umgetauft {token}")) == 3,
        "The new name does not find the sponsor",
    )
    check(
        await stack.api.sponsor_hits(KLARA_ID, f"Suchindex {token}") == [],
        "The old name still finds the sponsor",
    )
    await stack.index_matches_twenty()
    return renamed


async def prove_budget(stack: Stack) -> None:
    """A full pass spends its budget per run and continues where it stopped."""

    parties = await stack.connection.fetchval(
        """
        SELECT count(DISTINCT twenty_company_id) FILTER (
                   WHERE twenty_company_id IS NOT NULL
               ) > 0
           AND count(DISTINCT twenty_person_id) FILTER (
                   WHERE twenty_person_id IS NOT NULL
               ) > 0
        FROM acquisition_assignment
        """
    )
    check(bool(parties), "The proof needs a company and a person assignment")
    await stack.forget_index()
    first = await stack.run(budget=1)
    check(
        first.mode == "full"
        and first.requests == 1
        and not first.complete
        and first.continue_soon
        and not first.rate_limited,
        f"A budget of one request was not respected: {first!r}",
    )
    state = await stack.index.sync_state()
    check(
        state.full_pass_after is not None and state.full_pass_completed_at is None,
        "An unfinished full pass did not keep its cursor",
    )
    people_before = await stack.connection.fetchval(
        "SELECT count(*) FROM sponsor_search_entry WHERE party_kind = 'person'"
    )
    check(people_before == 0, "The first batch already read the people")
    runs = 1
    while True:
        report = await stack.run(budget=1)
        runs += 1
        check(report.mode == "full", "The unfinished pass was not continued")
        if report.complete:
            break
        check(runs < 20, "The full pass does not finish")
    await stack.index_matches_twenty()
    # The default budget is the one of the spec.
    check(SYNC_REQUEST_BUDGET == 30, "The request budget is not 30")


async def prove_changed_pass_state(stack: Stack) -> None:
    """Only a complete changed pass moves the point it has read up to."""

    before = await stack.index.sync_state()
    started = datetime.now(timezone.utc)
    complete = await stack.run()
    check(
        complete.mode == "changed" and complete.complete,
        f"Expected a complete changed pass: {complete!r}",
    )
    after = await stack.index.sync_state()
    check(
        after.changed_read_until is not None
        and after.changed_read_until >= started
        and (
            before.changed_read_until is None
            or after.changed_read_until > before.changed_read_until
        ),
        "A complete changed pass did not record how far it has read",
    )
    check(
        after.last_success == after.changed_read_until,
        "The last successful pass is not the changed pass that just ran",
    )
    # One request reads the companies only: the pass is cut by its budget.
    cut = await stack.run(budget=1)
    check(
        cut.mode == "changed" and not cut.complete and cut.crm_error is None,
        f"Expected a changed pass cut by its budget: {cut!r}",
    )
    check(
        (await stack.index.sync_state()).changed_read_until == after.changed_read_until,
        "An incomplete changed pass moved the point it has read up to",
    )


async def run_with(
    stack: Stack, gateway: TwentyCrmGateway, *, force_full: bool = True
) -> SyncReport:
    return await SponsorSearchSync(stack.index, gateway, zone=ZONE).run_once(
        force_full=force_full
    )


async def prove_incomplete_answer_deletes_nothing(
    stack: Stack, base_url: str, key: str
) -> None:
    """An ID batch that Twenty answers on more than one page is refused.

    The full pass deletes the entries missing from an answer, so a cut
    answer must never reach it. A page size of one cuts every batch of two.
    """

    companies = [
        row["twenty_id"]
        for row in await stack.connection.fetch(
            "SELECT twenty_id FROM sponsor_search_entry "
            "WHERE party_kind = 'company' AND erased_at IS NULL"
        )
    ]
    check(len(companies) >= 2, "The proof needs two indexed companies")
    entries_before = await stack.connection.fetch(
        "SELECT * FROM sponsor_search_entry ORDER BY party_kind, twenty_id"
    )
    state_before = await stack.index.sync_state()
    small_pages = TwentyCrmGateway(
        TwentyGatewaySettings(
            base_url=base_url,
            api_key=SecretStr(key),
            page_size=1,
            max_rate_limit_retries=0,
        )
    )
    try:
        try:
            await small_pages.sponsor_parties_by_id(
                CrmPartyKind.COMPANY,
                tuple(companies[:2]),
                correlation_id="sponsor-search:cut-page",
            )
        except CrmGatewayError as error:
            check(
                error.code == "crm_pagination_invalid" and not error.retryable,
                f"A cut ID batch raised the wrong error: {error.code}",
            )
        else:
            raise ContractFailure("A cut ID batch was accepted as complete")
        report = await run_with(stack, small_pages)
    finally:
        await small_pages.close()
    check(
        report.mode == "full"
        and report.crm_error == "crm_pagination_invalid"
        and not report.crm_error_retryable
        and not report.complete
        and report.deleted == 0
        and report.written == 0,
        f"A full pass acted on a cut answer: {report!r}",
    )
    check(
        await stack.connection.fetch(
            "SELECT * FROM sponsor_search_entry ORDER BY party_kind, twenty_id"
        )
        == entries_before,
        "A cut answer changed the index",
    )
    check(
        (await stack.index.sync_state()).full_pass_completed_at
        == state_before.full_pass_completed_at,
        "A failed full pass recorded a completion",
    )


async def prove_refused_key(stack: Stack, base_url: str) -> None:
    """A key that Twenty refuses ends the run and is not a success."""

    state_before = await stack.index.sync_state()
    refused = TwentyCrmGateway(
        TwentyGatewaySettings(
            base_url=base_url,
            api_key=SecretStr("revoked-" + uuid4().hex + uuid4().hex),
            max_rate_limit_retries=0,
        )
    )
    try:
        full = await run_with(stack, refused)
        changed = await run_with(stack, refused, force_full=False)
    finally:
        await refused.close()
    for report in (full, changed):
        check(
            report.crm_error == "crm_permission_denied"
            and not report.crm_error_retryable
            and not report.complete
            and report.requests == 1
            and not report.rate_limited,
            f"A refused key was not reported as such: {report!r}",
        )
    check(
        changed.mode == "changed" and full.mode == "full",
        "The refused runs were not one full and one changed pass",
    )
    state = await stack.index.sync_state()
    check(
        state.last_success == state_before.last_success
        and state.changed_read_until == state_before.changed_read_until,
        "A run with a refused key counted as a successful pass",
    )


def delete_company_in_twenty(company_id: UUID) -> None:
    """Delete the company as a workspace admin would in the Twenty UI.

    The integration key cannot delete (least privilege), so this signs in as
    the bootstrap admin of the test stack.
    """

    admin = TwentyClient()
    try:
        admin.authenticate()
        response = admin.request("DELETE", f"/rest/companies/{company_id}")
        if response.is_error:
            raise ContractFailure(
                f"Twenty refused the delete: HTTP {response.status_code}"
            )
    finally:
        admin.close()


async def prove_boards_with_a_gone_party(
    stack: Stack, company_id: UUID, token: str
) -> None:
    """One party deleted in Twenty does not close the boards of the action.

    Its assignments stay listed, named as gone and without contact data; the
    other rows are untouched. The search hit (still in the index until the
    full pass) opens that row, and a manager can still hand it over.
    """

    for user_id, scope in (
        (KLARA_ID, "action"),
        (SIMONE_ID, "action"),
        (ANNA_ID, "personal"),
    ):
        board = await stack.api.board(user_id, scope)
        check(
            board.status_code == 200,
            f"The {scope} board fails with a party deleted in Twenty: "
            f"{board.status_code}",
        )
        items = board.json()["workItems"]
        gone = [item for item in items if item["partyId"] == str(company_id)]
        others = [item for item in items if item["partyId"] != str(company_id)]
        check(bool(gone), f"The {scope} board dropped the gone party's assignment")
        check(bool(others), f"The {scope} board lost its other rows")
        for item in gone:
            check(
                item["partyDisplayName"] == CRM_PARTY_GONE_LABEL
                and all(
                    item[field] is None
                    for field in ("city", "postalCode", "contactName", "email", "phone")
                ),
                f"A gone party is not shown as gone: {item!r}",
            )
        check(
            all(item["partyDisplayName"] != CRM_PARTY_GONE_LABEL for item in others),
            "A party that Twenty still has is shown as gone",
        )
    # The hits still carry the indexed name; each opens its row on the board.
    for user_id in (KLARA_ID, ANNA_ID):
        hits = await stack.api.sponsor_hits(user_id, token)
        check(bool(hits), "The sponsor left the search before the full pass")
        for hit in hits:
            await stack.api.open_hit(user_id, hit, gone=True)
    # A manager can still hand the assignment over.
    hit = (await stack.api.sponsor_hits(ANNA_ID, token))[0]
    current = await stack.api.request(
        KLARA_ID,
        "GET",
        f"/api/v1/actions/{ACTION_ID}/acquisition/assignments/{hit['id']}",
    )
    current.raise_for_status()
    handed = await stack.api.request(
        KLARA_ID,
        "POST",
        f"/api/v1/actions/{ACTION_ID}/acquisition/assignments/{hit['id']}/handover",
        body={
            "revision": current.json()["assignment"]["revision"],
            "targetAcquirerUserId": str(BERND_ID),
        },
    )
    check(
        handed.status_code == 200,
        f"A gone party's assignment cannot be handed over: {handed.text}",
    )


async def prove_delete(stack: Stack, company_id: UUID, name: str, token: str) -> None:
    """Polling cannot see a delete in Twenty; the full pass removes the entry."""

    orphan = uuid4()
    await stack.connection.execute(
        "INSERT INTO sponsor_search_entry "
        "(party_kind, twenty_id, display_name, city, synced_at) "
        "VALUES ('person', $1, $2, NULL, CURRENT_TIMESTAMP)",
        orphan,
        f"Ohne Zuordnung {token}",
    )
    await asyncio.to_thread(delete_company_in_twenty, company_id)
    check(
        await stack.gateway.get_company(
            company_id, correlation_id="sponsor-search:gone"
        )
        is None,
        "The company still exists in Twenty",
    )
    changed = await stack.run()
    check(changed.mode == "changed", f"Expected a changed pass: {changed!r}")
    entry = await stack.entry(company_id)
    check(
        entry is not None and entry["display_name"] == name,
        "The changed pass was expected to miss the delete",
    )
    await prove_boards_with_a_gone_party(stack, company_id, token)
    full = await stack.run(force_full=True)
    check(
        full.mode == "full" and full.complete and full.deleted >= 2,
        f"The full pass did not delete the stale entries: {full!r}",
    )
    check(await stack.entry(company_id) is None, "The deleted sponsor is still indexed")
    check(await stack.entry(orphan) is None, "An entry without assignment survived")
    check(
        await stack.api.sponsor_hits(KLARA_ID, token) == [],
        "The search still finds a sponsor that Twenty no longer has",
    )
    await stack.index_matches_twenty()


# A spent minute bucket must stay spent for at least this long, so that the
# run that follows meets it at once.
QUOTA_RESET_MARGIN_SECONDS = 10.0


def seconds_to_reset(response: httpx.Response) -> float:
    try:
        return float(response.headers.get("X-RateLimit-Reset", "")) - time.time()
    except ValueError:
        return 0.0


async def spend_twenty_quota(twenty: httpx.AsyncClient) -> None:
    """Send reads until Twenty's minute bucket (100 requests) is spent.

    Twenty names the end of the window in ``X-RateLimit-Reset``. A bucket
    that reopens within the margin is waited out and spent again in the new
    window: the run that follows should not start in a fresh window.
    """

    for _ in range(60):
        responses = await asyncio.gather(
            *(twenty.get("/rest/companies", params={"limit": 1}) for _ in range(10))
        )
        limited = [response for response in responses if response.status_code == 429]
        # Twenty also has a short burst bucket. Only a spent minute bucket
        # (remaining 0) still refuses the request the sync sends next.
        spent = [
            response
            for response in limited
            if response.headers.get("X-RateLimit-Remaining", "").strip() == "0"
        ]
        if spent:
            reset = max(seconds_to_reset(response) for response in spent)
            if reset >= QUOTA_RESET_MARGIN_SECONDS:
                return
            await asyncio.sleep(max(reset, 0.0) + 0.5)
        elif limited:
            await asyncio.sleep(float(limited[0].headers.get("Retry-After", "1")))
    raise ContractFailure("Twenty's minute bucket was not spent by 600 requests")


async def wait_for_twenty_quota(twenty: httpx.AsyncClient) -> None:
    """Wait until Twenty accepts requests again, by its own reset header."""

    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        response = await twenty.get("/rest/companies", params={"limit": 1})
        if response.status_code != 429:
            response.raise_for_status()
            return
        try:
            reset = float(response.headers.get("X-RateLimit-Reset", "")) - time.time()
        except ValueError:
            reset = 1.0
        await asyncio.sleep(min(max(reset, 1.0), 30.0))
    raise ContractFailure("Twenty's request quota did not come back")


async def prove_rate_limit(stack: Stack, twenty: httpx.AsyncClient) -> None:
    """The first 429 ends the run: no request follows it, progress is kept.

    The proof counts what the gateway really sent and received. It does not
    pin how many requests Twenty still accepted before the 429: the quota
    is Twenty's, and its window can reopen between the spending and the run.
    """

    await stack.connection.execute(
        "UPDATE sponsor_search_sync SET full_pass_completed_at = NULL"
    )
    entries_before = await stack.connection.fetch(
        "SELECT party_kind, twenty_id, display_name, city, erased_at "
        "FROM sponsor_search_entry ORDER BY party_kind, twenty_id"
    )
    try:
        for _ in range(5):
            await spend_twenty_quota(twenty)
            limited_before = stack.gateway.rate_limited_responses
            report = await stack.run()
            limited = stack.gateway.rate_limited_responses - limited_before
            if limited:
                break
            # Twenty accepted the whole run after all (the window reopened):
            # nothing to judge. Make the pass due again and spend once more.
            check(
                report.mode == "full" and report.complete,
                f"A run without a 429 did not complete: {report!r}",
            )
            await stack.connection.execute(
                "UPDATE sponsor_search_sync SET full_pass_completed_at = NULL"
            )
        else:
            raise ContractFailure("No run met a 429 in five attempts")
        # Exactly one 429, and it was the answer to the last request the
        # run sent (Stack.run checked report.requests against the gateway).
        check(
            limited == 1 and stack.gateway.last_status_code == 429,
            f"The run sent a request after its first 429: {limited} answers "
            f"were a 429, the last status was {stack.gateway.last_status_code}",
        )
        check(
            report.mode == "full"
            and report.rate_limited
            and report.requests >= 1
            and not report.complete
            and report.crm_error == "crm_rate_limited",
            f"The run did not stop on the first 429: {report!r}",
        )
        state = await stack.index.sync_state()
        check(
            state.full_pass_completed_at is None,
            "A rate-limited run recorded a completed full pass",
        )
        # Every request before the 429 is one stored batch; the cursor
        # stands behind the last of them, or nowhere when the 429 came first.
        check(
            (state.full_pass_after is None) == (report.requests == 1),
            f"The cursor does not match the batches read before the 429: "
            f"{report!r}, cursor {state.full_pass_after!r}",
        )
        # The index was complete before; batches read again change nothing.
        check(
            await stack.connection.fetch(
                "SELECT party_kind, twenty_id, display_name, city, erased_at "
                "FROM sponsor_search_entry ORDER BY party_kind, twenty_id"
            )
            == entries_before
            and report.deleted == 0,
            "A rate-limited run changed the index",
        )
    finally:
        # Leave the stack usable for whoever borrows it next.
        await wait_for_twenty_quota(twenty)
    # The quota comes back request by request. Each run keeps what it read
    # and the next one continues there, until the pass is complete.
    for _ in range(12):
        report = await stack.run()
        check(report.mode == "full", f"The full pass was not continued: {report!r}")
        if report.complete:
            break
        check(
            report.rate_limited,
            f"A run ended early without a 429 or a spent budget: {report!r}",
        )
        await wait_for_twenty_quota(twenty)
    else:
        raise ContractFailure("The full pass did not finish after the quota came back")
    # The comparison reads Twenty too and may meet the last of the 429s.
    for _ in range(12):
        try:
            await stack.index_matches_twenty()
            break
        except CrmGatewayError as error:
            if error.http_status != 429:
                raise
            await wait_for_twenty_quota(twenty)
    else:
        raise ContractFailure("Twenty's request quota did not come back")


async def remove_proof_assignments(
    connection: asyncpg.Connection[Any], company_id: UUID | None
) -> None:
    """The proof's sponsor is gone from Twenty; its assignments go too.

    They would stay on the Golden boards as "Im CRM nicht mehr vorhanden"
    for whoever borrows the stack next.
    """

    if company_id is None:
        return
    ids = [
        row["id"]
        for row in await connection.fetch(
            "SELECT id FROM acquisition_assignment WHERE twenty_company_id = $1",
            company_id,
        )
    ]
    await connection.execute(
        "DELETE FROM acquisition_assignment_history "
        "WHERE assignment_id = ANY($1::uuid[])",
        ids,
    )
    await connection.execute(
        "DELETE FROM acquisition_assignment WHERE id = ANY($1::uuid[])", ids
    )
    await connection.execute(
        "DELETE FROM sponsor_search_entry WHERE twenty_id = $1", company_id
    )


async def exercise(connection: asyncpg.Connection[Any]) -> None:
    tokens = await seed_sessions(connection)
    token = uuid4().hex[:10]
    key = require_env("TWENTY_INTEGRATION_API_KEY")
    base_url = require_env("TWENTY_BASE_URL").rstrip("/")
    pool = await create_pool(require_env("CORE_DATABASE_URL"), maximum_size=3)
    # As the worker builds it: no retry on 429, the loop owns the waiting.
    gateway = TwentyCrmGateway(
        TwentyGatewaySettings(
            base_url=base_url, api_key=SecretStr(key), max_rate_limit_retries=0
        )
    )
    company_id: UUID | None = None
    try:
        async with (
            httpx.AsyncClient(
                base_url=require_env("API_BASE_URL").rstrip("/"), timeout=60
            ) as api_client,
            httpx.AsyncClient(
                base_url=base_url,
                headers={"Authorization": f"Bearer {key}"},
                timeout=60,
            ) as twenty,
        ):
            stack = Stack(connection, pool, gateway, Api(api_client, tokens))
            try:
                await prove_first_full_pass(stack)
                company_id = await prove_assignment_creation(stack, token)
                renamed = await prove_changed_pass(stack, company_id, token)
                await prove_budget(stack)
                await prove_delete(stack, company_id, renamed, token)
            finally:
                await remove_proof_assignments(connection, company_id)
            await prove_changed_pass_state(stack)
            await prove_incomplete_answer_deletes_nothing(stack, base_url, key)
            await prove_refused_key(stack, base_url)
            await prove_rate_limit(stack, twenty)
    finally:
        await gateway.close()
        await pool.close()
    print(
        "sponsor-search-contract: OK: entry on assignment creation, changed pass,",
        "full pass with deletes, request budget, stop on a real 429 and the",
        "targets of every role proven against real Twenty and PostgreSQL",
    )


async def prove_worker_loop(connection: asyncpg.Connection[Any]) -> None:
    """The running worker filled the emptied index by itself and is ready."""

    pool = await create_pool(require_env("CORE_DATABASE_URL"), maximum_size=2)
    # Only the comparison reads Twenty here; it may wait out a 429.
    gateway = TwentyCrmGateway(
        TwentyGatewaySettings(
            base_url=require_env("TWENTY_BASE_URL").rstrip("/"),
            api_key=SecretStr(require_env("TWENTY_INTEGRATION_API_KEY")),
        )
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            stack = Stack(connection, pool, gateway, Api(client, {}))
            deadline = time.monotonic() + 300
            while True:
                state = await stack.index.sync_state()
                if state.full_pass_completed_at is not None:
                    break
                check(
                    time.monotonic() < deadline,
                    "The worker did not finish a full pass within five minutes",
                )
                await asyncio.sleep(1)
            parties = await stack.index_matches_twenty()
            ready = await client.get("http://worker:8010/health/ready")
            check(ready.status_code == 200, f"Worker is not ready: {ready.text}")
            check(
                ready.json()["checks"].get("sponsor_search_sync") == "ready",
                f"Worker does not report the sync loop: {ready.text}",
            )
    finally:
        await gateway.close()
        await pool.close()
    print(
        f"sponsor-search-contract: OK: the worker loop filled the index for "
        f"{parties} parties and reports ready"
    )


async def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "exercise"
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"))
    try:
        if command == "exercise":
            await exercise(connection)
        elif command == "forget-index":
            await connection.execute("DELETE FROM sponsor_search_entry")
            await connection.execute(
                "UPDATE sponsor_search_sync SET full_pass_completed_at = NULL, "
                "full_pass_after_kind = NULL, full_pass_after_id = NULL"
            )
        elif command == "worker-loop":
            await prove_worker_loop(connection)
        else:
            raise ContractFailure(f"Unknown command: {command}")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
