"""PostgreSQL queries for the role-filtered core search.

Each type is one parameterised query limited to the readable actions and to
``criteria.limit`` rows. The patterns arrive LIKE-escaped with ``\\``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from leonaid.application.search import (
    ActionScope,
    SearchCriteria,
    SearchHit,
    SearchRepository,
    SearchResultType,
)

# $1 contains pattern, $2 prefix pattern, $3 all actions, $4 action ids, $5 limit.
_ACTIONS = r"""
SELECT * FROM (
    SELECT
        action.id,
        action.id AS action_id,
        action.name AS title,
        lower(action.name) AS sort_key,
        action.name ILIKE $2 ESCAPE '\' AS prefix_match,
        action.status,
        NULL::text AS detail,
        NULL::text AS action_name
    FROM charity_action AS action
    WHERE ($3 OR action.id = ANY($4::uuid[]))
      AND action.name ILIKE $1 ESCAPE '\'
) AS hit
ORDER BY NOT hit.prefix_match, hit.sort_key, hit.id
LIMIT $5
"""

_ORDERS = r"""
SELECT * FROM (
    SELECT
        commitment.id,
        commitment.action_id,
        commitment.customer_snapshot ->> 'displayName' AS title,
        lower(commitment.customer_snapshot ->> 'displayName') AS sort_key,
        (
            commitment.customer_snapshot ->> 'displayName' ILIKE $2 ESCAPE '\'
            OR coalesce(commitment.public_reference, '') ILIKE $2 ESCAPE '\'
        ) AS prefix_match,
        commitment.status,
        commitment.public_reference AS detail,
        action.name AS action_name
    FROM commitment
    JOIN charity_action AS action ON action.id = commitment.action_id
    WHERE ($3 OR commitment.action_id = ANY($4::uuid[]))
      -- The order list only shows orders with lines; so does search.
      AND EXISTS (
        SELECT 1 FROM commitment_line AS line
        WHERE line.commitment_id = commitment.id
      )
      AND (
        commitment.customer_snapshot ->> 'displayName' ILIKE $1 ESCAPE '\'
        OR commitment.public_reference ILIKE $1 ESCAPE '\'
      )
) AS hit
ORDER BY NOT hit.prefix_match, hit.sort_key, hit.id
LIMIT $5
"""

_INVOICES = r"""
SELECT * FROM (
    SELECT
        invoice.id,
        invoice.action_id,
        invoice.number AS title,
        lower(invoice.number) AS sort_key,
        (
            invoice.number ILIKE $2 ESCAPE '\'
            OR invoice.recipient_snapshot ->> 'recipientName' ILIKE $2 ESCAPE '\'
        ) AS prefix_match,
        invoice.status,
        invoice.recipient_snapshot ->> 'recipientName' AS detail,
        action.name AS action_name
    FROM invoice
    JOIN charity_action AS action ON action.id = invoice.action_id
    WHERE ($3 OR invoice.action_id = ANY($4::uuid[]))
      -- The invoice list refuses actions without invoicing; so does search.
      AND EXISTS (
        SELECT 1
        FROM charity_action_capability AS capability
        WHERE capability.action_id = invoice.action_id
          AND capability.capability = 'invoicing'
      )
      AND (
        invoice.number ILIKE $1 ESCAPE '\'
        OR invoice.recipient_snapshot ->> 'recipientName' ILIKE $1 ESCAPE '\'
      )
) AS hit
ORDER BY NOT hit.prefix_match, hit.sort_key, hit.id
LIMIT $5
"""

# Same visibility as the member directory: every account for system admins,
# otherwise accounts with a current membership in one of the actions.
# $6 is the evaluation time.
_MEMBERS = r"""
SELECT * FROM (
    SELECT
        account.id,
        NULL::uuid AS action_id,
        account.display_name AS title,
        lower(account.display_name) AS sort_key,
        (
            account.display_name ILIKE $2 ESCAPE '\'
            OR account.email ILIKE $2 ESCAPE '\'
        ) AS prefix_match,
        account.status,
        account.email AS detail,
        NULL::text AS action_name
    FROM user_account AS account
    WHERE (
        $3
        OR EXISTS (
            SELECT 1
            FROM action_membership AS membership
            WHERE membership.user_id = account.id
              AND membership.action_id = ANY($4::uuid[])
              AND membership.active_from <= $6
              AND (membership.active_until IS NULL OR membership.active_until > $6)
        )
      )
      AND (
        account.display_name ILIKE $1 ESCAPE '\'
        OR account.email ILIKE $1 ESCAPE '\'
      )
) AS hit
ORDER BY NOT hit.prefix_match, hit.sort_key, hit.id
LIMIT $5
"""

_QUERIES: tuple[tuple[SearchResultType, str], ...] = (
    (SearchResultType.ACTION, _ACTIONS),
    (SearchResultType.ORDER, _ORDERS),
    (SearchResultType.INVOICE, _INVOICES),
    (SearchResultType.MEMBER, _MEMBERS),
)


def _scope_for(criteria: SearchCriteria, kind: SearchResultType) -> ActionScope:
    scope = criteria.scope
    return {
        SearchResultType.ACTION: scope.actions,
        SearchResultType.ORDER: scope.orders,
        SearchResultType.INVOICE: scope.invoices,
        SearchResultType.MEMBER: scope.members,
    }[kind]


def _hit(kind: SearchResultType, position: int, row: asyncpg.Record) -> SearchHit:
    action_id = row["action_id"]
    return SearchHit(
        type=kind,
        id=UUID(str(row["id"])),
        action_id=UUID(str(action_id)) if action_id is not None else None,
        title=str(row["title"]),
        position=position,
        prefix_match=bool(row["prefix_match"]),
        status=str(row["status"]),
        detail=str(row["detail"]) if row["detail"] is not None else None,
        action_name=(
            str(row["action_name"]) if row["action_name"] is not None else None
        ),
    )


class AsyncpgSearchRepository(SearchRepository):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def search(self, criteria: SearchCriteria) -> tuple[SearchHit, ...]:
        hits: list[SearchHit] = []
        async with self._pool.acquire() as connection:
            async with connection.transaction(
                isolation="repeatable_read",
                readonly=True,
            ):
                for kind, query in _QUERIES:
                    scope = _scope_for(criteria, kind)
                    if scope.is_empty:
                        continue
                    arguments: list[object] = [
                        criteria.contains,
                        criteria.prefix,
                        scope.all_actions,
                        sorted(scope.action_ids, key=str),
                        criteria.limit,
                    ]
                    if kind is SearchResultType.MEMBER:
                        arguments.append(criteria.evaluated_at)
                    rows = await connection.fetch(query, *arguments)
                    hits.extend(
                        _hit(kind, position, row) for position, row in enumerate(rows)
                    )
        return tuple(hits)
