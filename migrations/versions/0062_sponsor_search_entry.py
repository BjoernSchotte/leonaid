"""Sponsor search index: name and city of the CRM parties with an assignment.

Revision ID: 0062_sponsor_search_entry
Revises: 0061_delivery_geo_regeocode

specs/mails-documents-donations-push §9 (D-S1, D-S2): the core search finds
sponsors through ``sponsor_search_entry``. It holds the name and the city of a
Twenty company or person that has an ``acquisition_assignment``, and nothing
else of the party (no e-mail, phone or street). ``erased_at`` marks an entry
whose name the privacy erasure removed; the row stays as a marker so the sync
does not copy the name back while the party still exists in Twenty.

``sponsor_search_sync`` is the single row of the sync loop: when the last full
pass finished, where an unfinished one continues, and up to when the changed
pass has read Twenty's changes. Both tables start empty;
the first worker run fills the index for the existing assignments. The
downgrade drops both: the index is derived data and the sync rebuilds it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0062_sponsor_search_entry"
down_revision: str | None = "0061_delivery_geo_regeocode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
DATA_MIGRATION_REFERENCE = (
    "Two new empty tables; existing rows are untouched. The worker fills the "
    "index from Twenty for the existing assignments on its first run."
)
BACKUP_REFERENCE = "infra/backup/README.md#schema-changing-migrations"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        CREATE TABLE sponsor_search_entry (
            party_kind text NOT NULL
                CONSTRAINT ck_sponsor_search_entry_party_kind
                CHECK (party_kind IN ('company', 'person')),
            twenty_id uuid NOT NULL,
            display_name text
                CONSTRAINT ck_sponsor_search_entry_display_name
                CHECK (length(display_name) BETWEEN 1 AND 401),
            city text
                CONSTRAINT ck_sponsor_search_entry_city
                CHECK (length(city) BETWEEN 1 AND 200),
            synced_at timestamptz NOT NULL,
            erased_at timestamptz,
            PRIMARY KEY (party_kind, twenty_id),
            CONSTRAINT ck_sponsor_search_entry_erased CHECK (
                (erased_at IS NULL AND display_name IS NOT NULL)
                OR (
                    erased_at IS NOT NULL
                    AND display_name IS NULL
                    AND city IS NULL
                )
            )
        );

        CREATE TABLE sponsor_search_sync (
            singleton boolean PRIMARY KEY DEFAULT true
                CONSTRAINT ck_sponsor_search_sync_singleton CHECK (singleton),
            full_pass_completed_at timestamptz,
            full_pass_after_kind text
                CONSTRAINT ck_sponsor_search_sync_after_kind
                CHECK (full_pass_after_kind IN ('company', 'person')),
            full_pass_after_id uuid,
            changed_pass_read_until timestamptz,
            CONSTRAINT ck_sponsor_search_sync_cursor CHECK (
                (full_pass_after_kind IS NULL) = (full_pass_after_id IS NULL)
            )
        );

        INSERT INTO sponsor_search_sync (singleton) VALUES (true)
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        DROP TABLE sponsor_search_sync;
        DROP TABLE sponsor_search_entry
        """
    )
