"""Tasks module: "Nachliefern" follow-up tasks for missed deliveries.

Revision ID: 0047_task_delivery_follow_up
Revises: 0046_delivery_board

One task per missed order, in a list per action and owner. The task mirrors
the drop: missed means open, delivered means done. Owned by the tasks module;
the delivery board only calls the module while it is enabled.
"""

from alembic import op

revision = "0047_task_delivery_follow_up"
down_revision = "0046_delivery_board"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE task_delivery_follow_up_list (
            action_id uuid NOT NULL REFERENCES charity_action(id),
            owner_user_id uuid NOT NULL REFERENCES user_account(id),
            list_id uuid NOT NULL REFERENCES task_list(id) ON DELETE CASCADE,
            PRIMARY KEY (action_id, owner_user_id)
        );
        CREATE TABLE task_delivery_follow_up (
            commitment_id uuid PRIMARY KEY
                REFERENCES commitment(id) ON DELETE CASCADE,
            task_id uuid NOT NULL UNIQUE REFERENCES task(id) ON DELETE CASCADE
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE task_delivery_follow_up;
        DROP TABLE task_delivery_follow_up_list;
        """
    )
