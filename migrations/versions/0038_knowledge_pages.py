"""Knowledge-owned pages, revision snapshots, explicit access and task references."""

from alembic import op

revision = "0038_knowledge_pages"
down_revision = "0037_work_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE knowledge_page (
            id uuid PRIMARY KEY,
            action_id uuid REFERENCES charity_action(id),
            owner_user_id uuid NOT NULL REFERENCES user_account(id),
            revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_knowledge_page_action ON knowledge_page (action_id);
        CREATE INDEX ix_knowledge_page_owner ON knowledge_page (owner_user_id);

        CREATE TABLE knowledge_page_revision (
            page_id uuid NOT NULL REFERENCES knowledge_page(id) ON DELETE CASCADE,
            revision bigint NOT NULL CHECK (revision > 0),
            title text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 240),
            content jsonb NOT NULL CHECK (
                jsonb_typeof(content) = 'object'
                AND coalesce(content->>'type' = 'doc', false)
                AND octet_length(content::text) <= 1048576
            ),
            created_by uuid NOT NULL REFERENCES user_account(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (page_id, revision)
        );
        ALTER TABLE knowledge_page ADD CONSTRAINT knowledge_page_current_revision
            FOREIGN KEY (id, revision) REFERENCES knowledge_page_revision(page_id, revision)
            DEFERRABLE INITIALLY DEFERRED;

        CREATE TABLE knowledge_page_member (
            page_id uuid NOT NULL REFERENCES knowledge_page(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES user_account(id),
            access text NOT NULL CHECK (access IN ('viewer', 'editor')),
            PRIMARY KEY (page_id, user_id)
        );
        CREATE INDEX ix_knowledge_page_member_user ON knowledge_page_member (user_id, page_id);

        CREATE TABLE knowledge_page_task (
            page_id uuid NOT NULL,
            revision bigint NOT NULL,
            task_id uuid NOT NULL REFERENCES task(id),
            PRIMARY KEY (page_id, revision, task_id),
            FOREIGN KEY (page_id, revision) REFERENCES knowledge_page_revision(page_id, revision)
                ON DELETE CASCADE
        );
        CREATE INDEX ix_knowledge_page_task_target ON knowledge_page_task (task_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE knowledge_page_task;
        DROP TABLE knowledge_page_member;
        ALTER TABLE knowledge_page DROP CONSTRAINT knowledge_page_current_revision;
        DROP TABLE knowledge_page_revision;
        DROP TABLE knowledge_page;
    """)
