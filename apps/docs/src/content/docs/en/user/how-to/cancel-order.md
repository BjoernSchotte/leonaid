---
title: Cancel an order
description: Cancel an order that is not delivered yet, with a reason, including its open invoice and follow-up task.
docId: DOC-P047
audience: [user]
diataxis: how-to
contentRevision: 4
reviewedRevision: 4
verifiedAgainst: b4bbe992cf790597a2f3ca7934de71995cff5665
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Role:** charity admin of the campaign or system admin, that is the same
people who manage the campaign's orders. Acquirers, drivers and finance roles
do not see the function; the server refuses it for them.

**Prerequisite:** the order is not delivered yet, and no payment is recorded
on its invoice (or every recorded payment is reversed).

1. In the back office, open **Bestellungen** and select the order. The detail
   pane opens.
2. Select **Bestellung stornieren**.
3. Enter a **Grund der Stornierung** (reason), at least eight characters. It
   appears in the order's history and, when an invoice is cancelled with it,
   on that invoice cancellation too.
4. Add a **Notiz** (note) if needed. Only your team sees it.
5. Confirm with **Stornieren**.

The order then carries the **Storniert** stamp and the status **Storniert**.
The **Storno** section shows reason, note, who cancelled it and when; the
**Verlauf** (history) lists it as well. The order stays in the list with all
its data and a struck-through amount. The filter **Status** › **Storniert**
finds all cancelled orders. Quantity and amount totals no longer count them.

## What else happens

- **Delivery:** the order leaves the **Auslieferung** board at once and no
  longer counts there. If it was marked **Nachliefern**, its task in the
  **Nachliefern** list is done. The task gets a note about the cancellation,
  but not the reason: it never holds names or free text from the order.
- **Invoice:** without an invoice, nothing else happens. If the invoice is
  issued or sent and unpaid, the dialog names it by number. It is cancelled
  together with the order: number, data and PDF stay unchanged, its status
  becomes **Storniert**. LeonAid issues a **cancellation invoice**
  ("Stornorechnung") with its own number for it. You find it under
  **Rechnungen** with the invoice and can download it and send it by e-mail
  there (see [Cancel an invoice](/en/user/how-to/cancel-invoice/)). If the
  invoice was sent by e-mail, the dialog offers **Stornorechnung gleich
  senden**; the box is ticked. The cancellation invoice then goes to the same
  address as soon as it is rendered. Without the tick you send it later from
  the invoice. Because this creates a financial
  document, you may have to confirm your sign-in again. Reason and note are
  kept; after the sign-in the dialog opens again and you confirm once more.
- **Buyer:** if the order came in through the public order form, the buyer
  soon gets an e-mail **Stornierung Ihrer Bestellung bei …** (your order was
  cancelled) at the address from the form. It names the order number, items,
  total, an invoice cancelled with it and the club's contact details from the
  legal settings. Reason and note are not in it; they stay internal. Repeating
  the command sends no second e-mail. Orders that members or acquirers entered
  send no e-mail: tell those buyers yourself.

## When it does not work

- **Already delivered:** an order ticked off as delivered cannot be cancelled.
  The dialog says so. If the tick was set by mistake, take it back on the
  **Auslieferung** board (see
  [Work the delivery board](/en/user/how-to/work-delivery-board/)).
- **Payment recorded:** if a payment is booked on the invoice, a partial one
  included, the dialog asks you to reverse it first. Open the invoice under
  **Rechnungen** and select **Zurückbuchen** on the payment. Once every payment
  is reversed, you can cancel the order. LeonAid books no refunds. If the
  sponsor really paid and the payment shall stay recorded, cancel the invoice
  first: that works with a payment too, and LeonAid keeps the open refund in
  view (see [Cancel an invoice](/en/user/how-to/cancel-invoice/)). After that
  the order can be cancelled as well.
- **Changed in the meantime:** if someone changed the order at the same time,
  the server refuses and the list reloads. Check the current state and cancel
  again; your reason stays in the dialog.

A cancellation is final. A cancelled order cannot be reopened; capture a new
order if needed.
