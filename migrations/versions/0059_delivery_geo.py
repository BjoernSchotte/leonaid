"""Delivery tours slice 2: `delivery_geo` and the action's start point.

Revision ID: 0059_delivery_geo
Revises: 0058_delivery_tours

specs/krapfentaxi-touren §5 and §8.2: one row per order holds the geocoded
(or manually pinned) coordinates and the hash of the address they belong to.
Failures are rows too (D14 e): ``not_found`` and ``failed`` carry no
coordinates, and only the geocoder writes them. The row goes with the order
(cascade) and with a privacy erasure. The action may name one start point
(D11), all four columns optional. The downgrade drops the table and columns;
cached coordinates are derived data and can be geocoded again.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0059_delivery_geo"
down_revision: str | None = "0058_delivery_tours"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
DATA_MIGRATION_REFERENCE = (
    "A new empty table and four nullable columns; existing orders and "
    "delivery configurations are untouched."
)
BACKUP_REFERENCE = "infra/backup/README.md#schema-changing-migrations"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        CREATE TABLE delivery_geo (
            commitment_id uuid PRIMARY KEY,
            action_id uuid NOT NULL,
            lat numeric(9,6),
            lon numeric(9,6),
            source text NOT NULL
                CONSTRAINT ck_delivery_geo_source
                CHECK (source IN ('geocoder', 'manual')),
            outcome text NOT NULL
                CONSTRAINT ck_delivery_geo_outcome
                CHECK (outcome IN ('found', 'not_found', 'failed')),
            address_hash text NOT NULL
                CONSTRAINT ck_delivery_geo_address_hash
                CHECK (address_hash ~ '^[0-9a-f]{64}$'),
            geocoded_at timestamptz NOT NULL,
            geocoder text NOT NULL
                CONSTRAINT ck_delivery_geo_geocoder
                CHECK (length(geocoder) BETWEEN 1 AND 200),
            attempts integer NOT NULL DEFAULT 1
                CONSTRAINT ck_delivery_geo_attempts CHECK (attempts > 0),
            FOREIGN KEY (action_id, commitment_id)
                REFERENCES commitment(action_id, id) ON DELETE CASCADE,
            CONSTRAINT ck_delivery_geo_found_has_point CHECK (
                (outcome = 'found') = (lat IS NOT NULL AND lon IS NOT NULL)
                AND (lat IS NULL) = (lon IS NULL)
            ),
            CONSTRAINT ck_delivery_geo_range CHECK (
                (lat IS NULL OR lat BETWEEN -90 AND 90)
                AND (lon IS NULL OR lon BETWEEN -180 AND 180)
            ),
            CONSTRAINT ck_delivery_geo_manual_found CHECK (
                source = 'geocoder' OR outcome = 'found'
            )
        );
        CREATE INDEX ix_delivery_geo_action ON delivery_geo (action_id);

        ALTER TABLE action_delivery_configuration
            ADD COLUMN start_label text
                CONSTRAINT ck_action_delivery_start_label
                CHECK (length(start_label) <= 80),
            ADD COLUMN start_address text
                CONSTRAINT ck_action_delivery_start_address
                CHECK (length(start_address) <= 200),
            ADD COLUMN start_lat numeric(9,6)
                CONSTRAINT ck_action_delivery_start_lat
                CHECK (start_lat BETWEEN -90 AND 90),
            ADD COLUMN start_lon numeric(9,6)
                CONSTRAINT ck_action_delivery_start_lon
                CHECK (start_lon BETWEEN -180 AND 180),
            ADD CONSTRAINT ck_action_delivery_start_point
                CHECK ((start_lat IS NULL) = (start_lon IS NULL))
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        ALTER TABLE action_delivery_configuration
            DROP CONSTRAINT ck_action_delivery_start_point,
            DROP COLUMN start_lon,
            DROP COLUMN start_lat,
            DROP COLUMN start_address,
            DROP COLUMN start_label;
        DROP TABLE delivery_geo
        """
    )
