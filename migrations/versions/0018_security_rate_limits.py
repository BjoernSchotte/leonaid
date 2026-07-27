"""Add durable transport-boundary rate-limit attempts.

Revision ID: 0018_security_rate_limits
Revises: 0017_feature_flags
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_security_rate_limits"
down_revision: str | None = "0017_feature_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_rate_attempt",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("fingerprint_hash", sa.String(length=64), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_security_rate_attempt"),
        sa.CheckConstraint(
            "length(scope) BETWEEN 3 AND 80",
            name="ck_security_rate_attempt_scope",
        ),
        sa.CheckConstraint(
            "fingerprint_hash ~ '^[0-9a-f]{64}$'",
            name="ck_security_rate_attempt_fingerprint",
        ),
    )
    op.create_index(
        "ix_security_rate_attempt_lookup",
        "security_rate_attempt",
        ["scope", "fingerprint_hash", "attempted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_security_rate_attempt_lookup",
        table_name="security_rate_attempt",
    )
    op.drop_table("security_rate_attempt")
