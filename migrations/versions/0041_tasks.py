"""Tasks module: lists, access, epics, tasks, personal plans, order and structure.

Revision ID: 0041_tasks
Revises: 0040_mail_delivery_set_null

Task data belongs to the tasks module only. Lists grant access through an
owner, explicit members and an optional charity-action context. Every shared
object carries a revision for optimistic concurrency. Personal planning and
personal order are private per user. Priority, list tags and checklists hang
off the task. No foreign key points from core tables into these tables, so
the module can be switched off without touching other data.
"""

from alembic import op

revision = "0041_tasks"
down_revision = "0040_mail_delivery_set_null"
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
            order_revision bigint NOT NULL DEFAULT 1 CHECK (order_revision > 0),
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
            description text NOT NULL DEFAULT ''
                CHECK (char_length(description) <= 10000),
            status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
            assignee_user_id uuid REFERENCES user_account(id),
            due_at timestamptz,
            deferred_until timestamptz,
            priority text NOT NULL DEFAULT 'none' CHECK (priority IN ('none', 'high')),
            checklist jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(checklist) = 'array'),
            manual_position bigint NOT NULL DEFAULT 0,
            revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_by uuid NOT NULL REFERENCES user_account(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (list_id, epic_id) REFERENCES task_epic(list_id, id),
            CONSTRAINT uq_task_list_id_id UNIQUE (list_id, id)
        );
        CREATE INDEX ix_task_list_timeline ON task (list_id, created_at, id);
        CREATE INDEX ix_task_epic ON task (list_id, epic_id) WHERE epic_id IS NOT NULL;
        CREATE INDEX ix_task_assignee_open ON task (assignee_user_id, due_at, id)
            WHERE status = 'open';
        CREATE INDEX ix_task_manual_order
            ON task (list_id, epic_id, manual_position, id);
        CREATE INDEX ix_task_priority ON task (list_id, priority, id)
            WHERE priority <> 'none';

        CREATE TABLE task_personal_plan (
            task_id uuid NOT NULL REFERENCES task(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES user_account(id),
            state text NOT NULL CHECK (state IN ('scheduled', 'someday', 'unplanned')),
            planned_on date,
            manual_position bigint NOT NULL DEFAULT 0,
            revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (task_id, user_id),
            CHECK (
                (state = 'scheduled' AND planned_on IS NOT NULL)
                OR (state IN ('someday', 'unplanned') AND planned_on IS NULL)
            )
        );
        CREATE INDEX ix_task_personal_plan_user_view
            ON task_personal_plan (user_id, state, planned_on, task_id);
        CREATE INDEX ix_task_personal_manual_order
            ON task_personal_plan (user_id, state, planned_on, manual_position, task_id);

        CREATE TABLE task_personal_order_state (
            user_id uuid PRIMARY KEY REFERENCES user_account(id) ON DELETE CASCADE,
            revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0)
        );

        CREATE TABLE task_tag (
            id uuid PRIMARY KEY,
            list_id uuid NOT NULL REFERENCES task_list(id) ON DELETE CASCADE,
            title text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 40),
            normalized_title text NOT NULL CHECK (char_length(normalized_title) > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (list_id, id),
            UNIQUE (list_id, normalized_title)
        );
        CREATE TABLE task_tag_assignment (
            list_id uuid NOT NULL,
            task_id uuid NOT NULL,
            tag_id uuid NOT NULL,
            PRIMARY KEY (task_id, tag_id),
            FOREIGN KEY (list_id, task_id)
                REFERENCES task(list_id, id) ON DELETE CASCADE,
            FOREIGN KEY (list_id, tag_id)
                REFERENCES task_tag(list_id, id) ON DELETE CASCADE
        );
        CREATE INDEX ix_task_tag_assignment_tag
            ON task_tag_assignment (tag_id, task_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE task_tag_assignment;
        DROP TABLE task_tag;
        DROP TABLE task_personal_order_state;
        DROP TABLE task_personal_plan;
        DROP TABLE task;
        DROP TABLE task_epic;
        DROP TABLE task_list_member;
        DROP TABLE task_list;
    """)
