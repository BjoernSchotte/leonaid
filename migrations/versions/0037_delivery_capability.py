"""Make delivery an explicit action/template capability.

Revision ID: 0037_delivery_capability
Revises: 0036_delivery_windows

Until now delivery planning was gated on the template key ``krapfentaxi``
combined with the ``ordering`` capability. This migration turns that implicit
rule into data: every template version and every action that satisfied the
old gate receives the ``delivery`` capability, so behaviour is unchanged for
existing installations and code can rely on the capability alone.
"""

from alembic import op

revision = "0037_delivery_capability"
down_revision = "0036_delivery_windows"
branch_labels = None
depends_on = None

DATA_MIGRATION_REFERENCE = (
    "Krapfentaxi template versions and actions that offer ordering gain the "
    "delivery capability. Delivery configuration flags, windows and orders "
    "stay untouched."
)


def upgrade() -> None:
    # Inserts do not fire the immutability triggers (UPDATE/DELETE only); the
    # published versions keep their content, the implicit rule becomes explicit.
    op.execute("""
        INSERT INTO action_template_capability (
            template_key, template_version, capability
        )
        SELECT capability.template_key, capability.template_version, 'delivery'
        FROM action_template_capability AS capability
        WHERE capability.template_key = 'krapfentaxi'
          AND capability.capability = 'ordering'
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        INSERT INTO charity_action_capability (action_id, capability)
        SELECT snapshot.action_id, 'delivery'
        FROM action_template_snapshot AS snapshot
        JOIN charity_action_capability AS capability
          ON capability.action_id = snapshot.action_id
         AND capability.capability = 'ordering'
        WHERE snapshot.template_key = 'krapfentaxi'
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE action_template_capability "
        "DISABLE TRIGGER trg_action_template_capability_immutable"
    )
    op.execute("DELETE FROM action_template_capability WHERE capability = 'delivery'")
    op.execute(
        "ALTER TABLE action_template_capability "
        "ENABLE TRIGGER trg_action_template_capability_immutable"
    )
    op.execute("DELETE FROM charity_action_capability WHERE capability = 'delivery'")
