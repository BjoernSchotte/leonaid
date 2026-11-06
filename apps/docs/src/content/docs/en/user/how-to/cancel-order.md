---
title: Cancel an order
description: Cancel an order that is not delivered yet, with a reason, including its open invoice and follow-up task.
docId: DOC-P047
audience: [user]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 05e19df19f872cc5137477166450e97438ff8348
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
  becomes **Storniert**. Because this changes a financial record, you may have
  to confirm your sign-in again. Reason and note are kept; after the sign-in
  the dialog opens again and you confirm once more.
- **Buyer:** LeonAid does not e-mail the buyer. Tell them about the
  cancellation yourself.

## When it does not work

- **Already delivered:** an order ticked off as delivered cannot be cancelled.
  The dialog says so. If the tick was set by mistake, take it back on the
  **Auslieferung** board (see
  [Work the delivery board](/en/user/how-to/work-delivery-board/)).
- **Payment recorded:** if a payment is booked on the invoice, a partial one
  included, the dialog asks you to reverse it first. Open the invoice under
  **Rechnungen** and select **Zurückbuchen** on the payment. Once every payment
  is reversed, you can cancel the order. LeonAid books no refunds.
- **Changed in the meantime:** if someone changed the order at the same time,
  the server refuses and the list reloads. Check the current state and cancel
  again; your reason stays in the dialog.

A cancellation is final. A cancelled order cannot be reopened; capture a new
order if needed.
