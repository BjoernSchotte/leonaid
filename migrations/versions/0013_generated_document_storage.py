"""Add immutable generated-document storage metadata and render jobs.

Revision ID: 0013_generated_document_storage
Revises: 0012_invoice_issuing
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_generated_document_storage"
down_revision: str | None = "0012_invoice_issuing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("CURRENT_TIMESTAMP")
DATA_MIGRATION_REFERENCE = (
    "upgrade() setzt bestehende Rechnungsdokumente auf pending, verwirft deren "
    "nicht versionierbare Legacy-Referenz und plant eine idempotente "
    "Neuerzeugung über die vorhandene Outbox ein."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade() -> None:
    op.add_column("generated_document", sa.Column("filename", sa.Text()))
    op.add_column("generated_document", sa.Column("storage_bucket", sa.Text()))
    op.add_column("generated_document", sa.Column("storage_version_id", sa.Text()))
    op.add_column("generated_document", sa.Column("size_bytes", sa.BigInteger()))
    op.add_column("generated_document", sa.Column("render_version", sa.Text()))
    op.add_column(
        "generated_document",
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "generated_document",
        sa.Column("available_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "generated_document",
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "generated_document",
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "generated_document",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
    )
    op.alter_column("generated_document", "object_key", nullable=True)
    op.alter_column("generated_document", "sha256", nullable=True)

    op.execute(
        """
        UPDATE generated_document
        SET object_key = NULL,
            sha256 = NULL,
            status = 'pending',
            updated_at = CURRENT_TIMESTAMP
        WHERE document_type = 'invoice_pdf'
        """
    )
    op.execute(
        """
        INSERT INTO outbox_event (
            id, aggregate_type, aggregate_id, event_type,
            idempotency_key, payload
        )
        SELECT
            md5(document.id::text || ':render:v1')::uuid,
            'generated_document',
            document.id,
            'invoice.document.render.requested.v1',
            'invoice-document' || chr(58) || document.id::text
                || chr(58) || 'v1',
            jsonb_build_object('documentId', document.id::text)
        FROM generated_document AS document
        WHERE document.document_type = 'invoice_pdf'
          AND document.invoice_id IS NOT NULL
        ON CONFLICT (idempotency_key) DO NOTHING
        """
    )

    op.create_check_constraint(
        "ck_generated_document_status",
        "generated_document",
        "status IN ('pending', 'available', 'deleted')",
    )
    op.create_check_constraint(
        "ck_generated_document_size",
        "generated_document",
        "size_bytes IS NULL OR size_bytes > 0",
    )
    op.create_check_constraint(
        "ck_generated_document_storage_state",
        "generated_document",
        """
        (
            status = 'pending'
            AND filename IS NULL
            AND storage_bucket IS NULL
            AND object_key IS NULL
            AND storage_version_id IS NULL
            AND size_bytes IS NULL
            AND sha256 IS NULL
            AND render_version IS NULL
            AND available_at IS NULL
            AND sent_at IS NULL
            AND deleted_at IS NULL
        )
        OR
        (
            status IN ('available', 'deleted')
            AND filename IS NOT NULL
            AND storage_bucket IS NOT NULL
            AND object_key IS NOT NULL
            AND storage_version_id IS NOT NULL
            AND size_bytes IS NOT NULL
            AND sha256 IS NOT NULL
            AND render_version IS NOT NULL
            AND available_at IS NOT NULL
            AND (
                (status = 'available' AND deleted_at IS NULL)
                OR (status = 'deleted' AND deleted_at IS NOT NULL AND sent_at IS NULL)
            )
        )
        """,
    )

    op.execute(
        """
        CREATE FUNCTION protect_generated_document()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.sent_at IS NOT NULL THEN
                    RAISE EXCEPTION
                        'sent generated documents are immutable'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.sent_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION
                    'sent generated documents are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.status IN ('available', 'deleted')
               AND (
                   NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.action_id IS DISTINCT FROM OLD.action_id
                   OR NEW.commitment_id IS DISTINCT FROM OLD.commitment_id
                   OR NEW.invoice_id IS DISTINCT FROM OLD.invoice_id
                   OR NEW.twenty_company_id IS DISTINCT FROM OLD.twenty_company_id
                   OR NEW.twenty_person_id IS DISTINCT FROM OLD.twenty_person_id
                   OR NEW.document_type IS DISTINCT FROM OLD.document_type
                   OR NEW.media_type IS DISTINCT FROM OLD.media_type
                   OR NEW.filename IS DISTINCT FROM OLD.filename
                   OR NEW.storage_bucket IS DISTINCT FROM OLD.storage_bucket
                   OR NEW.object_key IS DISTINCT FROM OLD.object_key
                   OR NEW.storage_version_id IS DISTINCT FROM OLD.storage_version_id
                   OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
                   OR NEW.sha256 IS DISTINCT FROM OLD.sha256
                   OR NEW.render_version IS DISTINCT FROM OLD.render_version
                   OR NEW.version IS DISTINCT FROM OLD.version
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at
                   OR NEW.available_at IS DISTINCT FROM OLD.available_at
               )
            THEN
                RAISE EXCEPTION
                    'available generated document bytes are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER generated_document_immutable
        BEFORE UPDATE OR DELETE ON generated_document
        FOR EACH ROW
        EXECUTE FUNCTION protect_generated_document();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER generated_document_immutable ON generated_document")
    op.execute("DROP FUNCTION protect_generated_document()")
    op.drop_constraint(
        "ck_generated_document_storage_state",
        "generated_document",
        type_="check",
    )
    op.drop_constraint(
        "ck_generated_document_size",
        "generated_document",
        type_="check",
    )
    op.drop_constraint(
        "ck_generated_document_status",
        "generated_document",
        type_="check",
    )
    op.execute(
        """
        UPDATE generated_document
        SET object_key = COALESCE(object_key, 'legacy/pending/' || id::text),
            sha256 = COALESCE(sha256, repeat('0', 64))
        """
    )
    op.alter_column("generated_document", "sha256", nullable=False)
    op.alter_column("generated_document", "object_key", nullable=False)
    for column in (
        "updated_at",
        "deleted_at",
        "sent_at",
        "available_at",
        "status",
        "render_version",
        "size_bytes",
        "storage_version_id",
        "storage_bucket",
        "filename",
    ):
        op.drop_column("generated_document", column)
