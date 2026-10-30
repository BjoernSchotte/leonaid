"""Task priority, list tags and checklist structure."""

from alembic import op

revision = "0044_task_structure"
down_revision = "0043_task_manual_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE task
            ADD COLUMN priority text NOT NULL DEFAULT 'none'
                CHECK (priority IN ('none','high')),
            ADD COLUMN checklist jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(checklist)='array'),
            ADD CONSTRAINT uq_task_list_id_id UNIQUE (list_id,id);

        CREATE TABLE task_tag (
            id uuid PRIMARY KEY,
            list_id uuid NOT NULL REFERENCES task_list(id) ON DELETE CASCADE,
            title text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 40),
            normalized_title text NOT NULL CHECK (char_length(normalized_title)>0),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (list_id,id),
            UNIQUE (list_id,normalized_title)
        );
        CREATE TABLE task_tag_assignment (
            list_id uuid NOT NULL,
            task_id uuid NOT NULL,
            tag_id uuid NOT NULL,
            PRIMARY KEY (task_id,tag_id),
            FOREIGN KEY (list_id,task_id)
                REFERENCES task(list_id,id) ON DELETE CASCADE,
            FOREIGN KEY (list_id,tag_id)
                REFERENCES task_tag(list_id,id) ON DELETE CASCADE
        );
        CREATE INDEX ix_task_priority ON task(list_id,priority,id)
            WHERE priority<>'none';
        CREATE INDEX ix_task_tag_assignment_tag
            ON task_tag_assignment(tag_id,task_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE task_tag_assignment;
        DROP TABLE task_tag;
        DROP INDEX ix_task_priority;
        ALTER TABLE task DROP CONSTRAINT uq_task_list_id_id;
        ALTER TABLE task DROP COLUMN checklist;
        ALTER TABLE task DROP COLUMN priority;
    """)
