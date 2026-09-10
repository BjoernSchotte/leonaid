"""Real database and HTTP proof of verified self buyers and acquisition replay access."""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.member_buyers import AsyncpgMemberBuyerRepository
from leonaid.application.commitments import CommitmentService
from leonaid.application.crm import CrmGatewayError, PersonData, PersonRecord
from leonaid.application.errors import AuthenticationRequired
from leonaid.application.member_buyers import MemberBuyerService
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)
from tools.delivery.http_configuration import FixtureIdentity, http_app


class BuyerCrm:
    def __init__(self, person_id: UUID):
        self.person = PersonRecord(
            person_id, PersonData("Anna", "Test", "anna@example.invalid")
        )
        self.calls = 0
        self.unavailable = False

    async def get_person(self, person_id, *, correlation_id):
        self.calls += 1
        if self.unavailable:
            raise CrmGatewayError(
                "crm_unavailable",
                "Unavailable",
                operation="get_person",
                correlation_id=correlation_id,
                retryable=True,
                outcome_unknown=False,
            )
        return (
            self.person if self.person and self.person.twenty_id == person_id else None
        )


class FreshIdentity(FixtureIdentity):
    fresh = True

    async def authenticate_fresh(self, token):
        actor = await self.authenticate(token)
        if not self.fresh:
            raise AuthenticationRequired(
                "fresh_login_required", "Bitte erneut anmelden."
            )
        return actor


