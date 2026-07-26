"""Add passwordless login challenges and harden server sessions.

Revision ID: 0004_passwordless_sessions
Revises: 0003_invitation_credentials
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0004_passwordless_sessions"
down_revision: str | None = "0003_invitation_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_check_constraint(
        "ck_user_session_last_seen",
        "user_session",
        "last_seen_at >= created_at",
    )
    op.create_check_constraint(
        "ck_user_session_fresh_login",
        "user_session",
        "fresh_login_at >= created_at AND fresh_login_at <= last_seen_at",
    )
    op.create_check_constraint(
        "ck_user_session_revocation",
        "user_session",
        "revoked_at IS NULL OR revoked_at >= created_at",
    )
    op.create_check_constraint(
        "ck_user_session_device_hint",
        "user_session",
        "device_hint IS NULL OR char_length(device_hint) <= 160",
    )
    op.create_index(
        "ix_user_session_active_user",
        "user_session",
        ["user_id", "expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "login_challenge",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("email_snapshot", sa.Text(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "failed_code_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_failed_code_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("expired_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.CheckConstraint(
            "purpose IN ('login', 'fresh_login')",
            name="ck_login_challenge_purpose",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'consumed', 'expired', 'revoked')",
            name="ck_login_challenge_status",
        ),
        sa.CheckConstraint(
            "email_snapshot = lower(email_snapshot) "
            "AND position('@' IN email_snapshot) > 1",
            name="ck_login_challenge_email",
        ),
        sa.CheckConstraint(
            "token_digest ~ '^[0-9a-f]{64}$' AND code_digest ~ '^[0-9a-f]{64}$'",
            name="ck_login_challenge_digests",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_login_challenge_expiry",
        ),
        sa.CheckConstraint(
            "failed_code_attempts BETWEEN 0 AND 5",
            name="ck_login_challenge_attempts",
        ),
        sa.CheckConstraint(
            "(failed_code_attempts = 0) = (last_failed_code_at IS NULL)",
            name="ck_login_challenge_failed_at",
        ),
        sa.CheckConstraint(
            """
            (
              status = 'pending'
              AND consumed_at IS NULL
              AND expired_at IS NULL
              AND revoked_at IS NULL
            )
            OR (
              status = 'consumed'
              AND consumed_at IS NOT NULL
              AND expired_at IS NULL
              AND revoked_at IS NULL
            )
            OR (
              status = 'expired'
              AND consumed_at IS NULL
              AND expired_at IS NOT NULL
              AND revoked_at IS NULL
            )
            OR (
              status = 'revoked'
              AND consumed_at IS NULL
              AND expired_at IS NULL
              AND revoked_at IS NOT NULL
            )
            """,
            name="ck_login_challenge_lifecycle",
        ),
    )
    op.create_index(
        "uq_login_challenge_token_digest",
        "login_challenge",
        ["token_digest"],
        unique=True,
    )
    op.create_index(
        "uq_login_challenge_code_digest",
        "login_challenge",
        ["code_digest"],
        unique=True,
    )
    op.create_index(
        "ix_login_challenge_email_code",
        "login_challenge",
        ["email_snapshot", "code_digest"],
    )
    op.create_index(
        "uq_login_challenge_pending_user_purpose",
        "login_challenge",
        ["user_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.execute(
        """
        CREATE FUNCTION enforce_login_challenge_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF NEW.user_id <> OLD.user_id
             OR NEW.purpose <> OLD.purpose
             OR NEW.email_snapshot <> OLD.email_snapshot
             OR NEW.token_digest <> OLD.token_digest
             OR NEW.code_digest <> OLD.code_digest
             OR NEW.expires_at <> OLD.expires_at
             OR NEW.created_at <> OLD.created_at THEN
            RAISE EXCEPTION 'login challenge credentials and snapshots are immutable';
          END IF;
          IF OLD.status <> NEW.status
             AND NOT (
               OLD.status = 'pending'
               AND NEW.status IN ('consumed', 'expired', 'revoked')
             ) THEN
            RAISE EXCEPTION 'invalid login challenge transition';
          END IF;
          IF OLD.status <> 'pending' AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'terminal login challenge is immutable';
          END IF;
          RETURN NEW;
        END
        $$;
        CREATE TRIGGER trg_login_challenge_transition
        BEFORE UPDATE ON login_challenge
        FOR EACH ROW EXECUTE FUNCTION enforce_login_challenge_transition();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_login_challenge_transition ON login_challenge;
        DROP FUNCTION IF EXISTS enforce_login_challenge_transition();
        """
    )
    op.drop_table("login_challenge")
    op.drop_index("ix_user_session_active_user", table_name="user_session")
    op.drop_constraint(
        "ck_user_session_device_hint",
        "user_session",
        type_="check",
    )
    op.drop_constraint(
        "ck_user_session_revocation",
        "user_session",
        type_="check",
    )
    op.drop_constraint(
        "ck_user_session_fresh_login",
        "user_session",
        type_="check",
    )
    op.drop_constraint(
        "ck_user_session_last_seen",
        "user_session",
        type_="check",
    )
