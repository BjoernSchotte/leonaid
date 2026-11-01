"""Open the action-template catalogue and add presentation themes.

Revision ID: 0038_open_action_templates
Revises: 0037_delivery_capability

Template keys were a closed list (``blank``, ``krapfentaxi``). They become
open slugs so a club can publish further campaign templates as data. A
nullable ``presentation_theme`` on template versions and actions lets the
public renderers pick a visual theme from data instead of guessing from slugs.
"""

from alembic import op

revision = "0038_open_action_templates"
down_revision = "0037_delivery_capability"
branch_labels = None
depends_on = None

DATA_MIGRATION_REFERENCE = (
    "The closed template-key CHECK is replaced by a slug CHECK that accepts "
    "every existing key. Krapfentaxi template versions get the krapfentaxi "
    "presentation theme; actions whose archive slug starts with krapfentaxi "
    "(the former public-site heuristic) get it as well, so every existing "
    "public page keeps its current look."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"

SLUG_CHECK = "~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'"


def upgrade() -> None:
    op.drop_constraint(
        "ck_action_template_key", "action_template_version", type_="check"
    )
    op.create_check_constraint(
        "ck_action_template_key",
        "action_template_version",
        f"template_key {SLUG_CHECK} AND length(template_key) <= 64",
    )
    op.execute(f"""
        ALTER TABLE action_template_version
            ADD COLUMN presentation_theme text,
            ADD CONSTRAINT ck_action_template_presentation_theme CHECK (
                presentation_theme IS NULL OR (
                    presentation_theme {SLUG_CHECK}
                    AND length(presentation_theme) <= 64
                )
            );
        ALTER TABLE charity_action
            ADD COLUMN presentation_theme text,
            ADD CONSTRAINT ck_charity_action_presentation_theme CHECK (
                presentation_theme IS NULL OR (
                    presentation_theme {SLUG_CHECK}
                    AND length(presentation_theme) <= 64
                )
            );
    """)
    # One controlled backfill of published versions; the immutability
    # trigger is re-enabled in the same transaction.
    op.execute("""
        ALTER TABLE action_template_version
            DISABLE TRIGGER trg_action_template_version_immutable;
        UPDATE action_template_version
        SET presentation_theme = 'krapfentaxi'
        WHERE template_key = 'krapfentaxi';
        ALTER TABLE action_template_version
            ENABLE TRIGGER trg_action_template_version_immutable;
    """)
    op.execute("""
        UPDATE charity_action
        SET presentation_theme = 'krapfentaxi'
        WHERE archive_slug ~ '^krapfentaxi(?:-|$)'
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM action_template_version
                WHERE template_key NOT IN ('blank', 'krapfentaxi')
            ) THEN
                RAISE EXCEPTION
                    'downgrade blocked: custom action templates exist';
            END IF;
        END;
        $$;
        ALTER TABLE charity_action
            DROP CONSTRAINT ck_charity_action_presentation_theme,
            DROP COLUMN presentation_theme;
        ALTER TABLE action_template_version
            DROP CONSTRAINT ck_action_template_presentation_theme,
            DROP COLUMN presentation_theme;
    """)
    op.drop_constraint(
        "ck_action_template_key", "action_template_version", type_="check"
    )
    op.create_check_constraint(
        "ck_action_template_key",
        "action_template_version",
        "template_key IN ('blank', 'krapfentaxi')",
    )
