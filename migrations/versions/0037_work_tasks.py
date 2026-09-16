"""Task-owned lists, explicit access, epics and revisioned tasks."""

from alembic import op

revision = "0037_work_tasks"
down_revision = "0036_delivery_windows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE task_list (
            id uuid PRIMARY KEY,
            action_id uuid REFERENCES charity_action(id),
            owner_user_id uuid NOT NULL REFERENCES user_account(id),
            title text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 240),
            revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_task_list_action ON task_list (action_id);
        CREATE INDEX ix_task_list_owner ON task_list (owner_user_id);

        CREATE TABLE task_list_member (
            list_id uuid NOT NULL REFERENCES task_list(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES user_account(id),
            access text NOT NULL CHECK (access IN ('viewer', 'editor')),
            PRIMARY KEY (list_id, user_id)
        );
        CREATE INDEX ix_task_list_member_user ON task_list_member (user_id, list_id);

        CREATE TABLE task_epic (
            id uuid PRIMARY KEY,
            list_id uuid NOT NULL REFERENCES task_list(id),
            title text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 240),
            revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (list_id, id)
        );

        CREATE TABLE task (
            id uuid PRIMARY KEY,
            list_id uuid NOT NULL REFERENCES task_list(id),
            epic_id uuid,
            title text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 240),
            description text NOT NULL DEFAULT '' CHECK (char_length(description) <= 10000),
            status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
            assignee_user_id uuid REFERENCES user_account(id),
            due_at timestamptz,
            deferred_until timestamptz,
            revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_by uuid NOT NULL REFERENCES user_account(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (list_id, epic_id) REFERENCES task_epic(list_id, id)
        );
        CREATE INDEX ix_task_list_timeline ON task (list_id, created_at, id);
        CREATE INDEX ix_task_epic ON task (list_id, epic_id) WHERE epic_id IS NOT NULL;
        CREATE INDEX ix_task_assignee_open ON task (assignee_user_id, due_at, id)
            WHERE status = 'open';
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE task;
        DROP TABLE task_epic;
        DROP TABLE task_list_member;
        DROP TABLE task_list;
    """)
