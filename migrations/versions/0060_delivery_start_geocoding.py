"""Delivery tours slice 2: the worker's lookup state of the start point.

Revision ID: 0060_delivery_start_geocoding
Revises: 0059_delivery_geo

specs/krapfentaxi-touren D11 and §8.2: the worker, not the API, geocodes the
action's start address (only the worker has an egress network). Like a
stop's ``delivery_geo`` row, the configuration remembers the last outcome
for the stored address, so the geocoder is asked once per address and a
failure is retried a few times. A point set by hand has no outcome. Label
and address come together; a point needs an address. The downgrade drops
the columns and checks; the outcome is derived data.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0060_delivery_start_geocoding"
down_revision: str | None = "0059_delivery_geo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
DATA_MIGRATION_REFERENCE = (
    "Four new columns with empty defaults; no start point is stored yet, so "
    "the new checks hold for every row."
)
BACKUP_REFERENCE = "infra/backup/README.md#schema-changing-migrations"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        ALTER TABLE action_delivery_configuration
            ADD COLUMN start_geo_outcome text
                CONSTRAINT ck_action_delivery_start_geo_outcome
                CHECK (start_geo_outcome IN ('found', 'not_found', 'failed')),
            ADD COLUMN start_geo_attempts integer NOT NULL DEFAULT 0
                CONSTRAINT ck_action_delivery_start_geo_attempts
                CHECK (start_geo_attempts >= 0),
            ADD COLUMN start_geocoded_at timestamptz,
            ADD COLUMN start_geocoder text
                CONSTRAINT ck_action_delivery_start_geocoder
                CHECK (length(start_geocoder) BETWEEN 1 AND 200),
            ADD CONSTRAINT ck_action_delivery_start_complete CHECK (
                (start_label IS NULL) = (start_address IS NULL)
                AND (start_address IS NOT NULL OR start_lat IS NULL)
            ),
            ADD CONSTRAINT ck_action_delivery_start_geo_state CHECK (
                (start_geo_outcome IS NULL) = (start_geocoded_at IS NULL)
                AND (start_geo_outcome IS NULL) = (start_geocoder IS NULL)
                AND (start_geo_outcome IS NULL) = (start_geo_attempts = 0)
                AND (start_geo_outcome IS NULL OR start_address IS NOT NULL)
                AND (start_geo_outcome IS DISTINCT FROM 'found'
                     OR start_lat IS NOT NULL)
            )
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        ALTER TABLE action_delivery_configuration
            DROP CONSTRAINT ck_action_delivery_start_geo_state,
            DROP CONSTRAINT ck_action_delivery_start_complete,
            DROP COLUMN start_geocoder,
            DROP COLUMN start_geocoded_at,
            DROP COLUMN start_geo_attempts,
            DROP COLUMN start_geo_outcome
        """
    )
