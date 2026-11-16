"""Own e-mail address for the Impressum.

Revision ID: 0069_legal_imprint_email
Revises: 0068_order_donations

Until now the Impressum showed the invoice issuer's e-mail. A club may name a
different address there (for example the chairperson's) while invoices,
buyer mails and the order form keep the club's order address (E-065).
`imprint_email` is NULL for every existing version: the Impressum then keeps
showing the issuer's address, as before.

The downgrade refuses while a version carries an Impressum e-mail: versions
are immutable evidence of what was published.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0069_legal_imprint_email"
down_revision: str | None = "0068_order_donations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE legal_configuration_version
            ADD COLUMN imprint_email text,
            ADD CONSTRAINT ck_legal_configuration_imprint_email CHECK (
                imprint_email IS NULL
                OR (length(imprint_email) BETWEEN 3 AND 320
                    AND imprint_email ~ '^[^@\s]+@[^@\s]+$')
            )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM legal_configuration_version
                WHERE imprint_email IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    '0069 downgrade refused: an Impressum e-mail exists';
            END IF;
        END;
        $$;
        """
    )
    op.execute("ALTER TABLE legal_configuration_version DROP COLUMN imprint_email")
