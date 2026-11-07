"""When a capture happened on the device, bounded by when Core received it.

The acquisition PWA queues contacts and orders while offline and sends them
later with ``capturedAt``: the moment the acquirer saved the capture on the
device (specs/pwa-offline-queue/PLAN.md §11.2). The device clock is untrusted,
so Core accepts it only inside a window around its own receive time:

* not later than receive time + 5 minutes (clock drift of a phone);
* not earlier than receive time − 14 days, the retention of unsent queue
  entries (decision D5).

Only the history uses ``capturedAt``. Authorisation, membership, prices,
delivery windows and suppression are always evaluated at receive time, so a
revoked acquirer cannot backdate a capture into their membership.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import require_aware

CAPTURE_MAX_AGE = timedelta(days=14)
CAPTURE_MAX_LEAD = timedelta(minutes=5)


def bounded_captured_at(captured_at: datetime, *, received_at: datetime) -> datetime:
    """``captured_at`` in UTC, or ``captured_at_out_of_range`` (422)."""

    require_aware(captured_at, "captured_at")
    require_aware(received_at, "received_at")
    if not (
        received_at - CAPTURE_MAX_AGE <= captured_at <= received_at + CAPTURE_MAX_LEAD
    ):
        raise DomainInvariantError(
            "captured_at_out_of_range",
            "Der Erfassungszeitpunkt liegt außerhalb des erlaubten Zeitraums "
            "(höchstens 14 Tage zurück, höchstens 5 Minuten voraus). "
            "Bitte Datum und Uhrzeit des Geräts prüfen.",
        )
    return captured_at.astimezone(timezone.utc)
