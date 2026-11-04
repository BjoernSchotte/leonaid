"""Delivery day board: who may tick which drop, and what follows from it.

A drop is an order booked into a delivery window. Its delivery state is
separate from the order status: ``open`` (no row or NULL), ``delivered`` or
``missed`` (the window was closed while it was open). Invoices and orders
never change because of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError

# Order statuses that belong on the board: booked, binding orders.
DELIVERABLE_ORDER_STATUSES = frozenset({"review_ready", "confirmed", "invoiced"})

# Read audits of drivers are kept this long (Björn, 2026-11-04).
READ_AUDIT_RETENTION_DAYS = 90


class DropState(StrEnum):
    OPEN = "open"
    DELIVERED = "delivered"
    MISSED = "missed"


class DeliveryBoardError(DomainInvariantError):
    """A refused board command; ``status`` is the HTTP status to answer."""

    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        super().__init__(code, message)
        self.status = status


@dataclass(frozen=True, slots=True)
class StateChange:
    """The decided transition of one drop."""

    new_state: DropState
    # True when a "Nachliefern" follow-up must now be open, False when it
    # must be done, None when the change does not concern follow-ups.
    follow_up_needed: bool | None


def decide_state_change(
    *,
    current: DropState,
    delivered: bool,
    window_closed: bool,
    manager: bool,
    assigned_driver: bool,
) -> StateChange | None:
    """The transition for "mark delivered" (``delivered``) or its undo.

    Returns None when the drop already is in the target state (idempotent).
    Raises a ``DeliveryBoardError`` when the viewer may not make the change.
    """

    if not (manager or assigned_driver):
        raise DeliveryBoardError(
            "delivery_not_assigned",
            "Diese Lieferung ist Ihnen nicht zugewiesen.",
            status=403,
        )
    if not window_closed:
        if current is DropState.MISSED:
            # Only a closure makes drops missed; reopening clears it again.
            raise DeliveryBoardError(
                "delivery_state_invalid",
                "Diese Lieferung ist als nicht geliefert vermerkt.",
            )
        target = DropState.DELIVERED if delivered else DropState.OPEN
        if target is current:
            return None
        return StateChange(new_state=target, follow_up_needed=None)
    # Closed window: only managers deliver later ("Nachliefern") or undo that.
    if not manager:
        raise DeliveryBoardError(
            "delivery_window_closed",
            "Dieses Lieferfenster ist abgeschlossen.",
        )
    target = DropState.DELIVERED if delivered else DropState.MISSED
    if target is current:
        return None
    if current is DropState.OPEN:
        raise DeliveryBoardError(
            "delivery_state_invalid",
            "In einem abgeschlossenen Fenster gibt es keine offenen Lieferungen.",
        )
    return StateChange(
        new_state=target,
        follow_up_needed=target is DropState.MISSED,
    )


@dataclass(frozen=True, slots=True)
class DropQuantity:
    unit: str
    quantity: int


@dataclass(frozen=True, slots=True)
class DropAddress:
    recipient_name: str
    street_line_1: str
    postal_code: str
    city: str


@dataclass(frozen=True, slots=True)
class DropContact:
    name: str | None
    phone: str | None


@dataclass(frozen=True, slots=True)
class DeliveryDrop:
    """What the board shows of one order. Never amounts or e-mail."""

    commitment_id: UUID
    window_id: UUID
    buyer_name: str
    quantities: tuple[DropQuantity, ...]
    total_boxes: int
    address: DropAddress | None
    contact: DropContact | None
    state: DropState
    state_changed_at: datetime | None
    state_changed_by_name: str | None
    driver_user_id: UUID | None
    driver_name: str | None
    revision: int
    # Manager view only: the order status (to strike cancelled drops).
    order_status: str | None


@dataclass(frozen=True, slots=True)
class WindowClosure:
    closed_at: datetime
    closed_by_name: str
    missed_count: int


@dataclass(frozen=True, slots=True)
class BoardWindow:
    id: UUID
    starts_at: datetime
    ends_at: datetime
    retired: bool
    closure: WindowClosure | None
    drops: tuple[DeliveryDrop, ...]


@dataclass(frozen=True, slots=True)
class BoardDriver:
    user_id: UUID
    display_name: str


@dataclass(frozen=True, slots=True)
class DeliveryBoard:
    action_id: UUID
    action_name: str
    timezone: str
    day: date | None
    days: tuple[date, ...]
    manager: bool
    windows: tuple[BoardWindow, ...]
    # Manager view only: members with the driver role (for assignment).
    drivers: tuple[BoardDriver, ...]
    # Whether closing a window creates "Nachliefern" tasks (tasks enabled).
    follow_up_tasks: bool


def board_day(
    days: tuple[date, ...], requested: date | None, today: date
) -> date | None:
    """The requested day if it has windows, else today, the next or last day."""

    if requested is not None and requested in days:
        return requested
    if not days:
        return None
    if today in days:
        return today
    upcoming = [day for day in days if day > today]
    return upcoming[0] if upcoming else days[-1]
