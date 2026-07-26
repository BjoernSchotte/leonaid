"""Harden invitation snapshots and one-time credentials.

Revision ID: 0003_invitation_credentials
Revises: 0002_durable_outbox
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0003_invitation_credentials"
down_revision: str | None = "0002_durable_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("action_invitation", sa.Column("display_name_snapshot", sa.Text()))
    op.add_column("action_invitation", sa.Column("action_name_snapshot", sa.Text()))
    op.add_column(
        "action_invitation",
        sa.Column("invited_by_name_snapshot", sa.Text()),
    )
    op.add_column(
        "action_invitation",
        sa.Column("code_digest", sa.String(length=64)),
    )
    op.add_column(
        "action_invitation",
        sa.Column(
            "accepted_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
        ),
    )
    op.add_column("action_invitation", sa.Column("accepted_via", sa.Text()))
    op.add_column(
        "action_invitation",
        sa.Column("expired_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "action_invitation",
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "action_invitation",
        sa.Column(
            "failed_code_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "action_invitation",
        sa.Column("last_failed_code_at", sa.DateTime(timezone=True)),
    )

    op.execute(
        """
        UPDATE action_invitation AS invitation
        SET display_name_snapshot = invitation.email_snapshot,
            action_name_snapshot = action.name,
            invited_by_name_snapshot = account.display_name,
            code_digest = invitation.token_digest,
            accepted_at = CASE
              WHEN invitation.status = 'accepted'
                THEN COALESCE(invitation.accepted_at, invitation.updated_at)
              ELSE NULL
            END,
            accepted_user_id = CASE
              WHEN invitation.status = 'accepted'
                THEN (
                  SELECT accepted_account.id
                  FROM user_account AS accepted_account
                  WHERE accepted_account.email = invitation.email_snapshot
                )
              ELSE NULL
            END,
            accepted_via = CASE
              WHEN invitation.status = 'accepted' THEN 'magic_link'
              ELSE NULL
            END,
            expired_at = CASE
              WHEN invitation.status = 'expired' THEN invitation.updated_at
              ELSE NULL
            END,
            revoked_at = CASE
              WHEN invitation.status = 'revoked' THEN invitation.updated_at
              ELSE NULL
            END
        FROM charity_action AS action, user_account AS account
        WHERE action.id = invitation.action_id
          AND account.id = invitation.invited_by_user_id
        """
    )
    for column in (
        "display_name_snapshot",
        "action_name_snapshot",
        "invited_by_name_snapshot",
        "code_digest",
    ):
        op.alter_column("action_invitation", column, nullable=False)

    op.create_unique_constraint(
        "uq_action_invitation_code_digest",
        "action_invitation",
        ["code_digest"],
    )
    op.execute(
        """
        WITH ranked AS (
          SELECT
            id,
            row_number() OVER (
              PARTITION BY action_id, email_snapshot, role_snapshot
              ORDER BY created_at DESC, id DESC
            ) AS position
          FROM action_invitation
          WHERE status = 'pending'
        )
        UPDATE action_invitation AS invitation
        SET status = 'revoked',
            revoked_at = invitation.updated_at
        FROM ranked
        WHERE ranked.id = invitation.id
          AND ranked.position > 1
        """
    )
    op.create_index(
        "ix_action_invitation_code_lookup",
        "action_invitation",
        ["email_snapshot", "code_digest"],
    )
    op.create_index(
        "uq_action_invitation_pending_target",
        "action_invitation",
        ["action_id", "email_snapshot", "role_snapshot"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_check_constraint(
        "ck_action_invitation_code_digest",
        "action_invitation",
        "code_digest ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_action_invitation_acceptance_method",
        "action_invitation",
        "accepted_via IS NULL OR accepted_via IN ('magic_link', 'code')",
    )
    op.create_check_constraint(
        "ck_action_invitation_code_attempts",
        "action_invitation",
        """
        failed_code_attempts BETWEEN 0 AND 5
        AND (
          (failed_code_attempts = 0 AND last_failed_code_at IS NULL)
          OR (failed_code_attempts > 0 AND last_failed_code_at IS NOT NULL)
        )
        """,
    )
    op.create_check_constraint(
        "ck_action_invitation_lifecycle_timestamps",
        "action_invitation",
        """
        (
          status = 'pending'
          AND accepted_at IS NULL
          AND accepted_user_id IS NULL
          AND accepted_via IS NULL
          AND expired_at IS NULL
          AND revoked_at IS NULL
        )
        OR (
          status = 'accepted'
          AND accepted_at IS NOT NULL
          AND accepted_user_id IS NOT NULL
          AND accepted_via IS NOT NULL
          AND expired_at IS NULL
          AND revoked_at IS NULL
        )
        OR (
          status = 'expired'
          AND accepted_at IS NULL
          AND accepted_user_id IS NULL
          AND accepted_via IS NULL
          AND expired_at IS NOT NULL
          AND revoked_at IS NULL
        )
        OR (
          status = 'revoked'
          AND accepted_at IS NULL
          AND accepted_user_id IS NULL
          AND accepted_via IS NULL
          AND expired_at IS NULL
          AND revoked_at IS NOT NULL
        )
        """,
    )

    op.execute(
        """
        CREATE FUNCTION enforce_action_invitation_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF ROW(
            NEW.action_id,
            NEW.invited_by_user_id,
            NEW.email_snapshot,
            NEW.display_name_snapshot,
            NEW.action_name_snapshot,
            NEW.invited_by_name_snapshot,
            NEW.role_snapshot,
            NEW.token_digest,
            NEW.code_digest,
            NEW.expires_at
          ) IS DISTINCT FROM ROW(
            OLD.action_id,
            OLD.invited_by_user_id,
            OLD.email_snapshot,
            OLD.display_name_snapshot,
            OLD.action_name_snapshot,
            OLD.invited_by_name_snapshot,
            OLD.role_snapshot,
            OLD.token_digest,
            OLD.code_digest,
            OLD.expires_at
          ) THEN
            RAISE EXCEPTION 'action_invitation snapshot is immutable'
              USING ERRCODE = '23514';
          END IF;
          IF NEW.status = OLD.status THEN
            RETURN NEW;
          END IF;
          IF OLD.status = 'pending'
             AND NEW.status IN ('accepted', 'expired', 'revoked') THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'invalid action_invitation status transition: % -> %',
            OLD.status, NEW.status
            USING ERRCODE = '23514';
        END;
        $$;
        CREATE TRIGGER trg_action_invitation_transition
        BEFORE UPDATE ON action_invitation
        FOR EACH ROW
        EXECUTE FUNCTION enforce_action_invitation_transition();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_action_invitation_transition
          ON action_invitation;
        DROP FUNCTION IF EXISTS enforce_action_invitation_transition();
        """
    )
    op.drop_constraint(
        "ck_action_invitation_lifecycle_timestamps",
        "action_invitation",
        type_="check",
    )
    op.drop_constraint(
        "ck_action_invitation_code_attempts",
        "action_invitation",
        type_="check",
    )
    op.drop_constraint(
        "ck_action_invitation_acceptance_method",
        "action_invitation",
        type_="check",
    )
    op.drop_constraint(
        "ck_action_invitation_code_digest",
        "action_invitation",
        type_="check",
    )
    op.drop_index(
        "uq_action_invitation_pending_target",
        table_name="action_invitation",
    )
    op.drop_index(
        "ix_action_invitation_code_lookup",
        table_name="action_invitation",
    )
    op.drop_constraint(
        "uq_action_invitation_code_digest",
        "action_invitation",
        type_="unique",
    )
    op.drop_column("action_invitation", "revoked_at")
    op.drop_column("action_invitation", "expired_at")
    op.drop_column("action_invitation", "last_failed_code_at")
    op.drop_column("action_invitation", "failed_code_attempts")
    op.drop_column("action_invitation", "accepted_via")
    op.drop_column("action_invitation", "accepted_user_id")
    op.drop_column("action_invitation", "code_digest")
    op.drop_column("action_invitation", "invited_by_name_snapshot")
    op.drop_column("action_invitation", "action_name_snapshot")
    op.drop_column("action_invitation", "display_name_snapshot")
