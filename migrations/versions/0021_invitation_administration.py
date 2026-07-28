"""Link immutable invitation replacements.

Revision ID: 0021_invitation_administration
Revises: 0020_account_status_admin
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0021_invitation_administration"
down_revision: str | None = "0020_account_status_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "action_invitation",
        sa.Column(
            "supersedes_invitation_id",
            UUID,
            sa.ForeignKey("action_invitation.id", ondelete="RESTRICT"),
        ),
    )
    op.create_unique_constraint(
        "uq_action_invitation_supersedes",
        "action_invitation",
        ["supersedes_invitation_id"],
    )
    op.create_check_constraint(
        "ck_action_invitation_not_self_superseding",
        "action_invitation",
        "supersedes_invitation_id IS NULL OR supersedes_invitation_id <> id",
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_action_invitation_transition()
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
            NEW.expires_at,
            NEW.supersedes_invitation_id
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
            OLD.expires_at,
            OLD.supersedes_invitation_id
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
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_action_invitation_transition()
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
        """
    )
    op.drop_constraint(
        "ck_action_invitation_not_self_superseding",
        "action_invitation",
        type_="check",
    )
    op.drop_constraint(
        "uq_action_invitation_supersedes",
        "action_invitation",
        type_="unique",
    )
    op.drop_column("action_invitation", "supersedes_invitation_id")
