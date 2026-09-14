"""Private per-user task planning state."""

from alembic import op

revision = "0042_task_personal_plans"
down_revision = "0041_inbox_cases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE task_personal_plan (
            task_id uuid NOT NULL REFERENCES task(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES user_account(id),
            state text NOT NULL CHECK (state IN ('scheduled','someday','unplanned')),
            planned_on date,
            revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (task_id, user_id),
            CHECK (
                (state='scheduled' AND planned_on IS NOT NULL)
                OR (state IN ('someday','unplanned') AND planned_on IS NULL)
            )
        );
        CREATE INDEX ix_task_personal_plan_user_view
            ON task_personal_plan(user_id, state, planned_on, task_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE task_personal_plan")
