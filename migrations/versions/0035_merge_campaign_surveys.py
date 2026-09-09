"""Join campaign and survey migration histories without changing data."""

revision = "0035_merge_campaign_surveys"
down_revision = (
    "0029_primary_campaign_renderer",
    "0034_survey_recovery_identity",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
