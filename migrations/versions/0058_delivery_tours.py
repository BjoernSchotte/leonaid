"""Delivery tours: flag `delivery.tours` and tour rank columns.

Revision ID: 0058_delivery_tours
Revises: 0057_pwa_offline_queue_flag

specs/krapfentaxi-touren: `base_position` is the planner's order within a
driver's day, `driver_position` the order the driver chose, and
`driver_ordered_at` when they chose it. A driver order needs a driver. The
feature ships off. The downgrade drops the columns and the flag row; the audit
events of flag changes stay (they reference the row id, not a foreign key).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0058_delivery_tours"
down_revision: str | None = "0057_pwa_offline_queue_flag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
DATA_MIGRATION_REFERENCE = (
    "Three nullable columns are added and the known-key check is replaced by "
    "a wider one; existing deliveries and flag rows are untouched."
)
BACKUP_REFERENCE = "infra/backup/README.md#schema-changing-migrations"

OLD_KEYS = (
    "key IN ('admin.system_status_panel', 'admin.preview_notice', 'pwa.offline_queue')"
)
NEW_KEYS = (
    "key IN ('admin.system_status_panel', 'admin.preview_notice', "
    "'pwa.offline_queue', 'delivery.tours')"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        ALTER TABLE commitment_delivery
            ADD COLUMN base_position integer
                CONSTRAINT ck_commitment_delivery_base_position
                CHECK (base_position > 0),
            ADD COLUMN driver_position integer
                CONSTRAINT ck_commitment_delivery_driver_position
                CHECK (driver_position > 0),
            ADD COLUMN driver_ordered_at timestamptz,
            ADD CONSTRAINT ck_commitment_delivery_driver_position_driver
                CHECK (driver_position IS NULL OR driver_user_id IS NOT NULL)
        """
    )
    op.drop_constraint("ck_feature_flag_known_key", "feature_flag", type_="check")
    op.create_check_constraint("ck_feature_flag_known_key", "feature_flag", NEW_KEYS)
    op.execute(
        "INSERT INTO feature_flag (id, key, enabled, revision) VALUES "
        "('95000000-0000-4000-8000-000000000004', 'delivery.tours', false, 1) "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("DELETE FROM feature_flag WHERE key = 'delivery.tours'")
    op.drop_constraint("ck_feature_flag_known_key", "feature_flag", type_="check")
    op.create_check_constraint("ck_feature_flag_known_key", "feature_flag", OLD_KEYS)
    op.execute(
        """
        ALTER TABLE commitment_delivery
            DROP CONSTRAINT ck_commitment_delivery_driver_position_driver,
            DROP COLUMN driver_ordered_at,
            DROP COLUMN driver_position,
            DROP COLUMN base_position
        """
    )
