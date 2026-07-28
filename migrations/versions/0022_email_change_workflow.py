"""Add recipient-confirmed login-email changes.

Revision ID: 0022_email_change_workflow
Revises: 0021_invitation_administration
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0022_email_change_workflow"
down_revision: str | None = "0021_invitation_administration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_change_request",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("old_email_snapshot", sa.Text(), nullable=False),
        sa.Column("new_email_snapshot", sa.Text(), nullable=False),
        sa.Column("display_name_snapshot", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "failed_code_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_failed_code_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("expired_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'expired', 'revoked')",
            name="ck_email_change_status",
        ),
        sa.CheckConstraint(
            "old_email_snapshot = lower(old_email_snapshot) "
            "AND new_email_snapshot = lower(new_email_snapshot) "
            "AND old_email_snapshot <> new_email_snapshot",
            name="ck_email_change_addresses",
        ),
        sa.CheckConstraint(
            "token_digest ~ '^[0-9a-f]{64}$' AND code_digest ~ '^[0-9a-f]{64}$'",
            name="ck_email_change_digests",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_email_change_expiry",
        ),
        sa.CheckConstraint(
            "failed_code_attempts BETWEEN 0 AND 5 "
            "AND (failed_code_attempts = 0) = (last_failed_code_at IS NULL)",
            name="ck_email_change_attempts",
        ),
        sa.CheckConstraint(
            """
            (status = 'pending' AND confirmed_at IS NULL
              AND expired_at IS NULL AND revoked_at IS NULL)
            OR (status = 'confirmed' AND confirmed_at IS NOT NULL
              AND expired_at IS NULL AND revoked_at IS NULL)
            OR (status = 'expired' AND confirmed_at IS NULL
              AND expired_at IS NOT NULL AND revoked_at IS NULL)
            OR (status = 'revoked' AND confirmed_at IS NULL
              AND expired_at IS NULL AND revoked_at IS NOT NULL)
            """,
            name="ck_email_change_lifecycle",
        ),
    )
    op.create_index(
        "uq_email_change_token_digest",
        "email_change_request",
        ["token_digest"],
        unique=True,
    )
    op.create_index(
        "uq_email_change_code_digest",
        "email_change_request",
        ["code_digest"],
        unique=True,
    )
    op.create_index(
        "ix_email_change_code_lookup",
        "email_change_request",
        ["new_email_snapshot", "code_digest"],
    )
    op.create_index(
        "uq_email_change_pending_user",
        "email_change_request",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_email_change_pending_address",
        "email_change_request",
        ["new_email_snapshot"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_email_change_immutability()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF ROW(
            NEW.user_id, NEW.requested_by_user_id,
            NEW.old_email_snapshot, NEW.new_email_snapshot,
            NEW.display_name_snapshot, NEW.token_digest,
            NEW.code_digest, NEW.expires_at
          ) IS DISTINCT FROM ROW(
            OLD.user_id, OLD.requested_by_user_id,
            OLD.old_email_snapshot, OLD.new_email_snapshot,
            OLD.display_name_snapshot, OLD.token_digest,
            OLD.code_digest, OLD.expires_at
          ) THEN
            RAISE EXCEPTION 'email_change_request snapshot is immutable'
              USING ERRCODE = '23514';
          END IF;
          IF NEW.status = OLD.status THEN
            RETURN NEW;
          END IF;
          IF OLD.status = 'pending'
             AND NEW.status IN ('confirmed', 'expired', 'revoked') THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'invalid email_change_request status transition'
            USING ERRCODE = '23514';
        END;
        $$;
        CREATE TRIGGER trg_email_change_immutability
        BEFORE UPDATE ON email_change_request
        FOR EACH ROW
        EXECUTE FUNCTION enforce_email_change_immutability();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_email_change_immutability
          ON email_change_request;
        DROP FUNCTION IF EXISTS enforce_email_change_immutability();
        """
    )
    op.drop_table("email_change_request")
