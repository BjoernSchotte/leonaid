"""Reserve campaign and authentication route roots without retargeting aliases.

Revision ID: 0027_campaign_alias_namespaces
Revises: 0026_invoice_payment_snapshot
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027_campaign_alias_namespaces"
down_revision: str | None = "0026_invoice_payment_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATA_MIGRATION_REFERENCE = (
    "Existing aliases and publication windows remain unchanged. Colliding aliases "
    "stop migration with a static error and require explicit operator resolution."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"

# Frozen migration inventory, deliberately not imported from mutable runtime code.
RESERVED = (
    "'_health', '_actions', '_astro', '_campaign-assets', '_emdash', '_image', "
    "'_server-islands', 'admin', 'api', 'app', 'archive', 'campaigns', 'crm', "
    "'email-change', 'fresh-login', 'health', 'invite', 'login', 'mail', 'mailing'"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE public_action_alias IN SHARE ROW EXCLUSIVE MODE")
    # Preflight under the same lock: do not leak the conflicting row through a
    # failed CHECK validation and never rename/delete a user's existing alias.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM public_action_alias "
        f"WHERE alias IN ({RESERVED})) THEN "
        "RAISE EXCEPTION 'campaign alias migration requires namespace conflict resolution'; "
        "END IF; END $$"
    )
    op.create_check_constraint(
        "ck_public_action_alias_campaign_namespaces",
        "public_action_alias",
        f"alias NOT IN ({RESERVED})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_public_action_alias_campaign_namespaces",
        "public_action_alias",
        type_="check",
    )
