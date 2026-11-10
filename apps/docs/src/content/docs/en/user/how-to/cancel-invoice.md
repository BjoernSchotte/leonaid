---
title: Cancel an invoice
description: Cancel an invoice, find and send the cancellation invoice, and mark a refund as done.
docId: DOC-P053
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: ea0d4b8aca50736cc2d8442cd424e4e083cc472a
reviewer: Claude Code (review by Björn Schotte pending)
---

**Role:** charity admin of the action or global `finance_manager`. Only the
charity admin of the action can send. `finance_reader` sees the cancellation
and the cancellation invoice but cannot change anything.

A cancellation voids the whole invoice. In the same step LeonAid issues a
**cancellation invoice** ("Stornorechnung"). You cannot cancel a part of an
invoice. An order has one invoice only: to correct an invoice, cancel it,
capture a new order and issue that order's invoice.

The interface is German. This page gives the German labels in bold.

## Cancel the invoice

1. Open **Rechnungen** in the back office and select the invoice. The detail
   pane opens.
2. Select **Stornieren**.
3. Enter the **Grund der Stornierung** (reason), at least eight characters. It
   stays internal: the section **Storno** of the invoice shows it, the
   cancellation invoice does not.
4. If the invoice was sent by e-mail, the dialog offers
   **Stornorechnung gleich senden**. The box is ticked. The cancellation
   invoice then goes as a PDF to the address the invoice went to, as soon as it
   is rendered. Clear the box to send it later or not at all.
5. Confirm with **Stornieren**. Because this creates a document, you may have
   to confirm your sign-in again.

The message names the number of the cancellation invoice, for example
**KT26-0017 storniert. Stornorechnung KT26-0042 ausgestellt.**

## What this creates

- **The invoice** keeps its number, data and PDF. Its status changes to
  **Storniert**. The list shows **storniert · Stornorechnung** and the number.
- **The cancellation invoice** is a document of its own. It gets the next
  number of the invoice number series and the date of the cancellation. It
  names the number and date of the cancelled invoice and shows its lines and
  amounts with the opposite sign.
- **The number series** belongs to the whole installation, not to one action.
  Invoices and cancellation invoices of all actions with the same prefix form
  one series without gaps.

The section **Stornorechnung** in the invoice's detail pane shows number and
date. Below it is the PDF: it is rendered shortly after the cancellation and
can then be viewed and downloaded.

## Send the cancellation invoice

If you did not send the cancellation invoice with the cancellation, select
**Stornorechnung senden** in the area **Versand der Stornorechnung**. This
works as soon as the PDF is ready. The area then shows whether the e-mail was
delivered. A failed delivery can be started again there. **Erneut senden**
deliberately sends the same cancellation invoice once more.

The e-mail goes to the e-mail address of the invoice recipient. Without a
stored address LeonAid cannot send the cancellation invoice: download the PDF
and pass it on another way.

## When money had been received

You can also cancel a paid or partly paid invoice. The dialog then names the
amount received.

- The payment stays recorded. On a cancelled invoice it can no longer be
  reversed.
- The cancellation invoice names the amount received and the sentence
  "Die Erstattung erfolgt gesondert." (the refund follows separately).
- LeonAid books no refund. You transfer the amount back outside LeonAid.
- Until then the invoice shows **Erstattung offen** in the list and in the
  detail pane. The filter **Erstattung** finds all invoices with an open
  refund.

When the money has been transferred back:

1. Open the invoice and select **Erstattung erledigt**.
2. Enter the day of the transfer under **Erstattet am**. It lies between the
   day of the cancellation and today.
3. Add a **Notiz** (note) if needed.
4. Confirm with **Erstattung erledigt**. Here too you may have to confirm
   your sign-in again.

The entry only closes the reminder. It cannot be changed or taken back. The
section **Stornorechnung** then shows **Erstattung erledigt am** with the date
and the person.

Cancelling the invoice keeps the order. To drop the order too, cancel it
afterwards (see [Cancel an order](/en/user/how-to/cancel-order/)). The other
way round does not work: an order whose open invoice has a recorded payment
cannot be cancelled. Cancel the invoice first.

## Older cancellations

Invoices cancelled before LeonAid issued cancellation invoices have none.
LeonAid does not invent them afterwards. The section **Stornorechnung** says so
and offers **Stornorechnung ausstellen**. The cancellation invoice then gets
the next number and today's date, not the date of the old cancellation. Here
too you may have to confirm your sign-in again.

## If it does not work

- **No button:** your account has read access only, or the invoice is already
  cancelled.
- **Invoice profile missing:** the cancellation invoice needs the number series
  of the action. Without an invoice profile a system admin must first activate
  the legal details.
- **Stornorechnung gleich senden fails:** without an e-mail address of the
  recipient the server refuses the whole step. Cancel without the tick.
- **Sending not possible yet:** the PDF is still being rendered. Try again a
  moment later.

A cancellation is final. A cancelled invoice cannot be reopened, and a
cancellation invoice cannot be changed or deleted.
