---
title: Manage delivery windows
description: Enable campaign delivery planning, add time windows, and retire existing windows.
docId: DOC-P012
audience: [user]
diataxis: how-to
contentRevision: 8
reviewedRevision: 8
verifiedAgainst: 52718b176309716b363998e37aa2c91349cdbe8f
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Role:** charity administrator for the affected campaign. The
**Lieferfenster** (delivery windows) tab appears for campaigns with the
**Auslieferung** (delivery) capability. Templates such as **Krapfentaxi**
enable it; for other campaigns, enable it with **Bearbeiten** under
**Funktionen** while the campaign is a draft or scheduled. Delivery requires
**Bestellungen**. In the back office, open the campaign and the
**Lieferfenster** tab.

1. Select **Lieferfenster hinzufügen**.
2. Enter a **Tag** (day) within the campaign period and **Von** and **Bis**
   (from, to). For the first window you also choose the **Zeitzone**; it is
   fixed afterwards.
3. Select **Speichern**. The message **Lieferfenster … angelegt.** confirms the
   window. Repeat for more periods.
4. If delivery planning is not active yet, the **Nächster Schritt** block offers
   **Lieferplanung aktivieren**. Confirm the dialog. From then on, new binding
   orders require a delivery address and an available window.

The table lists each window with its status (**Buchbar**, **Ausgebucht** or
**Stillgelegt**: bookable, fully booked or retired) and, for campaigns that take
orders, the booked boxes without cancelled orders.

## Mark a window as fully booked

When a window is full, switch on **Ausgebucht** (fully booked) in its row. The
change applies at once, the message **… ist als ausgebucht markiert.** confirms
it, and the log records who made it and when. LeonAid counts no quantities for
this; you decide when a window is full.

- In the public order form, the window appears with the note **ausgebucht**
  and cannot be selected. If it becomes full while someone fills in the form,
  LeonAid refuses the order and asks for another window; the other entries are
  kept.
- The back office and acquisition show the window with **(ausgebucht)**. If you
  select it anyway, the dialog **Lieferfenster ist ausgebucht** asks first;
  **Trotzdem eintragen** (book anyway) books the order and notes it in the log.
- Switch **Ausgebucht** off to offer the window again (**… ist wieder
  buchbar.**). Existing orders do not change.

The switch exists only for open windows that have not started yet. Retiring a
window clears **Ausgebucht**.

Stored windows are not edited. Select **Stilllegen** on the old window,
confirm **Fenster stilllegen**, and add the new time. Existing orders retain
their booked snapshot. If all windows are retired, no new binding order can be
completed.

If someone else changed the windows in the meantime, the dialog loads the
current state and keeps your input. Check it and select **Speichern** again.

## Complete missing delivery details

Orders captured before delivery planning was enabled have no delivery address
or window. While delivery planning is active, such an order cannot be invoiced:
**Rechnung prüfen** shows **Lieferangaben fehlen** and the approval stays
disabled.

1. Open **Bestellungen** (orders) and select the order. The side pane shows the
   **Nächster Schritt** (next step) block; select **Angaben ergänzen** there.
2. Enter the delivery address, select a window and, if needed, correct the
   billing address.
3. Select **Angaben speichern**. If the window is marked fully booked, also for
   a draft that already has its window, confirm **Trotzdem eintragen**.

The confirmation says **Angaben gespeichert. Die Bestellung ist prüfbereit.**
Buyer, items and prices stay unchanged. A booked window stays fixed, even if it
was retired later. Invoiced orders can no longer be changed.

### Record a past delivery

If all delivery windows are already over, you can still record, as Charity
Admin, when the order was actually delivered. The form shows the group
**Vergangene Lieferzeiten (nachträglich erfassen)** for this. It also contains
retired windows that have already started.

1. In this group, select the window in which the delivery took place. The note
   **Die Lieferung wird nachträglich für ein vergangenes Zeitfenster erfasst.**
   appears.
2. Enter the delivery address and the billing address, then select **Angaben
   speichern**.

The audit log marks this completion as historical. It stores no addresses or
contact details. You can then review and issue the invoice. This also works
when the campaign's order period is already closed; a draft then becomes ready
for review. Archived campaigns stay unchanged. Acquisition and public orders
never offer past windows.

If another administrator saved the order in the meantime, your inputs stay in
the form. Select **Aktuellen Stand laden und vergleichen**, check the stored
details, then select **Meine Eingaben auf diesen Stand anwenden** and save
again.

## On the delivery day

Booked orders appear per window on the **Auslieferung** (delivery) page. There
you assign drivers, tick off deliveries and close windows; see
[Work the delivery board](/en/user/how-to/work-delivery-board/).

## E-mail on the delivery day

LeonAid can send buyers an e-mail with their delivery window on the day of
the delivery: **Ihre Lieferung kommt heute zwischen 10:00 und 12:00 Uhr**
(your delivery comes today between 10:00 and 12:00). It names the order
number, the delivery window, the delivery address, the ordered quantities and
the club's contact details. Names or phone numbers of drivers, the note for
the driver, prices and an arrival time per address are not in it.

1. Open the campaign and select **Bearbeiten**.
2. In the section **E-Mails an Käufer**, switch on **E-Mail am Liefertag**.
   The switch applies at once, also while the campaign runs. For campaigns
   without the function **Auslieferung** it stays off.
3. Under **E-Mail am Liefertag senden ab**, select the time between 05:00 and
   12:00 (default 07:00). It applies in the time zone of the delivery windows.

From that time on the delivery day, the e-mail goes to every order whose
window starts on that day, if the order is ready for review, confirmed or
invoiced, holds an e-mail address of the buyer and is not ticked off on the
**Auslieferung** board yet. This applies to every origin, also to orders from
the public form. LeonAid checks every five minutes, so the e-mail arrives up
to five minutes after the selected time. An order that is added on the
delivery day itself gets the e-mail at the next check, as long as its window
is not over.

Cancelled orders, drafts, deliveries already ticked off, orders without an
e-mail address and windows that end before the selected time get no e-mail.
Each order gets the e-mail for its window once. At most ten order e-mails go
to one mailbox per hour.

The section **E-Mails an den Käufer** in the order shows whether the e-mail
went out (row **Liefertags-E-Mail**). There you can also send it again on the
delivery day, until the window ends or the delivery is ticked off; see
[Cancel an order](/en/user/how-to/cancel-order/#see-the-e-mails-of-an-order-and-send-one-again).
