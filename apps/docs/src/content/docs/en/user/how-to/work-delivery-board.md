---
title: Work the delivery board
description: On the delivery day, assign drivers, tick off deliveries, close windows and follow up on missed drops.
docId: DOC-P046
audience: [user]
diataxis: how-to
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: 05e19df19f872cc5137477166450e97438ff8348
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Role:** Charity Admin of the campaign for the board; drivers for their own
deliveries in the app. The **Auslieferung** (delivery) page exists only when a
campaign you manage has the **Auslieferung** capability and its delivery
planning is active (see
[Manage delivery windows](/en/user/how-to/manage-delivery-windows/)).

## Prepare the board

1. In the back office, open **Auslieferung** and select the campaign at the
   top. The board shows the delivery day with all its windows; switch the day
   with **Liefertag** (delivery day).
2. If deliveries have no driver yet, the **Nächster Schritt** (next step) block
   offers **Fahrer zuweisen** (assign driver). Select one driver for all deliveries
   without a driver. Change single deliveries with the driver icon
   at the end of the row, a whole window with **Fahrer für alle** (driver for
   all).
3. If the campaign has no drivers yet, **Nächster Schritt** shows **Ausfahrer
   einladen** (invite drivers). Invite someone with the **Ausfahrer** (driver)
   role there.

An open window marked fully booked in the **Lieferfenster** tab carries the
note **Ausgebucht** (fully booked) in its header; drivers do not see it.

Drivers only see the deliveries assigned to them. Use **Fahrdienst** (driver
service) to filter the board by driver or **Ohne Fahrer** (no driver).

## Tick off deliveries

1. Select the round check in front of a delivery. The message **…: geliefert.**
   (delivered) offers **Rückgängig** (undo).
2. With the keyboard, move with **J** and **K** and tick with **D**.

While the window is open, you can take back any tick. A cancelled order
leaves the board at once and no longer counts; its **Nachliefern** task is
done (see [Cancel an order](/en/user/how-to/cancel-order/)). A delivered order
cannot be cancelled.

## Close a window

1. Select **Fenster abschließen** (close window) on the window. For a past
   window that is fully delivered, **Nächster Schritt** offers it too.
2. The dialog lists the deliveries that are not ticked yet. Confirm with **Mit …
   offenen abschließen** (close with … open) or **Abschließen** (close).

Open deliveries are then marked **Nachliefern** (deliver later). If the
**Aufgaben** (tasks) module is active, LeonAid creates one task for each in your
**Nachliefern** list. The task names only the order reference, the window and a
link to the order, no names or addresses. Without tasks, the deliveries stay on
the board with the **Nachliefern** note.

## After closing

- **Nachliefern:** tick a delivery marked **Nachliefern** once it has arrived
  after all. This completes its task. You can take this tick back; the task is
  then open again.
- **Booked later:** an order booked into the window after it was closed carries
  the note **nach Abschluss gebucht** (booked after closing), and **Nächster
  Schritt** reminds you with **Zur Lieferung** (go to delivery). No task is
  created for it. Tick it once delivered; this is logged and cannot be taken
  back without reopening. If it is not delivered, reopen the window and close
  it again: it then counts as **Nachliefern**.
- **Correct:** change other ticks in a closed window only after **Wieder
  öffnen** (reopen). Reopening clears the Nachliefern marks and completes their
  tasks. When you close again, LeonAid reopens the same tasks and assigns them
  to you, without duplicates.

## In the app (drivers)

1. Open **Auslieferung** in the app. You see only your deliveries with address
   and contact, without amounts. If you drive for several campaigns, select the
   **Aktion** (campaign) at the top.
2. Tick off what has arrived. While the window is open, you can take the tick
   back.

Once the window is closed, you cannot change anything; contact the campaign
lead. Without a connection, the app shows no deliveries and keeps no addresses
on the device. As soon as you are back online, the board reloads.
