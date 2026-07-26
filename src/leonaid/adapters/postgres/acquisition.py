"""PostgreSQL row scopes for acquisition-facing Core operations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.acquisition import (
    AcquisitionActivity,
    AcquisitionActivityPage,
    AcquisitionDocument,
    AcquisitionPolicyRepository,
    PartyAssignmentRoster,
)
from leonaid.application.crm import CrmPartyKind
from leonaid.application.sponsor_matching import (
    AssignedAcquirer,
    RecordedAssignment,
    SponsorMatchingRepository,
    SponsorResolutionOutcome,
)
from leonaid.domain.policies import AcquisitionAccessLevel, AuthorizedPartyScope


class AsyncpgAcquisitionPolicyRepository(
    AcquisitionPolicyRepository,
    SponsorMatchingRepository,
):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def authorized_scope(
        self,
        actor_user_id: UUID,
        action_id: UUID,
        *,
        evaluated_at: datetime,
    ) -> AuthorizedPartyScope | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                WITH actor_access AS (
                    SELECT
                        action.id AS action_id,
                        CASE
                            WHEN EXISTS (
                                SELECT 1
                                FROM user_global_role AS global_role
                                WHERE global_role.user_id = $1
                                  AND global_role.role = 'system_admin'
                            ) THEN 'manage'
                            WHEN EXISTS (
                                SELECT 1
                                FROM action_membership AS membership
                                WHERE membership.action_id = action.id
                                  AND membership.user_id = $1
                                  AND membership.role = 'charity_admin'
                                  AND membership.active_from <= $3
                                  AND (
                                    membership.active_until IS NULL
                                    OR membership.active_until > $3
                                  )
                            ) THEN 'manage'
                            WHEN EXISTS (
                                SELECT 1
                                FROM action_membership AS membership
                                WHERE membership.action_id = action.id
                                  AND membership.user_id = $1
                                  AND membership.role = 'acquirer'
                                  AND membership.active_from <= $3
                                  AND (
                                    membership.active_until IS NULL
                                    OR membership.active_until > $3
                                  )
                            ) THEN 'assigned'
                            ELSE NULL
                        END AS access_level
                    FROM charity_action AS action
                    WHERE action.id = $2
                ),
                visible_assignment AS (
                    SELECT assignment.*
                    FROM actor_access AS access
                    JOIN acquisition_assignment AS assignment
                      ON assignment.action_id = access.action_id
                    WHERE access.access_level = 'manage'
                       OR assignment.acquirer_user_id = $1
                )
                SELECT
                    access.access_level,
                    COALESCE(
                        array_agg(DISTINCT assignment.twenty_company_id)
                        FILTER (WHERE assignment.twenty_company_id IS NOT NULL),
                        ARRAY[]::uuid[]
                    ) AS company_ids,
                    COALESCE(
                        array_agg(DISTINCT assignment.twenty_person_id)
                        FILTER (WHERE assignment.twenty_person_id IS NOT NULL),
                        ARRAY[]::uuid[]
                    ) AS person_ids
                FROM actor_access AS access
                LEFT JOIN visible_assignment AS assignment
                  ON assignment.action_id = access.action_id
                WHERE access.access_level IS NOT NULL
                GROUP BY access.access_level
                """,
                actor_user_id,
                action_id,
                evaluated_at,
            )
        if row is None:
            return None
        return AuthorizedPartyScope(
            action_id=action_id,
            actor_user_id=actor_user_id,
            access_level=AcquisitionAccessLevel(str(row["access_level"])),
            company_ids=frozenset(row["company_ids"]),
            person_ids=frozenset(row["person_ids"]),
        )

    async def assignment_roster(
        self,
        scope: AuthorizedPartyScope,
        *,
        evaluated_at: datetime,
    ) -> PartyAssignmentRoster:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT
                    assignment.twenty_company_id,
                    assignment.twenty_person_id,
                    array_agg(
                        DISTINCT assignment.acquirer_user_id
                        ORDER BY assignment.acquirer_user_id
                    ) AS acquirer_ids
                FROM acquisition_assignment AS assignment
                JOIN action_membership AS membership
                  ON membership.action_id = assignment.action_id
                 AND membership.user_id = assignment.acquirer_user_id
                 AND membership.role = 'acquirer'
                 AND membership.active_from <= $4
                 AND (
                    membership.active_until IS NULL
                    OR membership.active_until > $4
                 )
                WHERE assignment.action_id = $1
                  AND (
                    assignment.twenty_company_id = ANY($2::uuid[])
                    OR assignment.twenty_person_id = ANY($3::uuid[])
                  )
                GROUP BY
                    assignment.twenty_company_id,
                    assignment.twenty_person_id
                """,
                scope.action_id,
                list(scope.company_ids),
                list(scope.person_ids),
                evaluated_at,
            )
        company_assignees: dict[UUID, tuple[UUID, ...]] = {}
        person_assignees: dict[UUID, tuple[UUID, ...]] = {}
        for row in rows:
            assignees = tuple(row["acquirer_ids"])
            if row["twenty_company_id"] is not None:
                company_assignees[row["twenty_company_id"]] = assignees
            if row["twenty_person_id"] is not None:
                person_assignees[row["twenty_person_id"]] = assignees
        return PartyAssignmentRoster(
            company_assignees=company_assignees,
            person_assignees=person_assignees,
        )

    async def can_self_assign(
        self,
        actor_user_id: UUID,
        action_id: UUID,
        *,
        evaluated_at: datetime,
    ) -> bool:
        async with self._pool.acquire() as connection:
            allowed = await connection.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM charity_action AS action
                    JOIN charity_action_capability AS capability
                      ON capability.action_id = action.id
                     AND capability.capability = 'acquisition'
                    JOIN action_membership AS membership
                      ON membership.action_id = action.id
                     AND membership.user_id = $1
                     AND membership.role = 'acquirer'
                     AND membership.active_from <= $3
                     AND (
                        membership.active_until IS NULL
                        OR membership.active_until > $3
                     )
                    JOIN user_account AS account
                      ON account.id = membership.user_id
                     AND account.status = 'active'
                    WHERE action.id = $2
                )
                """,
                actor_user_id,
                action_id,
                evaluated_at,
            )
        return bool(allowed)

    async def assigned_acquirers(
        self,
        action_id: UUID,
        party_kind: CrmPartyKind,
        party_ids: tuple[UUID, ...],
        *,
        evaluated_at: datetime,
    ) -> dict[UUID, tuple[AssignedAcquirer, ...]]:
        if not party_ids:
            return {}
        party_column = (
            "assignment.twenty_company_id"
            if party_kind is CrmPartyKind.COMPANY
            else "assignment.twenty_person_id"
        )
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                f"""
                SELECT
                    {party_column} AS party_id,
                    account.id AS user_id,
                    account.display_name
                FROM acquisition_assignment AS assignment
                JOIN action_membership AS membership
                  ON membership.action_id = assignment.action_id
                 AND membership.user_id = assignment.acquirer_user_id
                 AND membership.role = 'acquirer'
                 AND membership.active_from <= $3
                 AND (
                    membership.active_until IS NULL
                    OR membership.active_until > $3
                 )
                JOIN user_account AS account
                  ON account.id = assignment.acquirer_user_id
                 AND account.status = 'active'
                WHERE assignment.action_id = $1
                  AND {party_column} = ANY($2::uuid[])
                ORDER BY
                    {party_column},
                    lower(account.display_name),
                    account.id
                """,
                action_id,
                list(party_ids),
                evaluated_at,
            )
        grouped: dict[UUID, list[AssignedAcquirer]] = {}
        for row in rows:
            grouped.setdefault(row["party_id"], []).append(
                AssignedAcquirer(
                    user_id=row["user_id"],
                    display_name=str(row["display_name"]),
                )
            )
        return {party_id: tuple(assignees) for party_id, assignees in grouped.items()}

    async def record_resolution(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        party_kind: CrmPartyKind,
        twenty_id: UUID,
        outcome: SponsorResolutionOutcome,
        normalized_key: str,
        prior_assignee_ids: tuple[UUID, ...],
        request_id: str,
        occurred_at: datetime,
    ) -> RecordedAssignment | None:
        assignment_id = uuid4()
        company_id = twenty_id if party_kind is CrmPartyKind.COMPANY else None
        person_id = twenty_id if party_kind is CrmPartyKind.PERSON else None
        conflict_target = (
            "(action_id, twenty_company_id, acquirer_user_id) "
            "WHERE twenty_company_id IS NOT NULL"
            if company_id is not None
            else "(action_id, twenty_person_id, acquirer_user_id) "
            "WHERE twenty_person_id IS NOT NULL"
        )
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                allowed = await connection.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM action_membership AS membership
                        JOIN user_account AS account
                          ON account.id = membership.user_id
                         AND account.status = 'active'
                        JOIN charity_action_capability AS capability
                          ON capability.action_id = membership.action_id
                         AND capability.capability = 'acquisition'
                        WHERE membership.action_id = $1
                          AND membership.user_id = $2
                          AND membership.role = 'acquirer'
                          AND membership.active_from <= $3
                          AND (
                            membership.active_until IS NULL
                            OR membership.active_until > $3
                          )
                    )
                    """,
                    action_id,
                    actor_user_id,
                    occurred_at,
                )
                if not allowed:
                    return None
                inserted_id = await connection.fetchval(
                    f"""
                    INSERT INTO acquisition_assignment (
                        id,
                        action_id,
                        twenty_company_id,
                        twenty_person_id,
                        acquirer_user_id,
                        status,
                        priority,
                        created_at,
                        updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, 'open', 0, $6, $6)
                    ON CONFLICT {conflict_target} DO NOTHING
                    RETURNING id
                    """,
                    assignment_id,
                    action_id,
                    company_id,
                    person_id,
                    actor_user_id,
                    occurred_at,
                )
                created = inserted_id is not None
                if inserted_id is None:
                    inserted_id = await connection.fetchval(
                        """
                        SELECT id
                        FROM acquisition_assignment
                        WHERE action_id = $1
                          AND acquirer_user_id = $2
                          AND (
                            ($3::uuid IS NOT NULL AND twenty_company_id = $3)
                            OR ($4::uuid IS NOT NULL AND twenty_person_id = $4)
                          )
                        """,
                        action_id,
                        actor_user_id,
                        company_id,
                        person_id,
                    )
                if inserted_id is None:
                    raise RuntimeError(
                        "Akquise-Zuordnung konnte nicht ermittelt werden."
                    )
                if created:
                    await connection.execute(
                        """
                        INSERT INTO acquisition_assignment_history (
                            id,
                            assignment_id,
                            changed_by_user_id,
                            previous_state,
                            new_state,
                            changed_at
                        )
                        VALUES ($1, $2, $3, '{}'::jsonb, $4::jsonb, $5)
                        """,
                        uuid4(),
                        inserted_id,
                        actor_user_id,
                        json.dumps(
                            {
                                "status": "open",
                                "priority": 0,
                                "nextAction": None,
                                "dueAt": None,
                            },
                            separators=(",", ":"),
                        ),
                        occurred_at,
                    )
                await connection.execute(
                    """
                    INSERT INTO audit_event (
                        id,
                        action_id,
                        actor_user_id,
                        event_type,
                        entity_type,
                        entity_id,
                        request_id,
                        payload,
                        occurred_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
                    """,
                    uuid4(),
                    action_id,
                    actor_user_id,
                    (
                        "sponsor_party_created"
                        if outcome is SponsorResolutionOutcome.CREATED
                        else "sponsor_party_reused"
                    ),
                    f"twenty_{party_kind.value}",
                    twenty_id,
                    request_id,
                    json.dumps(
                        {
                            "normalizedKey": normalized_key,
                            "assignmentId": str(inserted_id),
                            "assignmentCreated": created,
                            "priorAssigneeIds": [
                                str(item) for item in prior_assignee_ids
                            ],
                        },
                        separators=(",", ":"),
                    ),
                    occurred_at,
                )
        return RecordedAssignment(assignment_id=inserted_id, created=created)

    async def activities(
        self,
        scope: AuthorizedPartyScope,
        *,
        offset: int,
        limit: int,
    ) -> AcquisitionActivityPage:
        visibility, parameters = self._visibility(scope)
        async with self._pool.acquire() as connection:
            total = await connection.fetchval(
                f"""
                SELECT count(*)
                FROM acquisition_activity AS activity
                WHERE activity.action_id = $1
                  AND ({visibility})
                """,
                *parameters,
            )
            rows = await connection.fetch(
                f"""
                SELECT
                    activity.id,
                    activity.action_id,
                    activity.twenty_company_id,
                    activity.twenty_person_id,
                    activity.actor_user_id,
                    activity.outcome,
                    activity.channel,
                    activity.note,
                    activity.occurred_at
                FROM acquisition_activity AS activity
                WHERE activity.action_id = $1
                  AND ({visibility})
                ORDER BY activity.occurred_at DESC, activity.id
                OFFSET ${len(parameters) + 1}
                LIMIT ${len(parameters) + 2}
                """,
                *parameters,
                offset,
                limit,
            )
        return AcquisitionActivityPage(
            items=tuple(self._activity(row) for row in rows),
            total=int(total),
            offset=offset,
            limit=limit,
        )

    async def document(
        self,
        scope: AuthorizedPartyScope,
        document_id: UUID,
    ) -> AcquisitionDocument | None:
        visibility, parameters = self._visibility(
            scope,
            company_column="document.twenty_company_id",
            person_column="document.twenty_person_id",
        )
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                f"""
                SELECT
                    document.id,
                    document.action_id,
                    document.twenty_company_id,
                    document.twenty_person_id,
                    document.document_type,
                    document.media_type,
                    document.sha256,
                    document.version,
                    document.created_at
                FROM generated_document AS document
                WHERE document.action_id = $1
                  AND document.id = ${len(parameters) + 1}
                  AND ({visibility})
                """,
                *parameters,
                document_id,
            )
        if row is None:
            return None
        company_id = row["twenty_company_id"]
        person_id = row["twenty_person_id"]
        if company_id is not None:
            party_kind = CrmPartyKind.COMPANY
            party_id = company_id
        elif person_id is not None:
            party_kind = CrmPartyKind.PERSON
            party_id = person_id
        else:
            return None
        return AcquisitionDocument(
            id=row["id"],
            action_id=row["action_id"],
            party_kind=party_kind,
            party_id=party_id,
            document_type=str(row["document_type"]),
            media_type=str(row["media_type"]),
            sha256=str(row["sha256"]),
            version=int(row["version"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _visibility(
        scope: AuthorizedPartyScope,
        *,
        company_column: str = "activity.twenty_company_id",
        person_column: str = "activity.twenty_person_id",
    ) -> tuple[str, tuple[object, ...]]:
        if scope.access_level is AcquisitionAccessLevel.MANAGE:
            return "TRUE", (scope.action_id,)
        return (
            f"({company_column} = ANY($2::uuid[]) "
            f"OR {person_column} = ANY($3::uuid[]))",
            (
                scope.action_id,
                list(scope.company_ids),
                list(scope.person_ids),
            ),
        )

    @staticmethod
    def _activity(row: asyncpg.Record) -> AcquisitionActivity:
        company_id = row["twenty_company_id"]
        person_id = row["twenty_person_id"]
        if company_id is not None:
            party_kind = CrmPartyKind.COMPANY
            party_id = company_id
        elif person_id is not None:
            party_kind = CrmPartyKind.PERSON
            party_id = person_id
        else:
            raise RuntimeError("Eine Akquiseaktivität besitzt keinen Partnerbezug.")
        return AcquisitionActivity(
            id=row["id"],
            action_id=row["action_id"],
            party_kind=party_kind,
            party_id=party_id,
            actor_user_id=row["actor_user_id"],
            outcome=str(row["outcome"]),
            channel=str(row["channel"]),
            note=row["note"],
            occurred_at=row["occurred_at"],
        )
