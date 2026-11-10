"""Number allocation from the installation's document series (ADR-0015).

A number is taken inside the transaction that stores its document: the series
row is locked, read and advanced with a compare-and-swap, so a failed
transaction uses no number. The series row is taken after the invoice and
order locks (lock order in ``leonaid.adapters.postgres.retry``) and held to
the end of the command.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg

from leonaid.domain.document_series import (
    DocumentSeries,
    DocumentSeriesKind,
    format_document_number,
    series_of_number,
)

# The numeric tail of a number of the prefix $2, or NULL when the number is
# not of that prefix. A number belongs to the longest known series prefix it
# starts with: with the series "RE" and "RE2026", "RE20260001" is number 1 of
# "RE2026", not number 20260001 of "RE".
_SERIAL_SQL = """
    CASE
        WHEN left(number, char_length($2)) = $2
         AND substring(number FROM char_length($2) + 1) ~ '^[0-9]{1,18}$'
         AND NOT EXISTS (
             SELECT 1 FROM document_series AS longer
             WHERE char_length(longer.prefix) > char_length($2)
               AND left(number, char_length(longer.prefix)) = longer.prefix
               AND substring(number FROM char_length(longer.prefix) + 1)
                   ~ '^[0-9]{1,18}$'
         )
        THEN substring(number FROM char_length($2) + 1)::bigint
    END
"""


async def series_of_issued_number(
    connection: asyncpg.Connection[Any],
    *,
    kind: DocumentSeriesKind,
    number: str,
) -> tuple[str, int]:
    """Prefix and width of the series an issued number belongs to.

    The longest known series prefix of that kind the number starts with;
    only when no series matches, the digits at the number's end.
    """

    row = await connection.fetchrow(
        """
        SELECT prefix, width FROM document_series
        WHERE kind = $1
          AND left($2::text, char_length(prefix)) = prefix
          AND substring($2::text FROM char_length(prefix) + 1) ~ '^[0-9]{1,18}$'
        ORDER BY char_length(prefix) DESC
        LIMIT 1
        """,
        kind.value,
        number,
    )
    if row is None:
        return series_of_number(number)
    return str(row["prefix"]), int(row["width"])


async def ensure_series(
    connection: asyncpg.Connection[Any],
    *,
    kind: DocumentSeriesKind,
    prefix: str,
    width: int,
) -> None:
    """Creates the series of a prefix that has none yet.

    It starts after the highest number any document of that prefix already
    holds, so a prefix that comes back into use never repeats a number. An
    existing series keeps its counter.
    """

    await connection.execute(
        f"""
        INSERT INTO document_series (kind, prefix, next_number, width)
        SELECT $1, $2, COALESCE(max({_SERIAL_SQL}), 0) + 1, $3
        FROM document_number
        ON CONFLICT (kind, prefix) DO NOTHING
        """,
        kind.value,
        prefix,
        width,
    )


async def read_series(
    connection: asyncpg.Connection[Any],
    *,
    kind: DocumentSeriesKind,
    prefix: str,
    lock: bool = False,
) -> DocumentSeries | None:
    row = await connection.fetchrow(
        f"""
        SELECT kind, prefix, next_number, width
        FROM document_series
        WHERE kind = $1 AND prefix = $2
        {"FOR UPDATE" if lock else ""}
        """,
        kind.value,
        prefix,
    )
    if row is None:
        return None
    return DocumentSeries(
        kind=DocumentSeriesKind(str(row["kind"])),
        prefix=str(row["prefix"]),
        next_number=int(row["next_number"]),
        width=int(row["width"]),
    )


async def peek_next_serial(
    connection: asyncpg.Connection[Any],
    *,
    kind: DocumentSeriesKind,
    prefix: str,
) -> int:
    """The serial the next document of a series would get; takes no lock."""

    return int(
        await connection.fetchval(
            f"""
            SELECT COALESCE(
                (
                    SELECT next_number FROM document_series
                    WHERE kind = $1 AND prefix = $2
                ),
                (SELECT COALESCE(max({_SERIAL_SQL}), 0) + 1 FROM document_number)
            )
            """,
            kind.value,
            prefix,
        )
    )


async def allocate_document_number(
    connection: asyncpg.Connection[Any],
    *,
    kind: DocumentSeriesKind,
    prefix: str,
    width: int,
    occurred_at: datetime,
) -> str:
    """Takes the next number of a series for a document of this transaction.

    ``width`` only applies when the series does not exist yet. The caller
    stores the document in the same transaction; the database then registers
    the number in ``document_number`` and refuses one that is already taken.
    """

    series = await read_series(connection, kind=kind, prefix=prefix, lock=True)
    if series is None:
        await ensure_series(connection, kind=kind, prefix=prefix, width=width)
        series = await read_series(connection, kind=kind, prefix=prefix, lock=True)
    if series is None:
        raise RuntimeError("Der Nummernkreis ist verschwunden.")
    serial = series.next_number
    number = series.next_document_number
    # The counter can be behind an issued number: an invoice written by the
    # previous release after the migration, or one restored or inserted by
    # hand. Such a number would be refused by the registry on every try. The
    # counter then moves past the highest registered number of the prefix.
    # After the previous release issued the next numbers in a row, no gap
    # follows. A number written by hand further up leaves the numbers below
    # it unused: a gap, traceable to that row, never a duplicate.
    if await connection.fetchval(
        "SELECT EXISTS (SELECT 1 FROM document_number WHERE number = $1)", number
    ):
        serial = int(
            await connection.fetchval(
                f"""
                SELECT COALESCE(max({_SERIAL_SQL}), 0) + 1
                FROM document_number
                -- $1 only keeps the parameter numbering of _SERIAL_SQL.
                WHERE $1::text IS NOT NULL
                """,
                kind.value,
                prefix,
            )
        )
        number = format_document_number(prefix, serial, series.width)
    updated = await connection.execute(
        """
        UPDATE document_series
        SET next_number = $5,
            updated_at = $4
        WHERE kind = $1
          AND prefix = $2
          AND next_number = $3
        """,
        kind.value,
        prefix,
        series.next_number,
        occurred_at,
        serial + 1,
    )
    if updated != "UPDATE 1":
        raise RuntimeError("Der Nummernkreis wurde parallel verändert.")
    return number
