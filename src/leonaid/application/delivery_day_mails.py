"""The sweep that queues the mail on the delivery day.

Every few minutes one worker asks Core which orders are due
(``order_mails.delivery_day_not_due_reason`` says the rule in words; the
repository applies it in SQL) and writes one job per order and window. There
are no future-dated jobs: switching the feature, moving an order to another
window and closing a window need no job bookkeeping, because the next sweep
only sees what is true then. A job that exists for an order and window is
never written twice, whatever became of it.

The job holds ids and the two legal links only. The worker has no campaign
host directory, so the delivery-day mail carries no link to the campaign.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from leonaid.application.links import LinkBuilder
from leonaid.application.order_mails import (
    OrderMailKind,
    OrderMailLinks,
    order_mail_event,
)
from leonaid.domain.outbox import PendingOutboxEvent

SWEEP_INTERVAL_SECONDS = 300.0
# After a run that another worker's sweep kept out: soon again, not after a
# whole interval.
SWEEP_BUSY_RETRY_SECONDS = 30.0
# Orders per run; a full batch runs the next one after a second.
SWEEP_BATCH = 200


@dataclass(frozen=True, slots=True)
class DueDeliveryDayMail:
    action_id: UUID
    commitment_id: UUID
    window_id: UUID


def delivery_day_links(links: LinkBuilder) -> OrderMailLinks:
    """The legal pages of the public host; no campaign link."""

    return OrderMailLinks(
        campaign_url=None,
        privacy_url=links.site_url("/datenschutz"),
        imprint_url=links.site_url("/impressum"),
    )


def delivery_day_event(
    due: DueDeliveryDayMail, links: OrderMailLinks
) -> PendingOutboxEvent:
    return order_mail_event(
        OrderMailKind.DELIVERY_DAY,
        action_id=due.action_id,
        commitment_id=due.commitment_id,
        links=links,
        window_id=due.window_id,
    )


class DeliveryDayMailRepository(Protocol):
    async def queue_due(
        self, *, now: datetime, limit: int, links: OrderMailLinks
    ) -> int | None:
        """Queue the jobs of up to ``limit`` due orders in one transaction.

        Returns how many were queued, or ``None`` when another worker runs
        the sweep right now (singleton by advisory lock).
        """
        ...


class DeliveryDayMailSweep:
    def __init__(
        self, repository: DeliveryDayMailRepository, links: LinkBuilder
    ) -> None:
        self._repository = repository
        self._links = delivery_day_links(links)

    async def run_once(self, *, now: datetime, limit: int = SWEEP_BATCH) -> int | None:
        """One bounded run: the number of jobs it queued, or ``None`` when
        it did not run because another worker holds the sweep. The caller
        must not count that as a pass."""

        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("The sweep needs an aware current time.")
        return await self._repository.queue_due(now=now, limit=limit, links=self._links)
