"""Unique member buyer links with revision checks and explicit audit provenance."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.member_buyers import MemberBuyerLink, MemberBuyerRepository


def _link(user_id: UUID, row: asyncpg.Record | None) -> MemberBuyerLink:
    if row is None or row["revision"] is None:
        return MemberBuyerLink(user_id)
    return MemberBuyerLink(
        user_id=user_id,
        twenty_person_id=row["twenty_person_id"],
        revision=row["revision"],
        verified_by_user_id=row["verified_by_user_id"],
        verified_at=row["verified_at"],
    )


class AsyncpgMemberBuyerRepository(MemberBuyerRepository):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def get(self, user_id: UUID) -> MemberBuyerLink:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """SELECT link.* FROM user_account AS account
                LEFT JOIN member_buyer_link AS link ON link.user_id = account.id
                WHERE account.id = $1""",
                user_id,
            )
            if row is None:
                raise ResourceNotFound(
                    "member_not_found", "Das Mitglied wurde nicht gefunden."
                )
            return _link(user_id, row)

    async def is_assigned(
        self, user_id: UUID, person_id: UUID, action_id: UUID
    ) -> bool:
        async with self._pool.acquire() as connection:
            return bool(
                await connection.fetchval(
                    """SELECT EXISTS (SELECT 1 FROM acquisition_assignment
                WHERE acquirer_user_id = $1 AND twenty_person_id = $2 AND action_id = $3)""",
                    user_id,
                    person_id,
                    action_id,
                )
            )

    async def save(
        self,
        user_id: UUID,
        person_id: UUID | None,
        *,
        expected_revision: int,
        actor_user_id: UUID,
        occurred_at: datetime,
        request_id: str,
    ) -> MemberBuyerLink:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    # Lock a stable row even before the first link is created.
                    status = await connection.fetchval(
                        "SELECT status FROM user_account WHERE id = $1 FOR UPDATE",
                        user_id,
                    )
                    if status is None:
                        raise ResourceNotFound(
                            "member_not_found", "Das Mitglied wurde nicht gefunden."
                        )
                    current = _link(
                        user_id,
                        await connection.fetchrow(
                            "SELECT * FROM member_buyer_link WHERE user_id = $1",
                            user_id,
                        ),
                    )
                    if current.revision != expected_revision:
                        raise Conflict(
                            "member_buyer_revision_conflict",
                            "Die Eigenzuordnung wurde inzwischen geändert. Bitte lade sie neu.",
                        )
                    if person_id is not None:
                        if status != "active":
                            raise Conflict(
                                "member_buyer_inactive", "Das Mitglied ist nicht aktiv."
                            )
                        assigned = await connection.fetchval(
                            """SELECT assignment.id FROM acquisition_assignment AS assignment
                            JOIN action_membership AS membership
                              ON membership.user_id = assignment.acquirer_user_id
                              AND membership.action_id = assignment.action_id
                              AND membership.role = 'acquirer'
                              AND membership.active_from <= $3
                              AND (membership.active_until IS NULL OR membership.active_until > $3)
                            WHERE assignment.acquirer_user_id = $1 AND assignment.twenty_person_id = $2
                            LIMIT 1 FOR SHARE OF assignment, membership""",
                            user_id,
                            person_id,
                            occurred_at,
                        )
                        if assigned is None:
                            raise Conflict(
                                "member_buyer_assignment_required",
                                "Ordne diese CRM-Person dem Mitglied zuerst in der Akquise zu.",
                            )
                    if current.twenty_person_id == person_id:
                        return current
                    row = await connection.fetchrow(
                        """INSERT INTO member_buyer_link
                        (user_id, twenty_person_id, revision, verified_by_user_id, verified_at)
                        VALUES ($1,$2,$3,$4,$5)
                        ON CONFLICT (user_id) DO UPDATE SET
                            twenty_person_id = EXCLUDED.twenty_person_id,
                            revision = EXCLUDED.revision,
                            verified_by_user_id = EXCLUDED.verified_by_user_id,
                            verified_at = EXCLUDED.verified_at
                        RETURNING *""",
                        user_id,
                        person_id,
                        current.revision + 1,
                        actor_user_id if person_id else None,
                        occurred_at if person_id else None,
                    )
                    await connection.execute(
                        """INSERT INTO audit_event
                        (id, actor_user_id, event_type, entity_type, entity_id, request_id, payload, occurred_at)
                        VALUES ($1,$2,'member_buyer_link_changed','user_account',$3,$4,$5::jsonb,$6)""",
                        uuid4(),
                        actor_user_id,
                        user_id,
                        request_id,
                        json.dumps(
                            {
                                "linked": person_id is not None,
                                "revision": current.revision + 1,
                            }
                        ),
                        occurred_at,
                    )
                    return _link(user_id, row)
        except asyncpg.UniqueViolationError:
            raise Conflict(
                "member_buyer_person_already_linked",
                "Diese CRM-Person ist bereits als eigene Person eines Mitglieds bestätigt.",
            ) from None
