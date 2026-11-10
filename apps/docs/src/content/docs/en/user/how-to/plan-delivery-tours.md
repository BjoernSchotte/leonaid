---
title: Plan delivery tours
description: Assign the stops of a delivery day to drivers, set the base order per window, fix pins and set the start point.
docId: DOC-P051
audience: [user]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: c546921444a3c60a7681373698b85b3c3e37bc59
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Role:** Charity Admin of the campaign (and System Admin). The **Touren**
(tours) view exists only when the feature flag `delivery.tours` is on. It is
off by default, like `pwa.offline_queue`, which drivers need to work offline (see
[Drive my tour](/en/user/how-to/drive-my-tour/)). A system admin switches the flags on. Without the flag, the delivery board works as before (see
[Work the delivery board](/en/user/how-to/work-delivery-board/)).

A tour is one driver on one delivery day. Each driver has one tour per day.

## Open the planner

1. In the back office, open **Auslieferung** and select the campaign.
2. Switch to the view **Touren**. Choose the delivery day.
3. Stops without a driver are listed apart. Each driver has a column; stops
   are grouped by delivery window.

## Assign and order

1. Assign stops to a driver. There are three ways:
   - Drag the stop by its grip (six dots on the left) into the driver's
     column. The column under the pointer is marked and names the window at
     whose end the stop goes.
   - Point at the stop and select **Fahrer ändern** (change driver).
   - Tick several stops and use **Fahrer zuordnen** (assign driver). **Alle
     ohne Fahrer auswählen** ticks every stop without a driver.

   This is also how you hand one stop to another driver. The message offers
   **Rückgängig** (undo).
2. Drag stops inside a window group to set the base order. LeonAid saves on
   drop. The message offers **Rückgängig** (undo). A stop stays in its
   delivery window: the time window is promised to the customer.
3. **Vorschlag sortieren** (sort suggestion) on a driver column proposes an
   order by straight-line distance. If pins are missing, it says **Für den
   Vorschlag fehlen Koordinaten.** (coordinates are missing). **Strecke …**
   shows the straight-line length of the tour.
4. **Karte** (map) in the page header shows and hides the map; LeonAid
   remembers the choice in the browser. The map shows the stops as numbered
   pins, coloured by driver. The numbers follow the order the column shows;
   the column and its numbers carry the colour of the pins.

A driver can reorder their own tour. The driver's order then wins over your
base order until you reset it.

## Start point

Set the start point in the action's delivery settings, in the section
**Startpunkt der Touren** (start point of the tours): the place where the
driver collects all Krapfen in the morning (for example the bakery). Enter the
address and select **Startpunkt speichern** (save); **Startpunkt entfernen**
removes it. If the address is not found, the message **Startpunkt nicht
gefunden – Pin auf der Karte setzen** asks you to set the pin on the map. The
distance and the sort suggestion start there. The start point is optional.

## Pins and addresses

LeonAid looks up each delivery address on the server. It uses the public
Nominatim service. Only street, postal code, city and country are sent, never
names, contacts or order data. Only house-level hits are used.

If no exact hit is found, the stop shows no pin on the map. The stop can still
be assigned and ordered. Set the pin by hand:

1. Select **Pin setzen** (set pin) on the stop and click the place on the map.
2. To move an existing pin, select **Pin versetzen** (move pin).

## Driver note

The order form has an optional field **Hinweis für den Fahrer** (note for the
driver), one line, up to 200 characters, for example "back yard" or "ring
twice". The assigned driver and you see it. It never appears in e-mails.

## Limits

See [Known limits](/en/known-limits/): no road routing, no live tracking, one
tour per driver and day.
