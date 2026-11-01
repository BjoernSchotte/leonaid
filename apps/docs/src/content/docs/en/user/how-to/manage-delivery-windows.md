---
title: Manage delivery windows
description: Enable campaign delivery planning, add time windows, and retire existing windows.
docId: DOC-P012
audience: [user]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 3ffbc7ebf669d360fb6ec7352034e4067d7eb8a4
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
