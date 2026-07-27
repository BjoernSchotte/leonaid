#!/usr/bin/env python3
"""Prepare ignored real sessions for the POC-090 browser proof."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid5

import asyncpg

from leonaid.domain.sessions import (
    SESSION_LIFETIME,
    session_token_digest,
)

KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
FINN_ID = UUID("10000000-0000-4000-8000-000000000007")
SESSION_NAMESPACE = UUID("ab77cb61-0df1-4df7-a3fb-fbf8bddf58b4")


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Umgebungsvariable fehlt: {name}")
    return value


async def main() -> None:
    output = Path(require_env("SESSION_OUTPUT"))
    now = datetime.now(timezone.utc)
    stale_at = now - timedelta(days=1)
    sessions = (
        (
            "KLARA_STALE_SESSION",
            KLARA_ID,
            "poc090-browser-klara-stale-session-token-value",
            stale_at,
            stale_at,
        ),
        (
            "FINN_SESSION",
            FINN_ID,
            "poc090-browser-finn-finance-session-token-value",
            now,
            now,
        ),
    )
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        await connection.execute(
            "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
            [KLARA_ID, FINN_ID],
        )
        for name, user_id, token, created_at, fresh_login_at in sessions:
            await connection.execute(
                """
                INSERT INTO user_session (
                    id, user_id, token_digest, expires_at,
                    last_seen_at, fresh_login_at, device_hint,
                    created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, 'POC-090 Browser',
                        $7, $5)
                """,
                uuid5(SESSION_NAMESPACE, name),
                user_id,
                session_token_digest(token),
                created_at + SESSION_LIFETIME,
                now,
                fresh_login_at,
                created_at,
            )
    finally:
        await connection.close()

    output.write_text(
        "".join(
            f"{name}={token}\n" for name, _user_id, token, _created, _fresh in sessions
        ),
        encoding="utf-8",
    )
    output.chmod(0o600)
    print("invoice-browser-setup: OK: veraltete Admin- und Finanz-Lesesitzung")


if __name__ == "__main__":
    asyncio.run(main())
