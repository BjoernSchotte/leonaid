"""The application startup must resolve one head containing both histories."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_campaign_and_survey_migrations_share_one_head() -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    head = scripts.get_current_head()
    assert head is not None
    revisions = {item.revision for item in scripts.iterate_revisions(head, "base")}
    assert {
        "0029_primary_campaign_renderer",
        "0034_survey_recovery_identity",
    } <= revisions
