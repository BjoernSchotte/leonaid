from __future__ import annotations

from pathlib import Path

from tools.schema.check_migrations import check_directory


def test_current_migrations_follow_destructive_change_policy() -> None:
    root = Path(__file__).resolve().parents[2]
    assert check_directory(root / "migrations/versions") == []


def test_destructive_migration_requires_data_and_backup_references(
    tmp_path: Path,
) -> None:
    revision = tmp_path / "0002_bad.py"
    revision.write_text(
        "from alembic import op\n"
        "def upgrade() -> None:\n"
        "    op.drop_column('invoice', 'recipient_snapshot')\n",
        encoding="utf-8",
    )

    problems = check_directory(tmp_path)

    assert len(problems) == 1
    assert "BACKUP_REFERENCE" in problems[0]
    assert "DATA_MIGRATION_REFERENCE" in problems[0]
