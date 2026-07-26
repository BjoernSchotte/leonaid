"""Reserve immutable archive slugs and harden public aliases.

Revision ID: 0009_public_action_routes
Revises: 0008_activity_capture
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_public_action_routes"
down_revision: str | None = "0008_activity_capture"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_check_constraint(
        "ck_charity_action_archive_slug",
        "charity_action",
        "archive_slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'",
    )
    op.create_check_constraint(
        "ck_public_action_alias_not_reserved",
        "public_action_alias",
        "alias NOT IN ("
        "'_health', 'admin', 'api', 'app', 'archive', 'crm', "
        "'fresh-login', 'invite', 'login', 'mail', 'mailing'"
        ")",
    )
    op.create_table(
        "action_archive_slug_reservation",
        sa.Column("archive_slug", sa.Text(), primary_key=True),
        sa.Column("action_id", sa.UUID(), nullable=False, unique=True),
        sa.Column(
            "reserved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.CheckConstraint(
            "archive_slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'",
            name="ck_action_archive_slug_reservation_slug",
        ),
    )
    op.execute(
        """
        INSERT INTO action_archive_slug_reservation (archive_slug, action_id)
        SELECT archive_slug, id
        FROM charity_action
        """
    )
    op.execute(
        """
        CREATE FUNCTION reserve_charity_action_archive_slug()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            INSERT INTO action_archive_slug_reservation (
                archive_slug, action_id, reserved_at
            )
            VALUES (NEW.archive_slug, NEW.id, CURRENT_TIMESTAMP);
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_charity_action_archive_slug_reserve
        AFTER INSERT ON charity_action
        FOR EACH ROW
        EXECUTE FUNCTION reserve_charity_action_archive_slug()
        """
    )
    op.execute(
        """
        CREATE FUNCTION keep_charity_action_archive_slug()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.archive_slug IS DISTINCT FROM NEW.archive_slug THEN
                RAISE EXCEPTION 'charity_action archive_slug is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_charity_action_archive_slug_immutable
        BEFORE UPDATE OF archive_slug ON charity_action
        FOR EACH ROW
        EXECUTE FUNCTION keep_charity_action_archive_slug()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_charity_action_archive_slug_immutable ON charity_action"
    )
    op.execute("DROP FUNCTION keep_charity_action_archive_slug()")
    op.execute("DROP TRIGGER trg_charity_action_archive_slug_reserve ON charity_action")
    op.execute("DROP FUNCTION reserve_charity_action_archive_slug()")
    op.drop_table("action_archive_slug_reservation")
    op.drop_constraint(
        "ck_public_action_alias_not_reserved",
        "public_action_alias",
        type_="check",
    )
    op.drop_constraint(
        "ck_charity_action_archive_slug",
        "charity_action",
        type_="check",
    )
