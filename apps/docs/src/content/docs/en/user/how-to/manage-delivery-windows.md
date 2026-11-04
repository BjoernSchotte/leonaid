---
title: Manage delivery windows
description: Enable campaign delivery planning, add time windows, and retire existing windows.
docId: DOC-P012
audience: [user]
diataxis: how-to
contentRevision: 6
reviewedRevision: 6
verifiedAgainst: 0902dfb1bf60793cde4dd67936e7f8424c58a8db
reviewer: Björn Schotte
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

The table lists each window with its status (**Buchbar** or **Stillgelegt**)
and, for campaigns that take orders, the booked boxes without cancelled orders.

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
3. Select **Angaben speichern**.

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
