"""Startup phase extraction keeps private logs out of timing evidence."""

from tools.twenty.startup_timings import timings


def test_multiple_starts_produce_only_completed_fixed_phases() -> None:
    log = """2026-09-09T10:00:00.000000000Z Running database setup and migrations...
2026-09-09T10:00:01.000000000Z private-database-url-and-token
2026-09-09T10:00:30.000000000Z Successfully migrated DB!
2026-09-09T10:00:30.000000000Z Registering background sync jobs...
2026-09-09T10:00:42.500000000Z Successfully registered all background sync jobs!
2026-09-09T10:01:00.000000000Z Running database setup and migrations...
2026-09-09T10:01:20.000000000Z Successfully migrated DB!
2026-09-09T10:01:20.000000000Z Registering background sync jobs...
"""
    assert timings(log) == [
        ("twenty-migrations", 30.0),
        ("twenty-cron-registration", 12.5),
        ("twenty-migrations", 20.0),
    ]
