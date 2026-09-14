"""Revisioned shared and personal task order."""

from alembic import op

revision = "0043_task_manual_order"
down_revision = "0042_task_personal_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE task_list
            ADD COLUMN order_revision bigint NOT NULL DEFAULT 1
            CHECK (order_revision > 0);
        ALTER TABLE task ADD COLUMN manual_position bigint NOT NULL DEFAULT 0;
        WITH ranked AS (
            SELECT id, row_number() OVER (
                PARTITION BY list_id, epic_id ORDER BY created_at, id
            ) * 1024 AS position
            FROM task
        )
        UPDATE task SET manual_position=ranked.position
        FROM ranked WHERE ranked.id=task.id;
        CREATE INDEX ix_task_manual_order
            ON task(list_id, epic_id, manual_position, id);

        ALTER TABLE task_personal_plan
            ADD COLUMN manual_position bigint NOT NULL DEFAULT 0;
        WITH ranked AS (
            SELECT task_id, user_id, row_number() OVER (
                PARTITION BY user_id, state, planned_on ORDER BY created_at, task_id
            ) * 1024 AS position
            FROM task_personal_plan
        )
        UPDATE task_personal_plan SET manual_position=ranked.position
        FROM ranked
        WHERE ranked.task_id=task_personal_plan.task_id
          AND ranked.user_id=task_personal_plan.user_id;
        CREATE INDEX ix_task_personal_manual_order
            ON task_personal_plan(user_id, state, planned_on, manual_position, task_id);

        CREATE TABLE task_personal_order_state (
            user_id uuid PRIMARY KEY REFERENCES user_account(id) ON DELETE CASCADE,
            revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0)
        );
        INSERT INTO task_personal_order_state(user_id)
        SELECT DISTINCT user_id FROM task_personal_plan;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE task_personal_order_state;
        DROP INDEX ix_task_personal_manual_order;
        ALTER TABLE task_personal_plan DROP COLUMN manual_position;
        DROP INDEX ix_task_manual_order;
        ALTER TABLE task DROP COLUMN manual_position;
        ALTER TABLE task_list DROP COLUMN order_revision;
    """)
