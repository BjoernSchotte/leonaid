"""Separate page access concurrency from immutable content revisions."""

from alembic import op

revision = "0039_knowledge_access_revision"
down_revision = "0038_knowledge_pages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE knowledge_page ADD COLUMN access_revision bigint NOT NULL DEFAULT 1 CHECK (access_revision > 0)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE knowledge_page DROP COLUMN access_revision")
