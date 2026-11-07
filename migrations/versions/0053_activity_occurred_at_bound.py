"""Bound the capture time of manually recorded contacts.

Revision ID: 0053_activity_occurred_at_bound
Revises: 0052_commitment_captured_at

A contact attempt (phone, email, in person) queued by the PWA is stored with
``occurred_at = capturedAt`` and ``created_at`` = Core's receive time
(specs/pwa-offline-queue/PLAN.md §11.2). Core accepts 14 days back and 5
minutes ahead (decision D5); this check repeats the bound in the database,
like ``ck_commitment_captured_at`` for orders, so no write path can store a
far-away contact time. Until now both columns were written from the same
value, so every existing manual row satisfies it. System and public-form
activities are derived history (the golden seed backdates them) and stay
unbounded.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0053_activity_occurred_at_bound"
down_revision: str | None = "0052_commitment_captured_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Added NOT VALID so that new rows are bound at once; existing rows are
    # checked by a guard that names them before VALIDATE, instead of a bare
    # check violation. A manual contact outside the window (only possible
    # through a hand-made database edit) must be reviewed by the operator.
    op.execute(
        """
        ALTER TABLE acquisition_activity
            ADD CONSTRAINT ck_acquisition_activity_occurred_at_bound
            CHECK (
                channel NOT IN ('phone', 'email', 'in_person')
                OR (
                    occurred_at >= created_at - interval '14 days'
                    AND occurred_at <= created_at + interval '5 minutes'
                )
            ) NOT VALID
        """
    )
    op.execute(
        """
        DO $$
        DECLARE
            offending bigint;
            sample text;
        BEGIN
            SELECT count(*),
                   string_agg(id::text, ', ' ORDER BY id) FILTER (
                       WHERE rn <= 10
                   )
            INTO offending, sample
            FROM (
                SELECT id, row_number() OVER (ORDER BY id) AS rn
                FROM acquisition_activity
                WHERE channel IN ('phone', 'email', 'in_person')
                  AND (
                    occurred_at < created_at - interval '14 days'
                    OR occurred_at > created_at + interval '5 minutes'
                  )
            ) AS outside;
            IF offending > 0 THEN
                RAISE EXCEPTION
                    '0053 refused: % manual contact(s) have occurred_at more '
                    'than 14 days before or 5 minutes after created_at '
                    '(first ids: %); correct or remove them, then upgrade again',
                    offending, sample;
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        "ALTER TABLE acquisition_activity "
        "VALIDATE CONSTRAINT ck_acquisition_activity_occurred_at_bound"
    )


def downgrade() -> None:
    # Only a check: the older schema stores the same rows without it.
    op.execute(
        "ALTER TABLE acquisition_activity "
        "DROP CONSTRAINT ck_acquisition_activity_occurred_at_bound"
    )
