"""Actual PostgreSQL namespace migration, existing data and rollback proof."""

from __future__ import annotations

import os
import subprocess
import sys

import psycopg

from leonaid.domain.actions import RESERVED_PUBLIC_ALIASES, PublicActionAlias
from leonaid.domain.errors import DomainInvariantError

PREVIOUS = "0026_invoice_payment_snapshot"
CURRENT = "0027_campaign_alias_namespaces"


def run(*args: str, success: bool = True) -> None:
    result = subprocess.run(
        [sys.executable, *args], capture_output=True, timeout=120, check=False
    )
    if success:
        assert result.returncode == 0, "isolated fixture command failed"
    else:
        assert result.returncode != 0
        assert (
            b"campaign alias migration requires namespace conflict resolution"
            in result.stderr
        )


def main() -> None:
    assert os.environ["LEONAID_ENV"] == "test"
    run("-m", "alembic", "upgrade", PREVIOUS)
    run("tools/seed/golden.py", "seed-core", "tests/fixtures/golden/v1")
    with psycopg.connect(os.environ["CORE_DATABASE_URL"], autocommit=True) as db:

        def snapshot() -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
            return (
                db.execute(
                    "SELECT * FROM public_action_alias ORDER BY alias"
                ).fetchall(),
                db.execute("SELECT * FROM charity_action ORDER BY id").fetchall(),
            )

        baseline = snapshot()
        assert baseline[0]
        original = baseline[0][0][0]
        # Each newly reserved slug was accepted by the preceding database.
        for collision in ("campaigns", "email-change", "health"):
            db.execute(
                "UPDATE public_action_alias SET alias=%s WHERE alias=%s",
                (collision, original),
            )
            conflicting = snapshot()
            run("-m", "alembic", "upgrade", CURRENT, success=False)
            assert snapshot() == conflicting
            assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
                PREVIOUS,
            )
            db.execute(
                "UPDATE public_action_alias SET alias=%s WHERE alias=%s",
                (original, collision),
            )
        assert snapshot() == baseline
        run("-m", "alembic", "upgrade", CURRENT)
        assert snapshot() == baseline
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            CURRENT,
        )
        invalid = sorted(RESERVED_PUBLIC_ALIASES) + [
            "https://example.org",
            "//example.org",
            "a/b",
            "a\\b",
            "a%2fb",
            "a%252fb",
            "a?b",
            "a#b",
            ".",
            "..",
            "Krapfentaxi",
            "",
        ]
        for alias in invalid:
            try:
                PublicActionAlias(alias)
            except DomainInvariantError:
                pass
            else:
                raise AssertionError("domain accepted unsafe alias")
            try:
                with db.transaction():
                    db.execute(
                        "UPDATE public_action_alias SET alias=%s WHERE alias=%s",
                        (alias, original),
                    )
            except psycopg.errors.CheckViolation:
                pass
            else:
                raise AssertionError("database accepted unsafe alias")
            assert snapshot() == baseline
        # Downgrade only removes the new constraint, never aliases or windows.
        run("-m", "alembic", "downgrade", PREVIOUS)
        assert snapshot() == baseline
        run("-m", "alembic", "upgrade", CURRENT)
        run("-m", "alembic", "upgrade", CURRENT)
        assert snapshot() == baseline
    print(
        "alias-namespaces: actual PostgreSQL upgrade, three collision rollbacks, "
        "domain/SQL unsafe-path denial, unchanged alias targets and action windows, "
        "downgrade and repeated upgrade passed"
    )


if __name__ == "__main__":
    main()
