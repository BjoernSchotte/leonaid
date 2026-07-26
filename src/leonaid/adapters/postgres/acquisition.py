"""PostgreSQL row scopes for acquisition-facing Core operations."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
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
from leonaid.application.activities import (
    AcquisitionActivityRepository,
    ActivityRecordingResult,
    RecordedAcquisitionActivity,
)
from leonaid.application.assignments import (
    AssignmentCreateResult,
    AssignmentHandoverResult,
    AssignmentManagementRepository,
)
from leonaid.application.crm import CrmPartyKind
from leonaid.application.errors import Conflict
from leonaid.application.sponsor_matching import (
    AssignedAcquirer,
    RecordedAssignment,
    SponsorMatchingRepository,
    SponsorResolution,
    SponsorResolutionCommand,
    SponsorResolutionOutcome,
)
from leonaid.domain.policies import AcquisitionAccessLevel, AuthorizedPartyScope
from leonaid.domain.acquisition import (
    AcquisitionAssignment,
    ActivityCapture,
    ActivityChannel,
    ActivityOutcome,
    AssignmentHistoryEntry,
    AssignmentPartyKind,
    AssignmentState,
    AssignmentStatus,
)


SPONSOR_RESOLUTION_COMMAND_TYPE = "resolve_sponsor_match_v1"


def _resolution_receipt(result: SponsorResolution) -> dict[str, object]:
    return {
        "assignmentCreated": result.assignment_created,
        "assignmentId": str(result.assignment_id),
        "contactTwentyId": (
            str(result.contact_twenty_id)
            if result.contact_twenty_id is not None
            else None
        ),
        "displayName": result.display_name,
        "normalizedKey": result.normalized_key,
        "outcome": result.outcome.value,
        "partyKind": result.party_kind.value,
        "priorAssignees": [
            {
                "displayName": assignee.display_name,
                "userId": str(assignee.user_id),
            }
            for assignee in result.prior_assignees
        ],
        "twentyId": str(result.twenty_id),
    }


def _replayed_resolution(value: object) -> SponsorResolution:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError("Sponsor-Befehlsnachweis besitzt kein Ergebnis.")
    assignee_values = value.get("priorAssignees")
    if not isinstance(assignee_values, list):
        raise RuntimeError("Sponsor-Befehlsnachweis besitzt keine Zuordnungen.")
    try:
        prior_assignees = tuple(
            AssignedAcquirer(
                user_id=UUID(str(item["userId"])),
                display_name=str(item["displayName"]),
            )
            for item in assignee_values
            if isinstance(item, dict)
        )
        if len(prior_assignees) != len(assignee_values):
            raise ValueError("Ungültige Akquisiteur-Zuordnung")
        contact_value = value.get("contactTwentyId")
        return SponsorResolution(
            outcome=SponsorResolutionOutcome(str(value["outcome"])),
            party_kind=CrmPartyKind(str(value["partyKind"])),
            twenty_id=UUID(str(value["twentyId"])),
            display_name=str(value["displayName"]),
            normalized_key=str(value["normalizedKey"]),
            assignment_id=UUID(str(value["assignmentId"])),
            assignment_created=bool(value["assignmentCreated"]),
            prior_assignees=prior_assignees,
            contact_twenty_id=(
                UUID(str(contact_value)) if contact_value is not None else None
            ),
            replayed=True,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(
            "Sponsor-Befehlsnachweis ist unvollständig oder ungültig."
        ) from error


class AsyncpgSponsorResolutionCommand:
    def __init__(
        self,
        repository: AsyncpgAcquisitionPolicyRepository,
        connection: asyncpg.Connection[Any],
        existing_result: SponsorResolution | None,
        idempotency_key: str,
    ) -> None:
        self._repository = repository
        self._connection = connection
        self._existing_result = existing_result
        self._idempotency_key = idempotency_key

    @property
    def existing_result(self) -> SponsorResolution | None:
        return self._existing_result

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
        return await self._repository.record_resolution(
            action_id=action_id,
            actor_user_id=actor_user_id,
            party_kind=party_kind,
            twenty_id=twenty_id,
            outcome=outcome,
            normalized_key=normalized_key,
            prior_assignee_ids=prior_assignee_ids,
            request_id=request_id,
            occurred_at=occurred_at,
        )

    async def complete(self, result: SponsorResolution) -> None:
        status = await self._connection.execute(
            """
            UPDATE command_receipt
            SET result = $2::jsonb,
                completed_at = CURRENT_TIMESTAMP
            WHERE idempotency_key = $1
              AND command_type = $3
              AND result IS NULL
            """,
            self._idempotency_key,
            json.dumps(_resolution_receipt(result), separators=(",", ":")),
            SPONSOR_RESOLUTION_COMMAND_TYPE,
        )
        if status != "UPDATE 1":
            raise RuntimeError(
                "Sponsor-Befehlsnachweis konnte nicht abgeschlossen werden."
            )


class AsyncpgAcquisitionPolicyRepository(
    AcquisitionPolicyRepository,
    SponsorMatchingRepository,
    AssignmentManagementRepository,
    AcquisitionActivityRepository,
):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    @asynccontextmanager
    async def resolution_command(
        self,
        *,
        lock_key: str,
        idempotency_key: str,
        request_hash: str,
    ) -> AsyncIterator[SponsorResolutionCommand]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    lock_key,
                )
                inserted = await connection.fetchval(
                    """
                    INSERT INTO command_receipt (
                        idempotency_key, command_type, request_hash
                    )
                    VALUES ($1, $2, $3)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING true
                    """,
                    idempotency_key,
                    SPONSOR_RESOLUTION_COMMAND_TYPE,
                    request_hash,
                )
                existing_result: SponsorResolution | None = None
                if not inserted:
                    receipt = await connection.fetchrow(
                        """
                        SELECT command_type, request_hash, result
                        FROM command_receipt
                        WHERE idempotency_key = $1
                        FOR UPDATE
                        """,
                        idempotency_key,
                    )
                    if receipt is None:
                        raise RuntimeError(
                            "Sponsor-Befehlsnachweis verschwand während der Auflösung."
                        )
                    if (
                        str(receipt["command_type"]) != SPONSOR_RESOLUTION_COMMAND_TYPE
                        or str(receipt["request_hash"]) != request_hash
                    ):
                        raise Conflict(
                            "idempotency_conflict",
                            "Diese Vorgangs-ID wurde bereits für andere "
                            "Eingaben verwendet.",
                        )
                    if receipt["result"] is None:
                        raise Conflict(
                            "idempotency_incomplete",
                            "Die vorherige Verarbeitung ist noch nicht "
                            "abgeschlossen. Bitte versuche es erneut.",
                        )
                    existing_result = _replayed_resolution(receipt["result"])

                yield AsyncpgSponsorResolutionCommand(
                    self,
                    connection,
                    existing_result,
                    idempotency_key,
                )

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
                       OR (
                            assignment.acquirer_user_id = $1
                            AND assignment.status <> 'handed_over'
                       )
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
                  AND assignment.status <> 'handed_over'
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
                  AND assignment.status <> 'handed_over'
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
                persisted = await connection.fetchrow(
                    """
                    SELECT status, priority, next_action, due_at
                    FROM acquisition_assignment
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    inserted_id,
                )
                if persisted is None:
                    raise RuntimeError("Akquise-Zuordnung konnte nicht gelesen werden.")
                reactivated = not created and str(persisted["status"]) == "handed_over"
                if reactivated:
                    await connection.execute(
                        """
                        UPDATE acquisition_assignment
                        SET status = 'open',
                            priority = 0,
                            next_action = NULL,
                            due_at = NULL,
                            revision = revision + 1,
                            updated_at = $2
                        WHERE id = $1
                        """,
                        inserted_id,
                        occurred_at,
                    )
                assignment_added = created or reactivated
                if assignment_added:
                    previous_state: dict[str, object] = {}
                    if reactivated:
                        previous_state = {
                            "status": str(persisted["status"]),
                            "priority": int(persisted["priority"]),
                            "nextAction": persisted["next_action"],
                            "dueAt": (
                                persisted["due_at"].isoformat()
                                if persisted["due_at"] is not None
                                else None
                            ),
                            "acquirerUserId": str(actor_user_id),
                        }
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
                        VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6)
                        """,
                        uuid4(),
                        inserted_id,
                        actor_user_id,
                        json.dumps(previous_state, separators=(",", ":")),
                        json.dumps(
                            {
                                "status": "open",
                                "priority": 0,
                                "nextAction": None,
                                "dueAt": None,
                                "acquirerUserId": str(actor_user_id),
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
                            "assignmentCreated": assignment_added,
                            "assignmentReactivated": reactivated,
                            "priorAssigneeIds": [
                                str(item) for item in prior_assignee_ids
                            ],
                        },
                        separators=(",", ":"),
                    ),
                    occurred_at,
                )
        return RecordedAssignment(
            assignment_id=inserted_id,
            created=assignment_added,
        )

    async def get_assignment(
        self,
        action_id: UUID,
        assignment_id: UUID,
    ) -> AcquisitionAssignment | None:
        async with self._pool.acquire() as connection:
            row = await self._assignment_record(
                connection,
                action_id=action_id,
                assignment_id=assignment_id,
            )
        return self._assignment(row) if row is not None else None

    async def assignment_history(
        self,
        assignment_id: UUID,
    ) -> tuple[AssignmentHistoryEntry, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT
                    history.id,
                    history.assignment_id,
                    history.changed_by_user_id,
                    account.display_name AS changed_by_display_name,
                    history.previous_state,
                    history.new_state,
                    history.changed_at
                FROM acquisition_assignment_history AS history
                JOIN user_account AS account
                  ON account.id = history.changed_by_user_id
                WHERE history.assignment_id = $1
                ORDER BY history.changed_at, history.id
                """,
                assignment_id,
            )
        return tuple(self._history(item) for item in rows)

    async def create_proactive_assignment(
        self,
        *,
        action_id: UUID,
        party_kind: AssignmentPartyKind,
        party_id: UUID,
        acquirer_user_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> AssignmentCreateResult | None:
        company_id = party_id if party_kind is AssignmentPartyKind.COMPANY else None
        person_id = party_id if party_kind is AssignmentPartyKind.PERSON else None
        conflict_target = self._assignment_conflict_target(party_kind)
        assignment_id = uuid4()
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                allowed = await connection.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM charity_action AS action
                        JOIN charity_action_capability AS capability
                          ON capability.action_id = action.id
                         AND capability.capability = 'acquisition'
                        JOIN action_membership AS target_membership
                          ON target_membership.action_id = action.id
                         AND target_membership.user_id = $3
                         AND target_membership.role = 'acquirer'
                         AND target_membership.active_from <= $4
                         AND (
                            target_membership.active_until IS NULL
                            OR target_membership.active_until > $4
                         )
                        JOIN user_account AS target_account
                          ON target_account.id = target_membership.user_id
                         AND target_account.status = 'active'
                        WHERE action.id = $1
                          AND (
                            EXISTS (
                                SELECT 1
                                FROM user_global_role AS global_role
                                WHERE global_role.user_id = $2
                                  AND global_role.role = 'system_admin'
                            )
                            OR EXISTS (
                                SELECT 1
                                FROM action_membership AS actor_membership
                                WHERE actor_membership.action_id = action.id
                                  AND actor_membership.user_id = $2
                                  AND actor_membership.role = 'charity_admin'
                                  AND actor_membership.active_from <= $4
                                  AND (
                                    actor_membership.active_until IS NULL
                                    OR actor_membership.active_until > $4
                                  )
                            )
                          )
                    )
                    """,
                    action_id,
                    actor_user_id,
                    acquirer_user_id,
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
                        revision,
                        created_at,
                        updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, 'open', 0, 1, $6, $6)
                    ON CONFLICT {conflict_target} DO NOTHING
                    RETURNING id
                    """,
                    assignment_id,
                    action_id,
                    company_id,
                    person_id,
                    acquirer_user_id,
                    occurred_at,
                )
                created = inserted_id is not None
                if inserted_id is None:
                    inserted_id = await connection.fetchval(
                        """
                        SELECT assignment.id
                        FROM acquisition_assignment AS assignment
                        WHERE assignment.action_id = $1
                          AND assignment.acquirer_user_id = $2
                          AND (
                            ($3::uuid IS NOT NULL AND assignment.twenty_company_id = $3)
                            OR ($4::uuid IS NOT NULL AND assignment.twenty_person_id = $4)
                          )
                        FOR UPDATE
                        """,
                        action_id,
                        acquirer_user_id,
                        company_id,
                        person_id,
                    )
                if inserted_id is None:
                    raise RuntimeError(
                        "Proaktive Zuordnung konnte nicht ermittelt werden."
                    )
                row = await self._assignment_record(
                    connection,
                    action_id=action_id,
                    assignment_id=inserted_id,
                )
                if row is None:
                    raise RuntimeError(
                        "Proaktive Zuordnung konnte nicht gelesen werden."
                    )
                current = self._assignment(row)
                previous_snapshot: dict[str, object] = {}
                event_type = "acquisition_assignment_created"
                changed = created
                if not created and current.state.status is AssignmentStatus.HANDED_OVER:
                    previous_snapshot = current.state.snapshot(
                        acquirer_user_id=current.acquirer_user_id
                    )
                    await connection.execute(
                        """
                        UPDATE acquisition_assignment
                        SET status = 'open',
                            priority = 0,
                            next_action = NULL,
                            due_at = NULL,
                            revision = revision + 1,
                            updated_at = $2
                        WHERE id = $1
                        """,
                        current.id,
                        occurred_at,
                    )
                    row = await self._assignment_record(
                        connection,
                        action_id=action_id,
                        assignment_id=current.id,
                    )
                    if row is None:
                        raise RuntimeError("Reaktivierte Zuordnung ist verschwunden.")
                    current = self._assignment(row)
                    event_type = "acquisition_assignment_reactivated"
                    changed = True
                if changed:
                    await self._append_history(
                        connection,
                        assignment=current,
                        actor_user_id=actor_user_id,
                        previous_state=previous_snapshot,
                        occurred_at=occurred_at,
                    )
                    await self._append_assignment_audit(
                        connection,
                        assignment=current,
                        actor_user_id=actor_user_id,
                        event_type=event_type,
                        request_id=request_id,
                        payload={
                            "partyKind": party_kind.value,
                            "partyId": str(party_id),
                            "acquirerUserId": str(acquirer_user_id),
                            "created": created,
                        },
                        occurred_at=occurred_at,
                    )
        return AssignmentCreateResult(assignment=current, created=created)

    async def save_assignment(
        self,
        previous: AcquisitionAssignment,
        changed: AcquisitionAssignment,
        *,
        actor_user_id: UUID,
        actor_may_manage: bool,
        request_id: str,
        occurred_at: datetime,
    ) -> AcquisitionAssignment | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                updated_id = await connection.fetchval(
                    """
                    UPDATE acquisition_assignment AS assignment
                    SET status = $4,
                        priority = $5,
                        next_action = $6,
                        due_at = $7,
                        revision = $8,
                        updated_at = $9
                    WHERE assignment.id = $1
                      AND assignment.action_id = $2
                      AND assignment.revision = $3
                      AND (
                        (
                          $11::boolean
                          AND (
                            EXISTS (
                              SELECT 1
                              FROM user_global_role AS global_role
                              WHERE global_role.user_id = $10
                                AND global_role.role = 'system_admin'
                            )
                            OR EXISTS (
                              SELECT 1
                              FROM action_membership AS manager_membership
                              WHERE manager_membership.action_id = assignment.action_id
                                AND manager_membership.user_id = $10
                                AND manager_membership.role = 'charity_admin'
                                AND manager_membership.active_from <= $9
                                AND (
                                  manager_membership.active_until IS NULL
                                  OR manager_membership.active_until > $9
                                )
                            )
                          )
                        )
                        OR (
                          assignment.acquirer_user_id = $10
                          AND EXISTS (
                            SELECT 1
                            FROM action_membership AS own_membership
                            JOIN user_account AS own_account
                              ON own_account.id = own_membership.user_id
                             AND own_account.status = 'active'
                            WHERE own_membership.action_id = assignment.action_id
                              AND own_membership.user_id = $10
                              AND own_membership.role = 'acquirer'
                              AND own_membership.active_from <= $9
                              AND (
                                own_membership.active_until IS NULL
                                OR own_membership.active_until > $9
                              )
                          )
                        )
                      )
                    RETURNING assignment.id
                    """,
                    previous.id,
                    previous.action_id,
                    previous.revision,
                    changed.state.status.value,
                    changed.state.priority,
                    changed.state.next_action,
                    changed.state.due_at,
                    changed.revision,
                    occurred_at,
                    actor_user_id,
                    actor_may_manage,
                )
                if updated_id is None:
                    await self._raise_revision_if_changed(
                        connection,
                        previous.id,
                        previous.revision,
                    )
                    return None
                await self._append_history(
                    connection,
                    assignment=changed,
                    actor_user_id=actor_user_id,
                    previous_state=previous.state.snapshot(
                        acquirer_user_id=previous.acquirer_user_id
                    ),
                    occurred_at=occurred_at,
                )
                await self._append_assignment_audit(
                    connection,
                    assignment=changed,
                    actor_user_id=actor_user_id,
                    event_type="acquisition_assignment_updated",
                    request_id=request_id,
                    payload={
                        "previousRevision": previous.revision,
                        "revision": changed.revision,
                    },
                    occurred_at=occurred_at,
                )
                row = await self._assignment_record(
                    connection,
                    action_id=previous.action_id,
                    assignment_id=previous.id,
                )
        if row is None:
            raise RuntimeError("Aktualisierte Zuordnung konnte nicht gelesen werden.")
        return self._assignment(row)

    async def hand_over_assignment(
        self,
        previous: AcquisitionAssignment,
        changed: AcquisitionAssignment,
        *,
        target_acquirer_user_id: UUID,
        actor_user_id: UUID,
        actor_may_manage: bool,
        request_id: str,
        occurred_at: datetime,
    ) -> AssignmentHandoverResult | None:
        company_id = (
            previous.party_id
            if previous.party_kind is AssignmentPartyKind.COMPANY
            else None
        )
        person_id = (
            previous.party_id
            if previous.party_kind is AssignmentPartyKind.PERSON
            else None
        )
        conflict_target = self._assignment_conflict_target(previous.party_kind)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                source_id = await connection.fetchval(
                    """
                    SELECT assignment.id
                    FROM acquisition_assignment AS assignment
                    WHERE assignment.id = $1
                      AND assignment.action_id = $2
                      AND assignment.revision = $3
                      AND assignment.status <> 'handed_over'
                      AND (
                        (
                          $6::boolean
                          AND (
                            EXISTS (
                              SELECT 1
                              FROM user_global_role AS global_role
                              WHERE global_role.user_id = $4
                                AND global_role.role = 'system_admin'
                            )
                            OR EXISTS (
                              SELECT 1
                              FROM action_membership AS manager_membership
                              WHERE manager_membership.action_id = assignment.action_id
                                AND manager_membership.user_id = $4
                                AND manager_membership.role = 'charity_admin'
                                AND manager_membership.active_from <= $5
                                AND (
                                  manager_membership.active_until IS NULL
                                  OR manager_membership.active_until > $5
                                )
                            )
                          )
                        )
                        OR (
                          assignment.acquirer_user_id = $4
                          AND EXISTS (
                            SELECT 1
                            FROM action_membership AS own_membership
                            JOIN user_account AS own_account
                              ON own_account.id = own_membership.user_id
                             AND own_account.status = 'active'
                            WHERE own_membership.action_id = assignment.action_id
                              AND own_membership.user_id = $4
                              AND own_membership.role = 'acquirer'
                              AND own_membership.active_from <= $5
                              AND (
                                own_membership.active_until IS NULL
                                OR own_membership.active_until > $5
                              )
                          )
                        )
                      )
                    FOR UPDATE
                    """,
                    previous.id,
                    previous.action_id,
                    previous.revision,
                    actor_user_id,
                    occurred_at,
                    actor_may_manage,
                )
                if source_id is None:
                    await self._raise_revision_if_changed(
                        connection,
                        previous.id,
                        previous.revision,
                    )
                    return None
                target_available = await connection.fetchval(
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
                    previous.action_id,
                    target_acquirer_user_id,
                    occurred_at,
                )
                if not target_available:
                    return None
                target_id = uuid4()
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
                        next_action,
                        due_at,
                        revision,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, 'open', $6, $7, $8, 1, $9, $9
                    )
                    ON CONFLICT {conflict_target} DO NOTHING
                    RETURNING id
                    """,
                    target_id,
                    previous.action_id,
                    company_id,
                    person_id,
                    target_acquirer_user_id,
                    previous.state.priority,
                    previous.state.next_action,
                    previous.state.due_at,
                    occurred_at,
                )
                target_created = inserted_id is not None
                if inserted_id is None:
                    inserted_id = await connection.fetchval(
                        """
                        SELECT assignment.id
                        FROM acquisition_assignment AS assignment
                        WHERE assignment.action_id = $1
                          AND assignment.acquirer_user_id = $2
                          AND (
                            ($3::uuid IS NOT NULL AND assignment.twenty_company_id = $3)
                            OR ($4::uuid IS NOT NULL AND assignment.twenty_person_id = $4)
                          )
                        FOR UPDATE
                        """,
                        previous.action_id,
                        target_acquirer_user_id,
                        company_id,
                        person_id,
                    )
                if inserted_id is None:
                    raise RuntimeError("Übergabe-Ziel konnte nicht ermittelt werden.")
                target_row = await self._assignment_record(
                    connection,
                    action_id=previous.action_id,
                    assignment_id=inserted_id,
                )
                if target_row is None:
                    raise RuntimeError("Übergabe-Ziel konnte nicht gelesen werden.")
                target = self._assignment(target_row)
                target_previous: dict[str, object] = {}
                target_changed = target_created
                if (
                    not target_created
                    and target.state.status is AssignmentStatus.HANDED_OVER
                ):
                    target_previous = target.state.snapshot(
                        acquirer_user_id=target.acquirer_user_id
                    )
                    await connection.execute(
                        """
                        UPDATE acquisition_assignment
                        SET status = 'open',
                            priority = $2,
                            next_action = $3,
                            due_at = $4,
                            revision = revision + 1,
                            updated_at = $5
                        WHERE id = $1
                        """,
                        target.id,
                        previous.state.priority,
                        previous.state.next_action,
                        previous.state.due_at,
                        occurred_at,
                    )
                    target_row = await self._assignment_record(
                        connection,
                        action_id=previous.action_id,
                        assignment_id=target.id,
                    )
                    if target_row is None:
                        raise RuntimeError("Reaktiviertes Übergabe-Ziel fehlt.")
                    target = self._assignment(target_row)
                    target_changed = True
                await connection.execute(
                    """
                    UPDATE acquisition_assignment
                    SET status = 'handed_over',
                        revision = $2,
                        updated_at = $3
                    WHERE id = $1
                    """,
                    previous.id,
                    changed.revision,
                    occurred_at,
                )
                if target_changed:
                    await self._append_history(
                        connection,
                        assignment=target,
                        actor_user_id=actor_user_id,
                        previous_state=target_previous,
                        occurred_at=occurred_at,
                    )
                await self._append_history(
                    connection,
                    assignment=changed,
                    actor_user_id=actor_user_id,
                    previous_state=previous.state.snapshot(
                        acquirer_user_id=previous.acquirer_user_id
                    ),
                    occurred_at=occurred_at,
                )
                await self._append_assignment_audit(
                    connection,
                    assignment=changed,
                    actor_user_id=actor_user_id,
                    event_type="acquisition_assignment_handed_over",
                    request_id=request_id,
                    payload={
                        "targetAssignmentId": str(target.id),
                        "targetAcquirerUserId": str(target_acquirer_user_id),
                        "targetCreated": target_created,
                    },
                    occurred_at=occurred_at,
                )
                source_row = await self._assignment_record(
                    connection,
                    action_id=previous.action_id,
                    assignment_id=previous.id,
                )
        if source_row is None:
            raise RuntimeError("Übergebene Ausgangszuordnung fehlt.")
        return AssignmentHandoverResult(
            source=self._assignment(source_row),
            target=target,
            target_created=target_created,
        )

    async def active_assignments_for_actor(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        evaluated_at: datetime,
    ) -> tuple[AcquisitionAssignment, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT
                    assignment.id,
                    assignment.action_id,
                    assignment.twenty_company_id,
                    assignment.twenty_person_id,
                    assignment.acquirer_user_id,
                    account.display_name AS acquirer_display_name,
                    assignment.status,
                    assignment.priority,
                    assignment.next_action,
                    assignment.due_at,
                    assignment.revision,
                    assignment.created_at,
                    assignment.updated_at
                FROM acquisition_assignment AS assignment
                JOIN user_account AS account
                  ON account.id = assignment.acquirer_user_id
                 AND account.status = 'active'
                JOIN action_membership AS membership
                  ON membership.action_id = assignment.action_id
                 AND membership.user_id = assignment.acquirer_user_id
                 AND membership.role = 'acquirer'
                 AND membership.active_from <= $3
                 AND (
                    membership.active_until IS NULL
                    OR membership.active_until > $3
                 )
                JOIN charity_action_capability AS capability
                  ON capability.action_id = assignment.action_id
                 AND capability.capability = 'acquisition'
                WHERE assignment.action_id = $1
                  AND assignment.acquirer_user_id = $2
                  AND assignment.status <> 'handed_over'
                ORDER BY
                    assignment.due_at NULLS LAST,
                    assignment.priority DESC,
                    assignment.id
                """,
                action_id,
                actor_user_id,
                evaluated_at,
            )
        return tuple(self._assignment(row) for row in rows)

    async def active_assignment_for_actor(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        party_kind: AssignmentPartyKind,
        party_id: UUID,
        evaluated_at: datetime,
    ) -> AcquisitionAssignment | None:
        party_column = (
            "assignment.twenty_company_id"
            if party_kind is AssignmentPartyKind.COMPANY
            else "assignment.twenty_person_id"
        )
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                f"""
                SELECT
                    assignment.id,
                    assignment.action_id,
                    assignment.twenty_company_id,
                    assignment.twenty_person_id,
                    assignment.acquirer_user_id,
                    account.display_name AS acquirer_display_name,
                    assignment.status,
                    assignment.priority,
                    assignment.next_action,
                    assignment.due_at,
                    assignment.revision,
                    assignment.created_at,
                    assignment.updated_at
                FROM acquisition_assignment AS assignment
                JOIN user_account AS account
                  ON account.id = assignment.acquirer_user_id
                 AND account.status = 'active'
                JOIN action_membership AS membership
                  ON membership.action_id = assignment.action_id
                 AND membership.user_id = assignment.acquirer_user_id
                 AND membership.role = 'acquirer'
                 AND membership.active_from <= $4
                 AND (
                    membership.active_until IS NULL
                    OR membership.active_until > $4
                 )
                JOIN charity_action_capability AS capability
                  ON capability.action_id = assignment.action_id
                 AND capability.capability = 'acquisition'
                WHERE assignment.action_id = $1
                  AND assignment.acquirer_user_id = $2
                  AND {party_column} = $3
                  AND assignment.status <> 'handed_over'
                """,
                action_id,
                actor_user_id,
                party_id,
                evaluated_at,
            )
        return self._assignment(row) if row is not None else None

    async def activity_timeline_for_actor(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        evaluated_at: datetime,
        limit: int,
    ) -> tuple[RecordedAcquisitionActivity, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT
                    activity.id,
                    activity.action_id,
                    activity.assignment_id,
                    activity.twenty_company_id,
                    activity.twenty_person_id,
                    activity.actor_user_id,
                    actor.display_name AS actor_display_name,
                    activity.channel,
                    activity.outcome,
                    activity.note,
                    activity.next_action_snapshot,
                    activity.due_at_snapshot,
                    activity.assignment_revision,
                    activity.occurred_at
                FROM acquisition_activity AS activity
                JOIN user_account AS actor
                  ON actor.id = activity.actor_user_id
                WHERE activity.action_id = $1
                  AND activity.channel IN (
                    'phone', 'email', 'in_person'
                  )
                  AND activity.outcome IN (
                    'reached', 'no_answer', 'interested', 'follow_up',
                    'committed', 'declined'
                  )
                  AND EXISTS (
                    SELECT 1
                    FROM acquisition_assignment AS own_assignment
                    JOIN user_account AS own_account
                      ON own_account.id = own_assignment.acquirer_user_id
                     AND own_account.status = 'active'
                    JOIN action_membership AS membership
                      ON membership.action_id = own_assignment.action_id
                     AND membership.user_id = own_assignment.acquirer_user_id
                     AND membership.role = 'acquirer'
                     AND membership.active_from <= $3
                     AND (
                        membership.active_until IS NULL
                        OR membership.active_until > $3
                     )
                    WHERE own_assignment.action_id = activity.action_id
                      AND own_assignment.acquirer_user_id = $2
                      AND own_assignment.status <> 'handed_over'
                      AND (
                        (
                            activity.twenty_company_id IS NOT NULL
                            AND own_assignment.twenty_company_id =
                                activity.twenty_company_id
                        )
                        OR (
                            activity.twenty_person_id IS NOT NULL
                            AND own_assignment.twenty_person_id =
                                activity.twenty_person_id
                        )
                      )
                  )
                ORDER BY activity.occurred_at DESC, activity.id DESC
                LIMIT $4
                """,
                action_id,
                actor_user_id,
                evaluated_at,
                limit,
            )
        return tuple(self._recorded_activity(row) for row in rows)

    async def record_activity(
        self,
        previous: AcquisitionAssignment,
        changed: AcquisitionAssignment,
        capture: ActivityCapture,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> ActivityRecordingResult | None:
        activity_id = uuid4()
        company_id = (
            previous.party_id
            if previous.party_kind is AssignmentPartyKind.COMPANY
            else None
        )
        person_id = (
            previous.party_id
            if previous.party_kind is AssignmentPartyKind.PERSON
            else None
        )
        persisted_row: asyncpg.Record | None = None
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                persisted_revision = await connection.fetchval(
                    """
                    UPDATE acquisition_assignment AS assignment
                    SET status = $6,
                        priority = $7,
                        next_action = $8,
                        due_at = $9,
                        revision = revision + 1,
                        updated_at = $10
                    WHERE assignment.id = $1
                      AND assignment.action_id = $2
                      AND assignment.acquirer_user_id = $3
                      AND assignment.revision = $4
                      AND assignment.status <> 'handed_over'
                      AND EXISTS (
                        SELECT 1
                        FROM action_membership AS membership
                        JOIN user_account AS account
                          ON account.id = membership.user_id
                         AND account.status = 'active'
                        JOIN charity_action_capability AS capability
                          ON capability.action_id = membership.action_id
                         AND capability.capability = 'acquisition'
                        WHERE membership.action_id = assignment.action_id
                          AND membership.user_id = assignment.acquirer_user_id
                          AND membership.role = 'acquirer'
                          AND membership.active_from <= $5
                          AND (
                            membership.active_until IS NULL
                            OR membership.active_until > $5
                          )
                      )
                    RETURNING revision
                    """,
                    previous.id,
                    previous.action_id,
                    actor_user_id,
                    previous.revision,
                    occurred_at,
                    changed.state.status.value,
                    changed.state.priority,
                    changed.state.next_action,
                    changed.state.due_at,
                    occurred_at,
                )
                if persisted_revision is None:
                    await self._raise_revision_if_changed(
                        connection,
                        previous.id,
                        previous.revision,
                    )
                    return None
                if int(persisted_revision) != changed.revision:
                    raise RuntimeError("Aktivitätsrevision ist inkonsistent.")
                await connection.execute(
                    """
                    INSERT INTO acquisition_activity (
                        id,
                        action_id,
                        assignment_id,
                        actor_user_id,
                        twenty_company_id,
                        twenty_person_id,
                        occurred_at,
                        channel,
                        outcome,
                        note,
                        next_action_snapshot,
                        due_at_snapshot,
                        assignment_revision,
                        created_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $7
                    )
                    """,
                    activity_id,
                    previous.action_id,
                    previous.id,
                    actor_user_id,
                    company_id,
                    person_id,
                    occurred_at,
                    capture.channel.value,
                    capture.outcome.value,
                    capture.note,
                    capture.next_action,
                    capture.due_at,
                    changed.revision,
                )
                await self._append_history(
                    connection,
                    assignment=changed,
                    actor_user_id=actor_user_id,
                    previous_state=previous.state.snapshot(
                        acquirer_user_id=previous.acquirer_user_id,
                    ),
                    occurred_at=occurred_at,
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
                    VALUES (
                        $1, $2, $3, 'acquisition_activity_recorded',
                        'acquisition_activity', $4, $5, $6::jsonb, $7
                    )
                    """,
                    uuid4(),
                    previous.action_id,
                    actor_user_id,
                    activity_id,
                    request_id,
                    json.dumps(
                        {
                            "assignmentId": str(previous.id),
                            "assignmentRevision": changed.revision,
                            "channel": capture.channel.value,
                            "outcome": capture.outcome.value,
                            "hasReminder": capture.due_at is not None,
                            "noteLength": len(capture.note or ""),
                        },
                        separators=(",", ":"),
                    ),
                    occurred_at,
                )
                persisted_row = await self._assignment_record(
                    connection,
                    action_id=previous.action_id,
                    assignment_id=previous.id,
                )
        if persisted_row is None:
            raise RuntimeError("Aktualisierte Akquise-Zuordnung fehlt.")
        persisted = self._assignment(persisted_row)
        return ActivityRecordingResult(
            assignment=persisted,
            activity=RecordedAcquisitionActivity(
                id=activity_id,
                action_id=previous.action_id,
                assignment_id=previous.id,
                party_kind=previous.party_kind,
                party_id=previous.party_id,
                actor_user_id=actor_user_id,
                actor_display_name=previous.acquirer_display_name,
                channel=capture.channel,
                outcome=capture.outcome,
                note=capture.note,
                next_action=capture.next_action,
                due_at=capture.due_at,
                assignment_revision=persisted.revision,
                occurred_at=occurred_at,
            ),
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
    async def _assignment_record(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        assignment_id: UUID,
    ) -> asyncpg.Record | None:
        return await connection.fetchrow(
            """
            SELECT
                assignment.id,
                assignment.action_id,
                assignment.twenty_company_id,
                assignment.twenty_person_id,
                assignment.acquirer_user_id,
                account.display_name AS acquirer_display_name,
                assignment.status,
                assignment.priority,
                assignment.next_action,
                assignment.due_at,
                assignment.revision,
                assignment.created_at,
                assignment.updated_at
            FROM acquisition_assignment AS assignment
            JOIN user_account AS account
              ON account.id = assignment.acquirer_user_id
            WHERE assignment.action_id = $1
              AND assignment.id = $2
            """,
            action_id,
            assignment_id,
        )

    @staticmethod
    def _assignment(row: asyncpg.Record) -> AcquisitionAssignment:
        company_id = row["twenty_company_id"]
        person_id = row["twenty_person_id"]
        if company_id is not None:
            party_kind = AssignmentPartyKind.COMPANY
            party_id = company_id
        elif person_id is not None:
            party_kind = AssignmentPartyKind.PERSON
            party_id = person_id
        else:
            raise RuntimeError("Eine Akquise-Zuordnung besitzt keinen Partnerbezug.")
        return AcquisitionAssignment(
            id=row["id"],
            action_id=row["action_id"],
            party_kind=party_kind,
            party_id=party_id,
            acquirer_user_id=row["acquirer_user_id"],
            acquirer_display_name=str(row["acquirer_display_name"]),
            state=AssignmentState(
                status=AssignmentStatus(str(row["status"])),
                priority=int(row["priority"]),
                next_action=row["next_action"],
                due_at=row["due_at"],
            ),
            revision=int(row["revision"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _history(row: asyncpg.Record) -> AssignmentHistoryEntry:
        return AssignmentHistoryEntry(
            id=row["id"],
            assignment_id=row["assignment_id"],
            changed_by_user_id=row["changed_by_user_id"],
            changed_by_display_name=str(row["changed_by_display_name"]),
            previous_state=AsyncpgAcquisitionPolicyRepository._json_object(
                row["previous_state"]
            ),
            new_state=AsyncpgAcquisitionPolicyRepository._json_object(row["new_state"]),
            changed_at=row["changed_at"],
        )

    @staticmethod
    def _json_object(value: object) -> dict[str, object]:
        decoded = json.loads(value) if isinstance(value, str) else value
        if not isinstance(decoded, dict):
            raise RuntimeError("Assignment-Historie enthält kein JSON-Objekt.")
        return {str(key): item for key, item in decoded.items()}

    @staticmethod
    async def _append_history(
        connection: asyncpg.Connection[Any],
        *,
        assignment: AcquisitionAssignment,
        actor_user_id: UUID,
        previous_state: dict[str, object],
        occurred_at: datetime,
    ) -> None:
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
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6)
            """,
            uuid4(),
            assignment.id,
            actor_user_id,
            json.dumps(previous_state, separators=(",", ":")),
            json.dumps(
                assignment.state.snapshot(acquirer_user_id=assignment.acquirer_user_id),
                separators=(",", ":"),
            ),
            occurred_at,
        )

    @staticmethod
    async def _append_assignment_audit(
        connection: asyncpg.Connection[Any],
        *,
        assignment: AcquisitionAssignment,
        actor_user_id: UUID,
        event_type: str,
        request_id: str,
        payload: dict[str, object],
        occurred_at: datetime,
    ) -> None:
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
            VALUES ($1, $2, $3, $4, 'acquisition_assignment', $5, $6, $7::jsonb, $8)
            """,
            uuid4(),
            assignment.action_id,
            actor_user_id,
            event_type,
            assignment.id,
            request_id,
            json.dumps(payload, separators=(",", ":")),
            occurred_at,
        )

    @staticmethod
    async def _raise_revision_if_changed(
        connection: asyncpg.Connection[Any],
        assignment_id: UUID,
        expected_revision: int,
    ) -> None:
        current_revision = await connection.fetchval(
            """
            SELECT revision
            FROM acquisition_assignment
            WHERE id = $1
            """,
            assignment_id,
        )
        if current_revision is not None and int(current_revision) != expected_revision:
            raise Conflict(
                "assignment_revision_conflict",
                "Die Zuordnung wurde zwischenzeitlich geändert. Bitte lade sie neu.",
            )

    @staticmethod
    def _assignment_conflict_target(
        party_kind: AssignmentPartyKind,
    ) -> str:
        if party_kind is AssignmentPartyKind.COMPANY:
            return (
                "(action_id, twenty_company_id, acquirer_user_id) "
                "WHERE twenty_company_id IS NOT NULL"
            )
        return (
            "(action_id, twenty_person_id, acquirer_user_id) "
            "WHERE twenty_person_id IS NOT NULL"
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
    def _recorded_activity(
        row: asyncpg.Record,
    ) -> RecordedAcquisitionActivity:
        company_id = row["twenty_company_id"]
        person_id = row["twenty_person_id"]
        if company_id is not None:
            party_kind = AssignmentPartyKind.COMPANY
            party_id = company_id
        elif person_id is not None:
            party_kind = AssignmentPartyKind.PERSON
            party_id = person_id
        else:
            raise RuntimeError("Eine Akquiseaktivität besitzt keinen Partnerbezug.")
        assignment_id = row["assignment_id"]
        actor_user_id = row["actor_user_id"]
        assignment_revision = row["assignment_revision"]
        if (
            assignment_id is None
            or actor_user_id is None
            or assignment_revision is None
        ):
            raise RuntimeError("Eine manuelle Aktivität besitzt keinen Verlauf.")
        return RecordedAcquisitionActivity(
            id=row["id"],
            action_id=row["action_id"],
            assignment_id=assignment_id,
            party_kind=party_kind,
            party_id=party_id,
            actor_user_id=actor_user_id,
            actor_display_name=str(row["actor_display_name"]),
            channel=ActivityChannel(str(row["channel"])),
            outcome=ActivityOutcome(str(row["outcome"])),
            note=row["note"],
            next_action=row["next_action_snapshot"],
            due_at=row["due_at_snapshot"],
            assignment_revision=int(assignment_revision),
            occurred_at=row["occurred_at"],
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
