---
title: Cancel an order
description: Cancel an order that is not delivered yet, with a reason, including its open invoice and follow-up task.
docId: DOC-P047
audience: [user]
diataxis: how-to
contentRevision: 5
reviewedRevision: 5
verifiedAgainst: 1f49427206df2ee9224ad2fb21c80e3f2241649b
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
- **Buyer:** before you cancel, the dialog says whether the buyer gets an
  e-mail. If the order came in through the public order form, the buyer soon
  gets the e-mail **Stornierung Ihrer Bestellung bei …** (your order was
  cancelled) at the address from the form. It names the order number, items,
  total, an invoice cancelled with it and the club's contact details from the
  legal settings. Reason and note are not in it; they stay internal. Repeating
  the command sends no second e-mail.

  For orders that members or acquirers entered, the same applies only when
  the action has the switch **E-Mails für Bestellungen, die Mitglieder
  erfassen** on (see below) and the order holds an e-mail address of the
  buyer. A cancelled draft sends nothing. When the dialog says that LeonAid
  does not notify the buyer, tell the buyer yourself.

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

## E-mails for orders that members enter

Orders from the public form always get the order confirmation and the
cancellation notice. For orders from acquisition and from the back office you
switch the e-mails on per campaign:

1. Open **Aktionen** in the back office, select the campaign and then
   **Bearbeiten**.
2. In the section **E-Mails an Käufer**, switch on **E-Mails für
   Bestellungen, die Mitglieder erfassen**. The switch applies at once, also
   while the campaign runs, and you can switch it off again at any time.

From then on the buyer gets the order confirmation as soon as the order is
ready for review: when it is captured, when a draft is completed, or when a
manager adds missing details. This also applies to orders that the app saved
offline and sent later. The e-mail says that a member of the club recorded
the order. Each order is confirmed once; a later change of address or
delivery window sends no second confirmation. Without an e-mail address of
the buyer in the order nothing is sent.

The e-mail goes to the address that the sponsor has in the CRM. The capture
form of the acquisition app and the form **Angaben ergänzen** show this
address before you save and name the e-mails that go there. Check with the
buyer that it is right.

LeonAid does not send a confirmation that would come too late: not after the
delivery was ticked off, not after the delivery window ended, and not once
the campaign is completed. So an order that is captured or completed
afterwards triggers no confirmation.

LeonAid does not confirm orders from before you switched the e-mails on by
itself. You can send the confirmation in the order, one by one (see below).

The club's privacy notice must name these e-mails. A system admin maintains
it under **Rechtliches**; the template holds the section **Bestellungen, die
ein Mitglied für Sie erfasst** for it. LeonAid does not check that the active
version contains the section.

## See the e-mails of an order and send one again

The detail pane of every order shows its order number (**Bestellnummer**)
at the top; every order has one, however it was captured. It is `LA-` and
eight characters, for example `LA-7F3K2QWX`, without the characters 0, O, 1,
I and L that are easy to mix up, so that a buyer can say it on the phone.
Public orders from before this change keep their long number (`LA-` and 32
characters). The search of the list finds the order by either.

The section **E-Mails an den Käufer** shows one row per e-mail:
**Bestellbestätigung** (order confirmation) and, after a cancellation,
**Stornierung** (cancellation notice). The state is **Gesendet** (sent) with
date and time, **Wartet** (waiting), **Fehlgeschlagen** (failed), **Nicht
gesendet** (not sent) or **Nicht fällig** (not due); the reason stands below
it, for example that the order has no e-mail address, that the campaign has
the e-mails switched off, that the delivery is already recorded, that the
delivery window is over or that the campaign is completed.

If the buyer did not get an e-mail, select **Erneut senden** (send again).
If an e-mail that is due never went out, the button reads **Senden** (send):
for example for an order from before you switched the e-mails on. The button
exists whenever the e-mail is due now and none is waiting. It is absent while
the e-mail waits, and whenever LeonAid would not send the e-mail by itself
either: without an address, with the e-mails switched off, for a draft, and
for the confirmation of an order that is cancelled, delivered or past its
window. A confirmation that is sent again states the order as it is today,
not as it was then. At most ten order e-mails go to one mailbox per hour;
above that the delivery fails, and you send again later. If LeonAid answers a
click by saying that the earlier request arrived, no further e-mail went out.
