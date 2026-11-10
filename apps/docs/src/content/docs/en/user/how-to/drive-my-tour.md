---
title: Drive my tour
description: Work through your delivery stops in the app, mark deliveries, reorder stops and keep going offline.
docId: DOC-P052
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 278f0c5658d87a7aaa1829609e883c816d35340b
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Role:** driver (**Ausfahrer**). The tab **Tour** in the app shows **Meine
Tour** (my tour) only when the feature flag `delivery.tours` is on. Without
the flag, use **Auslieferung** (see
[Work the delivery board](/en/user/how-to/work-delivery-board/)).

## Work the tour

1. Open **Tour**. You see only your own stops of the delivery day, with
   address, contact and quantity, without amounts.
2. The fixed block **Nächster Stopp** (next stop) at the bottom shows the next
   open stop. It has **Zugestellt** (delivered) and **Nicht da** (not at home).
3. The map shows your stops. An extra link opens the place in OpenStreetMap.
4. A **Hinweis für den Fahrer** from the customer shows on the next-stop block
   and on the stop row.

Delivered stops stay in place, greyed out. Expand one to see it again.

## Reorder

Drag a stop by its handle. LeonAid saves when you drop it and shows
**Rückgängig** (undo). To return to the planner's order, use **Zurück zur
Planung** (back to the plan) in the ⋮ menu.

## Offline

Offline (feature flag `pwa.offline_queue` also on): the app keeps your tour
cached and shows **Offline – Stand HH:MM** (as of that time). Offline,
LeonAid saves deliveries and your order on the device and sends them as soon
as you are online. If the planner changed the plan meanwhile, the entry
appears under **Du** as **Vom Planer geändert** or **Fenster geschlossen**.

The cached tour is removed when the window is closed, 12 hours after the
window ends, when you sign out and when the flag is switched off. The map
tiles are not stored for offline use. The list works without the map.
