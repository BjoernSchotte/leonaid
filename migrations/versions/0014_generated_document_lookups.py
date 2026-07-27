"""Index generated documents for every supported fach context.

Revision ID: 0014_generated_document_lookups
Revises: 0013_generated_document_storage
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_generated_document_lookups"
down_revision: str | None = "0013_generated_document_storage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = (
    ("ix_generated_document_action_created", "action_id"),
    ("ix_generated_document_commitment_created", "commitment_id"),
    ("ix_generated_document_invoice_created", "invoice_id"),
    ("ix_generated_document_company_created", "twenty_company_id"),
    ("ix_generated_document_person_created", "twenty_person_id"),
)


def upgrade() -> None:
    for name, reference_column in INDEXES:
        op.create_index(
            name,
            "generated_document",
            [reference_column, "created_at"],
        )


def downgrade() -> None:
    for name, _reference_column in reversed(INDEXES):
        op.drop_index(name, table_name="generated_document")
