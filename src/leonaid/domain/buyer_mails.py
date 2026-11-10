"""The action's switches for mails to buyers.

A settings row, not a capability: the club changes it while the action runs.
Mails for orders of the public form are not behind a switch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError

DEFAULT_DELIVERY_DAY_SEND_TIME = time(7, 0)
EARLIEST_DELIVERY_DAY_SEND_TIME = time(5, 0)
LATEST_DELIVERY_DAY_SEND_TIME = time(12, 0)


@dataclass(frozen=True, slots=True)
class BuyerMailConfiguration:
    action_id: UUID
    # Confirmation and cancellation notice for orders that members and
    # acquirers enter.
    internal_order_mails: bool = False
    # The mail on the delivery day, for orders of every source.
    delivery_day_mail: bool = False
    # Local time of the action (its delivery configuration's zone).
    delivery_day_send_time: time = DEFAULT_DELIVERY_DAY_SEND_TIME
    revision: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.revision, bool) or self.revision < 1:
            raise DomainInvariantError(
                "buyer_mail_revision_invalid",
                "Bitte die Einstellungen neu laden.",
            )
        moment = self.delivery_day_send_time
        if (
            moment.tzinfo is not None
            or moment.second
            or moment.microsecond
            or not (
                EARLIEST_DELIVERY_DAY_SEND_TIME
                <= moment
                <= LATEST_DELIVERY_DAY_SEND_TIME
            )
        ):
            raise DomainInvariantError(
                "buyer_mail_send_time_invalid",
                "Die Uhrzeit der Liefertags-E-Mail muss zwischen 05:00 und "
                "12:00 Uhr liegen.",
            )
