"""Campaign hosts and their editions.

Revision ID: 0055_site_hosts
Revises: 0054_preferred_surface

specs/multi-domain §7.3: ``site_host`` holds what belongs to a hostname
(verification, certificate approval, redirect host); ``site_binding`` maps
(host, edition segment) to an action, with history rows for old paths. Both
start empty; aliases and ``/campaigns/<slug>/`` keep working unchanged.

Downgrade refuses existing rows: a host or binding carries public URLs and
audit history that must not disappear silently. Remove the hosts in the
admin UI first, then delete the rows explicitly.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055_site_hosts"
down_revision: str | None = "0054_preferred_surface"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATA_MIGRATION_REFERENCE = (
    "New empty tables; no existing data changes. Downgrade refuses while any "
    "site host or binding exists instead of discarding public URLs."
)
BACKUP_REFERENCE = "infra/backup/README.md#schema-changing-migrations"

HOSTNAME_PATTERN = r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$"
SEGMENT_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "site_host",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Lowercase IDNA A-label, no port, no trailing dot, <= 253 chars.
        sa.Column("hostname", sa.Text(), nullable=False),
        # pending -> verified -> active ; any -> disabled ;
        # disabled -> verified (re-check passes, bindings live) | pending (re-add)
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        # Redirect host (www.) -> target host, whole host, path kept.
        sa.Column(
            "redirect_to_host_id",
            sa.UUID(),
            sa.ForeignKey("site_host.id", ondelete="RESTRICT"),
        ),
        sa.Column("verification_token", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_check_result", sa.Text()),
        # Nightly re-check (§7.4): three consecutive failures over 72 h
        # disable the host.
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("failing_since", sa.DateTime(timezone=True)),
        # First on-demand certificate approval; the ask rate limit counts
        # these per hour (§9.1).
        sa.Column("tls_approved_at", sa.DateTime(timezone=True)),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_by",
            sa.UUID(),
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending','verified','active','disabled')",
            name="ck_site_host_status",
        ),
        sa.CheckConstraint(
            "hostname ~ '" + HOSTNAME_PATTERN + "' AND length(hostname) <= 253",
            name="ck_site_host_hostname",
        ),
        sa.CheckConstraint(
            "redirect_to_host_id IS NULL OR redirect_to_host_id <> id",
            name="ck_site_host_redirect_self",
        ),
        sa.CheckConstraint("revision > 0", name="ck_site_host_revision"),
        sa.CheckConstraint(
            "consecutive_failures >= 0", name="ck_site_host_consecutive_failures"
        ),
        sa.CheckConstraint(
            "length(verification_token) BETWEEN 32 AND 128",
            name="ck_site_host_verification_token",
        ),
        # A verified or active host passed a check at some point (§7.4).
        sa.CheckConstraint(
            "status NOT IN ('verified','active') OR verified_at IS NOT NULL",
            name="ck_site_host_verified_at",
        ),
    )
    op.create_index("uq_site_host_hostname", "site_host", ["hostname"], unique=True)
    # The ask endpoint looks a hostname up by status on every new handshake.
    op.create_index(
        "ix_site_host_tls",
        "site_host",
        ["hostname"],
        postgresql_where=sa.text("status IN ('verified','active')"),
    )

    op.create_table(
        "site_binding",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "site_host_id",
            sa.UUID(),
            sa.ForeignKey("site_host.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "action_id",
            sa.UUID(),
            sa.ForeignKey("charity_action.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Path segment of this edition on the host: "2025". Never empty.
        sa.Column("edition_segment", sa.Text(), nullable=False),
        # This edition owns "/" while it is the host's current edition.
        sa.Column("at_root", sa.Boolean(), nullable=False, server_default=sa.false()),
        # Canonical binding of the action when it is live on several hosts.
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # NULL = live. Set = history row; its path 308s to the canonical URL.
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("ended_reason", sa.Text()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_by",
            sa.UUID(),
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "edition_segment ~ '"
            + SEGMENT_PATTERN
            + "' AND length(edition_segment) <= 63",
            name="ck_site_binding_segment",
        ),
        sa.CheckConstraint(
            "(valid_to IS NULL) = (ended_reason IS NULL)",
            name="ck_site_binding_history",
        ),
        sa.CheckConstraint(
            "ended_reason IS NULL OR ended_reason IN "
            "('segment_changed','unbound','host_removed')",
            name="ck_site_binding_ended_reason",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR NOT at_root", name="ck_site_binding_history_not_root"
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR NOT is_primary",
            name="ck_site_binding_history_not_primary",
        ),
        sa.CheckConstraint("revision > 0", name="ck_site_binding_revision"),
    )
    live = sa.text("valid_to IS NULL")
    # One current edition per host.
    op.create_index(
        "uq_site_binding_root",
        "site_binding",
        ["site_host_id"],
        unique=True,
        postgresql_where=sa.text("at_root AND valid_to IS NULL"),
    )
    # A segment names one live edition per host.
    op.create_index(
        "uq_site_binding_segment",
        "site_binding",
        ["site_host_id", "edition_segment"],
        unique=True,
        postgresql_where=live,
    )
    # An action appears at most once per host.
    op.create_index(
        "uq_site_binding_host_action",
        "site_binding",
        ["site_host_id", "action_id"],
        unique=True,
        postgresql_where=live,
    )
    # One canonical binding per action.
    op.create_index(
        "uq_site_binding_primary",
        "site_binding",
        ["action_id"],
        unique=True,
        postgresql_where=sa.text("is_primary AND valid_to IS NULL"),
    )
    # History lookup for old paths.
    op.create_index(
        "ix_site_binding_history",
        "site_binding",
        ["site_host_id", "edition_segment", "valid_to"],
        postgresql_where=sa.text("valid_to IS NOT NULL"),
    )
    op.create_index(
        "ix_site_binding_action_live",
        "site_binding",
        ["action_id"],
        postgresql_where=live,
    )
    # Redirect hosts (§7.3): no live editions, and the target is a campaign
    # host, never another redirect host. Checked at commit, so a command may
    # reorder rows inside its transaction.
    op.execute(
        """
        CREATE FUNCTION site_host_redirect_rules() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM site_host AS h
            WHERE h.redirect_to_host_id IS NOT NULL AND (
              EXISTS (SELECT 1 FROM site_binding AS b
                      WHERE b.site_host_id = h.id AND b.valid_to IS NULL)
              OR EXISTS (SELECT 1 FROM site_host AS t
                         WHERE t.id = h.redirect_to_host_id
                           AND t.redirect_to_host_id IS NOT NULL)
            )
          ) THEN
            RAISE EXCEPTION 'site_host redirect rules violated'
              USING ERRCODE = 'check_violation',
                    CONSTRAINT = 'ck_site_host_redirect_rules';
          END IF;
          RETURN NULL;
        END $$
        """
    )
    # Only the columns the rules read; check bookkeeping stays untouched.
    for table, columns in (
        ("site_host", "redirect_to_host_id"),
        ("site_binding", "site_host_id, valid_to"),
    ):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER tg_{table}_redirect_rules "
            f"AFTER INSERT OR UPDATE OF {columns} ON {table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
            "EXECUTE FUNCTION site_host_redirect_rules()"
        )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE site_binding, site_host IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM site_host) "
        "OR EXISTS (SELECT 1 FROM site_binding) THEN "
        "RAISE EXCEPTION '0055 downgrade refused: site hosts or bindings exist; "
        "remove them explicitly first'; "
        "END IF; END $$"
    )
    op.drop_table("site_binding")
    op.drop_table("site_host")
    op.execute("DROP FUNCTION site_host_redirect_rules()")
