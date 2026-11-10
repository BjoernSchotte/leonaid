---
title: Switch on notifications
description: Switch on, test and switch off notifications of the acquisition app for follow-ups, new orders, tasks and deliveries on your own device.
docId: DOC-P058
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: b1c08d3c04dbf7a46d1bb477753e36ad369a6fec
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Role:** member with access to the acquisition app. Notifications exist only
when the system administration has switched on the feature flag
**Benachrichtigungen in der Akquise-App**. The menu **Mehr** then has the
entry **Benachrichtigungen**. The flag is switched on only once the active
members' privacy notice carries the section "Benachrichtigungen auf deinem
Gerät" (see
[Maintain the Impressum and the privacy policy](../maintain-legal-pages/)) and the
operator has set the key (see
[Requirements and configuration](../../../ops/reference/requirements-and-configuration/)).

## Prerequisites

- A current Chrome, Edge, Firefox or Safari.
- **iPhone and iPad:** LeonAid must be on the home screen and opened from
  there (iOS/iPadOS 16.4 or later). A Safari tab gets no notifications. To
  put LeonAid there: open LeonAid in Safari, tap **Teilen** (Share), choose
  **Zum Home-Bildschirm** (Add to Home Screen).
- You are signed in on the device that shall get the notifications. You
  switch on each device separately.

## Switch on

1. In the acquisition app open **Mehr**, then **Benachrichtigungen**.
2. Choose **Benachrichtigungen einschalten**.
3. Your browser asks whether LeonAid may send notifications. Choose
   **Zulassen** (Allow).
4. Under **Worüber möchtest du Bescheid bekommen?** switch on what you need.
   Each kind is off until you switch it on. The switches hold for all your
   devices.

| Switch                | When the notification comes                               | What it opens      |
| --------------------- | --------------------------------------------------------- | ------------------ |
| **Wiedervorlagen**    | Once a day from 8:00, when follow-ups are due or overdue. | **Wiedervorlagen** |
| **Neue Bestellungen** | When an order for you arrives under **Neues**.            | **Neues**          |
| **Aufgaben**          | When someone assigns a task to you.                       | **Aufgaben**       |
| **Lieferungen**       | When deliveries are assigned to you for a tour.           | The delivery page  |

You see only the switches that fit your roles: **Wiedervorlagen** as an
acquirer, **Neue Bestellungen** as an acquirer or charity admin,
**Lieferungen** as a driver. **Aufgaben** exists while the tasks module is
switched on.

## Check the result

Under **Dieses Gerät** choose **Test senden**. The page reports **Der Test ist
unterwegs.** Shortly after, your device shows the notification
**Benachrichtigungen funktionieren auf diesem Gerät.** A tap on it opens
LeonAid.

## What a notification says

A notification names the kind and a count, for example **3 Wiedervorlagen
sind fällig.** It contains no names, addresses or amounts. A tap on it opens
the matching page in LeonAid.

At most one notification per kind comes in 15 minutes. LeonAid counts what
arrives in that time and reports it afterwards in one notification. You get
none for something you caused yourself.

## Switch off

- **One kind:** switch its switch off.
- **This device:** choose **Auf diesem Gerät ausschalten**. LeonAid deletes
  the address of this device at once.
- **Sign out:** when you sign out on the device, notifications end there.
  After the next sign-in you switch them on again on the device; your
  switches stay as they were.
- **90 days without opening:** if you do not open the app on a device for 90
  days, your sign-in ends there and the notifications with it. Sign in and
  open the app; then they come again.

## If it does not work

| What you see                                                  | What it means and what helps                                                                                                                                                       |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The menu **Mehr** has no **Benachrichtigungen**               | Your club has not switched the feature on.                                                                                                                                         |
| **Benachrichtigungen sind noch nicht eingerichtet.**          | The operator has set no key. Ask the system administration.                                                                                                                        |
| **Lege LeonAid zuerst auf den Home-Bildschirm.**              | iPhone or iPad in a Safari tab. Follow the three steps on the page.                                                                                                                |
| **Dieser Browser kann keine Benachrichtigungen empfangen.**   | Use a current Chrome, Edge, Firefox or Safari.                                                                                                                                     |
| **Benachrichtigungen sind im Browser blockiert.**             | You declined the browser's question. Allow notifications for the page in the browser's settings (the lock or settings icon next to the address) and reload.                        |
| **Dieses Gerät konnte nicht angemeldet werden.**              | The browser did not reach the notification service. Check the connection and try again.                                                                                            |
| **Das waren viele Tests in kurzer Zeit.**                     | More than five tests in ten minutes, from whatever device. Wait a few minutes.                                                                                                     |
| The test does not arrive                                      | Check in the device's settings that notifications for LeonAid (or the browser) are allowed and no "do not disturb" is active. Then switch the device off and on again on the page. |
| Nothing arrives after a sign-out or a long break              | Sign in, open **Benachrichtigungen** and switch them on again on the device. After 90 days without opening the app the sign-in on the device ends.                                 |
| LeonAid konnte die Anmeldung des Geräts gerade nicht erneuern | The app was opened very often in the last hour. The device stays switched on; **Test senden** and **Auf diesem Gerät ausschalten** are back in about an hour.                      |
| **Du hast schon zehn Geräte angemeldet.**                     | Switch notifications off on a device you no longer use.                                                                                                                            |

## Limits

- Notifications are a hint, not a delivery guarantee. If your device is off
  for more than a day, a notification expires.
- There are no quiet hours and no setting per device. You can register at
  most ten devices.
- When LeonAid cannot reach a device for several days, it removes the
  device. Switch notifications on again there.
- More limits are listed under [Known limits](../../../known-limits/).
