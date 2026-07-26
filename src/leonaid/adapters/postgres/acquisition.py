"""PostgreSQL row scopes for acquisition-facing Core operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from leonaid.application.acquisition import (
    AcquisitionActivity,
    AcquisitionActivityPage,
    AcquisitionDocument,
    AcquisitionPolicyRepository,
    PartyAssignmentRoster,
)
from leonaid.application.crm import CrmPartyKind
from leonaid.domain.policies import AcquisitionAccessLevel, AuthorizedPartyScope


class AsyncpgAcquisitionPolicyRepository(AcquisitionPolicyRepository):
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
