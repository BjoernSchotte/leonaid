"""Index the retention predicates of the outbox and the rate limiter.

Revision ID: 0039_retention_indexes
Revises: 0038_open_action_templates

The worker retention loop deletes completed outbox jobs by ``completed_at``
and expired rate-limit attempts by ``attempted_at`` in bounded batches. Both
predicates need an index; without one every batch scans the whole table.
The partial outbox index covers only completed rows, so it stays small and
does not slow down the claim path.
"""

from alembic import op

revision = "0039_retention_indexes"
down_revision = "0038_open_action_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_outbox_event_retention",
        "outbox_event",
        ["completed_at", "id"],
        postgresql_where="status = 'completed'",
    )
    op.create_index(
        "ix_security_rate_attempt_retention",
        "security_rate_attempt",
        ["attempted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_security_rate_attempt_retention",
        table_name="security_rate_attempt",
    )
    op.drop_index("ix_outbox_event_retention", table_name="outbox_event")
