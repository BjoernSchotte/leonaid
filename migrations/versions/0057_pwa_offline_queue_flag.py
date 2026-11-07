"""Register the feature flag of the PWA offline capture queue.

Revision ID: 0057_pwa_offline_queue_flag
Revises: 0056_site_hosts

specs/pwa-offline-queue §16: every stage ships behind `pwa.offline_queue`,
off by default, so the truthful "nothing is saved offline" copy stays until
the queue is live. The downgrade removes the flag row; the audit events of
its changes stay (they reference the row id, not a foreign key).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0057_pwa_offline_queue_flag"
down_revision: str | None = "0056_site_hosts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
DATA_MIGRATION_REFERENCE = (
    "The known-key check is replaced by a wider one; existing flag rows and "
    "their states are untouched."
)
BACKUP_REFERENCE = "infra/backup/README.md#schema-changing-migrations"

OLD_KEYS = "key IN ('admin.system_status_panel', 'admin.preview_notice')"
NEW_KEYS = (
    "key IN ('admin.system_status_panel', 'admin.preview_notice', 'pwa.offline_queue')"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("ck_feature_flag_known_key", "feature_flag", type_="check")
    op.create_check_constraint("ck_feature_flag_known_key", "feature_flag", NEW_KEYS)
    op.execute(
        "INSERT INTO feature_flag (id, key, enabled, revision) VALUES "
        "('95000000-0000-4000-8000-000000000003', 'pwa.offline_queue', false, 1) "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("DELETE FROM feature_flag WHERE key = 'pwa.offline_queue'")
    op.drop_constraint("ck_feature_flag_known_key", "feature_flag", type_="check")
    op.create_check_constraint("ck_feature_flag_known_key", "feature_flag", OLD_KEYS)
