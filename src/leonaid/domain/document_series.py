"""Document series: one gapless counter per document kind and prefix.

ADR-0015. A series belongs to the installation, not to an action. Invoices
and their cancellation invoices share the ``invoice`` series; donation pledges
and donation receipts each have their own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from leonaid.domain.errors import DomainInvariantError

SERIES_PREFIX = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,23}$")
MINIMUM_WIDTH = 3
MAXIMUM_WIDTH = 8


class DocumentSeriesKind(StrEnum):
    INVOICE = "invoice"
    DONATION = "donation"
    DONATION_RECEIPT = "donation_receipt"


class NumberedDocumentKind(StrEnum):
    """Which document holds an issued number; the number is unique over all."""

    INVOICE = "invoice"
    INVOICE_CANCELLATION = "invoice_cancellation"
    DONATION = "donation"
    DONATION_RECEIPT = "donation_receipt"


def format_document_number(prefix: str, serial: int, width: int) -> str:
    return f"{prefix}{serial:0{width}d}"


def series_of_number(number: str) -> tuple[str, int]:
    """Prefix and width of the series a document number belongs to.

    The last resort when neither a profile nor a legal configuration names
    the prefix: the digits at the end are the serial, the rest the prefix. A
    number without digits at its end becomes the prefix of a series of its
    own, so a document can always be numbered.
    """

    head = number.rstrip("0123456789")
    digits = len(number) - len(head)
    if digits and head and SERIES_PREFIX.fullmatch(head):
        return head, min(max(digits, MINIMUM_WIDTH), MAXIMUM_WIDTH)
    prefix = f"{number[:23]}-"
    if not SERIES_PREFIX.fullmatch(prefix):
        raise DomainInvariantError(
            "document_series_prefix_invalid",
            "Aus dieser Belegnummer lässt sich kein Nummernkreis ableiten.",
        )
    return prefix, MINIMUM_WIDTH


@dataclass(frozen=True, slots=True)
class DocumentSeries:
    kind: DocumentSeriesKind
    prefix: str
    next_number: int
    width: int

    def __post_init__(self) -> None:
        if not SERIES_PREFIX.fullmatch(self.prefix):
            raise DomainInvariantError(
                "document_series_prefix_invalid",
                "Das Präfix darf nur Großbuchstaben, Zahlen und Bindestriche enthalten.",
            )
        if (
            isinstance(self.next_number, bool)
            or self.next_number <= 0
            or not MINIMUM_WIDTH <= self.width <= MAXIMUM_WIDTH
        ):
            raise DomainInvariantError(
                "document_series_sequence_invalid",
                "Der Nummernkreis benötigt eine positive Nummer und drei bis acht Stellen.",
            )

    @property
    def next_document_number(self) -> str:
        return format_document_number(self.prefix, self.next_number, self.width)

    def advanced(self) -> DocumentSeries:
        """The series after its next number was issued."""

        return DocumentSeries(
            kind=self.kind,
            prefix=self.prefix,
            next_number=self.next_number + 1,
            width=self.width,
        )
