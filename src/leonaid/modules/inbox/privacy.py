"""Inbox cases in the privacy subject report and the erasure workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import asyncpg

from leonaid.domain.privacy import PrivacyReference


class InboxPrivacyContributor:
    """Finds cases by the submitted e-mail and anonymizes their snapshot.

    The erasure keeps the case and its handling history for the team, but
    removes the submitter's name, contact details and message. The case also
    leaves the CRM link pending review; the Twenty person itself is part of the
    existing manual CRM deletion step.
    """

    async def references(
        self, connection: object, normalized_email: str
    ) -> tuple[PrivacyReference, ...]:
        rows = await cast(asyncpg.Connection[Any], connection).fetch(
            """
            SELECT id, action_id, status, subject
            FROM inbox_case
            WHERE lower(email) = $1 AND erased_at IS NULL
            ORDER BY received_at, id
            """,
            normalized_email,
        )
        return tuple(
            PrivacyReference(
                id=row["id"],
                reference_type="inbox_case",
                action_id=row["action_id"],
                status=str(row["status"]),
                label=str(row["subject"]),
            )
            for row in rows
        )

    async def anonymize(
        self, connection: object, normalized_email: str, occurred_at: datetime
    ) -> int:
        status = await cast(asyncpg.Connection[Any], connection).execute(
            """
            UPDATE inbox_case
            SET given_name = 'Anonymisiert',
                family_name = 'Anonymisiert',
                email = NULL,
                phone = NULL,
                subject = 'Anonymisierte Anfrage',
                message = 'Inhalt im Datenschutz-Löschworkflow entfernt.',
                erased_at = $2,
                updated_at = $2,
                revision = revision + 1
            WHERE lower(email) = $1 AND erased_at IS NULL
            """,
            normalized_email,
            occurred_at,
        )
        return int(status.rsplit(" ", 1)[-1])
