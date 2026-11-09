"""Delivery tours: geocode the not_found addresses once more.

Revision ID: 0061_delivery_geo_regeocode
Revises: 0060_delivery_start_geocoding

The first acceptance rule turned exact Nominatim hits into ``not_found``
(it asked for an importance that Nominatim never gives to addresses). A
``not_found`` outcome is final for an address, so the wrong rows would stay.
This deletes the rows of the geocoder (and clears the same outcome of a start
address); the job then looks the addresses up again with the new rule. Manual
pins and found points stay. The downgrade does nothing: the rows are derived
data and the job makes them again.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0061_delivery_geo_regeocode"
down_revision: str | None = "0060_delivery_start_geocoding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
DATA_MIGRATION_REFERENCE = (
    "Deletes only delivery_geo rows with source geocoder and outcome not_found "
    "and clears the not_found lookup state of start addresses. All of it is "
    "derived data that the worker job rebuilds from the stored addresses."
)
BACKUP_REFERENCE = "infra/backup/README.md#schema-changing-migrations"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        DELETE FROM delivery_geo
        WHERE source = 'geocoder' AND outcome = 'not_found';

        UPDATE action_delivery_configuration
        SET start_geo_outcome = NULL,
            start_geo_attempts = 0,
            start_geocoded_at = NULL,
            start_geocoder = NULL
        WHERE start_geo_outcome = 'not_found'
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
