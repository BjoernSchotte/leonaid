"""Delivery day board: delivered state, drivers per drop, window closure.

Revision ID: 0046_delivery_board
Revises: 0045_invoice_issued_on

``commitment_delivery`` holds the current delivery state and the assigned
driver of one order (no row: open and unassigned). It carries no personal
data of its own; the order's snapshots do, and the existing erasure
anonymises them. Deleting an order deletes its delivery row. History goes
to ``audit_event``. ``delivery_read_audit`` records the first read of a
window's drops per driver and club day and is purged after 90 days.
"""

from alembic import op

revision = "0046_delivery_board"
down_revision = "0045_invoice_issued_on"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- Lets the delivery row reference the order within its action.
        ALTER TABLE commitment
            ADD CONSTRAINT uq_commitment_action_id UNIQUE (action_id, id);

        CREATE TABLE commitment_delivery (
            commitment_id uuid PRIMARY KEY,
            action_id uuid NOT NULL REFERENCES charity_action(id),
            driver_user_id uuid REFERENCES user_account(id),
            driver_assigned_by_user_id uuid REFERENCES user_account(id),
            driver_assigned_at timestamptz,
            state text CHECK (state IN ('delivered', 'missed')),
            state_changed_at timestamptz,
            state_changed_by_user_id uuid REFERENCES user_account(id),
            -- Set when a closure marked the drop missed; only such a drop may
            -- go back to missed after a later delivery in a closed window.
            missed_at_closure boolean NOT NULL DEFAULT false,
            revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
            FOREIGN KEY (action_id, commitment_id)
                REFERENCES commitment(action_id, id) ON DELETE CASCADE,
            CONSTRAINT ck_commitment_delivery_driver_complete CHECK (
                (driver_user_id IS NULL)
                = (driver_assigned_at IS NULL)
                AND (driver_user_id IS NULL)
                = (driver_assigned_by_user_id IS NULL)
            ),
            CONSTRAINT ck_commitment_delivery_state_complete CHECK (
                (state IS NULL) = (state_changed_at IS NULL)
                AND (state IS NULL) = (state_changed_by_user_id IS NULL)
            )
        );
        CREATE INDEX ix_commitment_delivery_driver
            ON commitment_delivery (driver_user_id, action_id)
            WHERE driver_user_id IS NOT NULL;
        CREATE INDEX ix_commitment_delivery_action
            ON commitment_delivery (action_id);

        CREATE TABLE delivery_window_closure (
            window_id uuid PRIMARY KEY,
            action_id uuid NOT NULL,
            closed_at timestamptz NOT NULL,
            closed_by_user_id uuid NOT NULL REFERENCES user_account(id),
            missed_count integer NOT NULL CHECK (missed_count >= 0),
            FOREIGN KEY (action_id, window_id)
                REFERENCES action_delivery_window(action_id, id)
        );

        CREATE TABLE delivery_read_audit (
            driver_user_id uuid NOT NULL REFERENCES user_account(id),
            window_id uuid NOT NULL,
            viewed_on date NOT NULL,
            action_id uuid NOT NULL,
            first_viewed_at timestamptz NOT NULL,
            PRIMARY KEY (driver_user_id, window_id, viewed_on),
            FOREIGN KEY (action_id, window_id)
                REFERENCES action_delivery_window(action_id, id)
        );
        CREATE INDEX ix_delivery_read_audit_viewed
            ON delivery_read_audit (first_viewed_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE delivery_read_audit;
        DROP TABLE delivery_window_closure;
        DROP TABLE commitment_delivery;
        ALTER TABLE commitment DROP CONSTRAINT uq_commitment_action_id;
        """
    )