async def prove_member_buyers(
    pool: asyncpg.Pool, action_id: UUID, admin_id: UUID
) -> None:
    now = datetime.now(timezone.utc)
    anna_id, colleague_id, person_id = uuid4(), uuid4(), uuid4()
    for user_id in (anna_id, colleague_id):
        await pool.execute(
            "INSERT INTO user_account(id,email,display_name,status) VALUES ($1,$2,'Test','active')",
            user_id,
            f"{user_id}@example.invalid",
        )
        await pool.execute(
            "INSERT INTO action_membership(id,action_id,user_id,role) VALUES($1,$2,$3,'acquirer')",
            uuid4(),
            action_id,
            user_id,
        )
        await pool.execute(
            "INSERT INTO acquisition_assignment(id,action_id,twenty_person_id,acquirer_user_id) VALUES($1,$2,$3,$4)",
            uuid4(),
            action_id,
            person_id,
            user_id,
        )

    def actor(user_id, role=ActionRole.ACQUIRER, global_roles=frozenset()):
        return IdentityPrincipal(
            UserAccount(
                user_id, f"{user_id}@example.invalid", "Test", AccountStatus.ACTIVE
            ),
            global_roles,
            (ActionMembership(uuid4(), action_id, "Test", user_id, role, now),),
        )

    anna = actor(anna_id)
    admin = actor(
        admin_id, ActionRole.CHARITY_ADMIN, frozenset({GlobalRole.SYSTEM_ADMIN})
    )
    app, _ = http_app(admin)
    identity = FreshIdentity(admin)
    app.state.identity_service = identity
    crm = BuyerCrm(person_id)
    service = MemberBuyerService(AsyncpgMemberBuyerRepository(pool), crm)
    app.state.member_buyer_service = service
    app.state.commitment_service = CommitmentService(
        AsyncpgCommitmentRepository(pool), service
    )
    path = f"/api/v1/admin/members/{anna_id}/buyer-link"
    context_path = f"/api/v1/actions/{action_id}/commitment-capture"
    body = {"twentyPersonId": str(person_id), "expectedRevision": 0}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(path)
        assert response.status_code == 200 and response.json()["revision"] == 0
        assert response.headers["cache-control"] == "no-store"
        identity.current = anna
        assert (await client.get(context_path)).json()[
            "selfBuyerUnavailableReason"
        ] == "not_linked"
        assert (await client.get(path)).status_code == 403
        assert (await client.put(path, json=body)).status_code == 403
        assert crm.calls == 0  # Authorization precedes CRM lookup.
        identity.current = None
        assert (await client.get(path)).status_code == 401
        assert (await client.put(path, json=body)).status_code == 401
        identity.current = admin
        identity.fresh = False
        assert (await client.put(path, json=body)).status_code == 401
        identity.fresh = True
        assert (
            await client.put(path, json={**body, "twentyPersonId": str(uuid4())})
        ).status_code == 409
        results = await asyncio.gather(
            client.put(path, json=body), client.put(path, json=body)
        )
        assert sorted(r.status_code for r in results) == [200, 409], [
            r.text for r in results
        ]
        saved = next(r.json() for r in results if r.status_code == 200)
        assert saved["buyer"]["displayName"] == "Anna Test" and saved["revision"] == 1
        assert saved["verifiedByUserId"] == str(admin_id) and saved["verifiedAt"]
        # One CRM person cannot serve as two members' verified identity.
        other_path = f"/api/v1/admin/members/{colleague_id}/buyer-link"
        response = await client.put(other_path, json=body)
        assert (
            response.status_code == 409
            and response.json()["code"] == "member_buyer_person_already_linked"
        )
        assert (await client.get(other_path)).json()["revision"] == 0
        identity.current = anna
        context = (await client.get(context_path)).json()
        assert context["selfBuyer"]["twentyId"] == str(person_id)
        assert context["selfBuyerUnavailableReason"] is None
        crm.unavailable = True
        assert (await client.get(context_path)).json()[
            "selfBuyerUnavailableReason"
        ] == "crm_unavailable"
        crm.unavailable = False
        original_person = crm.person
        crm.person = None
        assert (await client.get(context_path)).json()[
            "selfBuyerUnavailableReason"
        ] == "person_missing"
        crm.person = original_person
        # The verified snapshot is used through the existing buyer contract.
        order_body = {
            "source": "acquisition",
            "buyer": context["selfBuyer"],
            "lines": [
                {
                    "offeringId": context["offerings"][0]["id"],
                    "quantity": 1,
                    "unit": "box",
                }
            ],
        }
        order_path = f"/api/v1/actions/{action_id}/commitments"
        headers = {"Idempotency-Key": f"self-buyer:{uuid4()}"}
        response = await client.post(order_path, json=order_body, headers=headers)
        assert response.status_code == 201, response.text
        assert (await client.post(order_path, json=order_body, headers=headers)).json()[
            "replayed"
        ]
        identity.current = actor(colleague_id)
        assert (
            await client.post(order_path, json=order_body, headers=headers)
        ).status_code == 403
        identity.current = anna
        await pool.execute(
            "DELETE FROM acquisition_assignment WHERE acquirer_user_id=$1", anna_id
        )
        assert (await client.get(context_path)).json()[
            "selfBuyerUnavailableReason"
        ] == "not_assigned"
        assert (
            await client.post(order_path, json=order_body, headers=headers)
        ).status_code == 403
        assert (
            await client.post(
                order_path,
                json=order_body,
                headers={"Idempotency-Key": f"self-buyer:{uuid4()}"},
            )
        ).status_code == 403
        identity.current = admin
        response = await client.put(
            path, json={"twentyPersonId": None, "expectedRevision": 1}
        )
        assert response.status_code == 200 and response.json()["revision"] == 2
        assert response.json()["verifiedAt"] is None
        # Still cannot relink an existing CRM person without a live acquisition assignment.
        response = await client.put(path, json={**body, "expectedRevision": 2})
        assert (
            response.status_code == 409
            and response.json()["code"] == "member_buyer_assignment_required"
        )
        identity.current = anna
        assert (await client.get(context_path)).json()[
            "selfBuyerUnavailableReason"
        ] == "not_linked"
        identity.current = replace(
            anna, account=replace(anna.account, status=AccountStatus.SUSPENDED)
        )
        assert (await client.get(context_path)).status_code == 403
        events = await pool.fetch(
            "SELECT payload FROM audit_event WHERE entity_id=$1 AND event_type='member_buyer_link_changed'",
            anna_id,
        )
        assert (
            len(events) == 2
            and "Anna" not in str(events)
            and str(person_id) not in str(events)
        )
    print(
        "KLF-050 member buyers PASS: explicit admin verification, fresh-login entrypoint, unique/revision conflict, same-action assignment, missing/failed CRM, unlink, self draft, revoked/foreign replay denied (synthetic identity and CRM)"
    )
