"""Mail address per recipient (Björn, 2026-11-04).

Mails to members (login code, invitation, e-mail change) use "du", like
the member sign-in pages. Mails to buyers and other non-members use "Sie"
(public = Sie). Today these are the invoice delivery and the survey
invitation; LeonAid sends no order confirmation and no contact-form reply.
"""

from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path
from uuid import uuid4

from leonaid.application.invoice_deliveries import (
    InvoiceDeliveryContext,
    InvoiceDeliveryService,
)

SOURCE = Path(__file__).resolve().parents[2] / "src" / "leonaid"
DU = re.compile(r"\b(du|dich|dir|dein\w*)\b", re.I)


def _joined_strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    texts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            texts.append(
                "".join(
                    part.value if isinstance(part, ast.Constant) else "{}"
                    for part in node.values
                )
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            texts.append(node.value)
    return texts


def test_invoice_mail_addresses_the_buyer_with_sie() -> None:
    text = InvoiceDeliveryService._message_text(
        InvoiceDeliveryContext(
            action_id=uuid4(),
            action_name="Krapfentaxi 2026",
            invoice_id=uuid4(),
            invoice_number="KT26-00001",
            document_id=uuid4(),
            recipient_name="Muster GmbH",
            recipient_email="einkauf@muster.invalid",
            issuer_name="Förderverein Lions Club Musterstadt e. V.",
            gross_minor=10800,
            currency="EUR",
            due_on=date(2026, 11, 18),
            payment_reference="KT26-00001",
        )
    )
    assert text.startswith("Guten Tag Muster GmbH,")
    assert "erhalten Sie die Rechnung KT26-00001" in text
    assert "antworten Sie bitte" in text
    assert not DU.search(text)


def test_survey_invitation_addresses_the_recipient_with_sie() -> None:
    texts = _joined_strings(
        SOURCE / "modules" / "surveys" / "adapters" / "postgres" / "surveys.py"
    )
    body = [text for text in texts if "zur Umfrage" in text and "eingeladen" in text]
    subject = [text for text in texts if text.startswith("Ihre Rückmeldung")]
    assert len(body) == 1 and subject
    assert body[0].startswith("Sie sind zur Umfrage")
    assert "Bitte geben Sie" in body[0]
    assert not DU.search(body[0])


def test_member_mails_keep_du() -> None:
    """The member mails stay "du" on purpose; guard against a silent switch."""
    for relative, marker in (
        ("application/sessions.py", "Alternativ kannst du den Code"),
        ("application/invitations.py", "lädt dich als"),
        ("application/email_changes.py", "für dein LeonAid-Konto"),
    ):
        texts = _joined_strings(SOURCE / relative)
        assert any(marker in text for text in texts), relative
