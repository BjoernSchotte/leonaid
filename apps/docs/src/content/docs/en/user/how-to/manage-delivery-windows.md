---
title: Manage delivery windows
description: Enable campaign delivery planning, add time windows, and retire existing windows.
docId: DOC-P012
audience: [user]
diataxis: how-to
contentRevision: 4
reviewedRevision: 4
verifiedAgainst: 0902dfb1bf60793cde4dd67936e7f8424c58a8db
reviewer: Björn Schotte
---

**Role:** charity administrator for the affected campaign. The editor is
available for campaigns with the **Auslieferung** (delivery) capability. Templates
such as **Krapfentaxi** enable it; for other campaigns, enable it under
**Funktionen & Team** while the campaign is a draft or scheduled. Delivery
requires **Bestellungen**. In the back office, open the campaign and the
**Lieferung planen** section.

1. For a new setup, enable **Lieferplanung für diese Aktion aktivieren**.
2. Choose the **Zeitzone** before saving the first window. It becomes fixed as
   soon as stored windows exist.
3. Select **Weiteren Tag hinzufügen**, enter a date within the campaign period,
   and set **Beginn** and **Ende**.
4. Use **Zeitfenster hinzufügen** to add more periods on the same day.
5. Select **Lieferplanung speichern**.

The confirmation says **Lieferplanung gespeichert. Die Fenster gelten für
Akquise und öffentliche Bestellungen.** New binding orders now require a
delivery address and an available window.

Stored times are not edited. Mark the old window with **… Uhr stilllegen**, add
the replacement, and save. Existing orders retain their booked snapshot. If
all windows are retired, no new binding order can be completed.

On an edit conflict, select **Aktuellen Stand laden und Eingaben behalten**,
compare the merged plan, and save again. Use the offered new-tab link if you
need to inspect the current state separately.

## Complete missing delivery details

Orders captured before delivery planning was enabled have no delivery address
or window. While delivery planning is active, such an order cannot be invoiced:
**Rechnung prüfen** shows **Lieferangaben fehlen** and the approval stays
disabled.

1. Open **Bestellungen prüfen**, then the order's **Liefer- und
   Rechnungsangaben ergänzen** section.
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
