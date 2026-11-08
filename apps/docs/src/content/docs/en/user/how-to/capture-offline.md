---
title: Capture offline
description: Record contacts, follow-ups, orders and new sponsors in the acquisition app without network and send them automatically later.
docId: DOC-P050
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 0a840abef544ca6c79841ab9e4acd677567159f1
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Role:** acquirer of a campaign in the acquisition app. Offline capture is
available only while the system administration has switched on the feature
flag **Offline-Erfassung in der Akquise-App** (offline capture in the
acquisition app). Without the flag the app shows only what is already open
when the network is gone, and keeps nothing. The flag is switched on only once
the active members' privacy notice contains the section "Speicherung auf
deinem Gerät" (see [Maintain the Impressum and the privacy policy](../maintain-legal-pages/)).

## Prepare

1. Open the acquisition app once with a connection and sign in.
2. Wait until your sponsor list has loaded. The app keeps an encrypted copy
   of your own sponsors and of the order details (offers, prices, delivery
   windows) on the device and keeps it current while you are online.

Without a connection the app then starts from this copy. It shows the copy
for up to 7 days after the last update. If it is older, the app shows
**Deine Sponsorenliste ist älter als 7 Tage. Geh online, um sie zu
aktualisieren.** (your sponsor list is older than 7 days; go online to
update it), and you cannot capture anything offline.

## Capture offline

Offline, the app shows **Du bist offline. Neue Kontakte, Wiedervorlagen und
Bestellungen speichert LeonAid auf diesem Gerät und sendet sie, sobald du
wieder online bist.** (new contacts, follow-ups and orders are kept on this
device and sent when you are back online).

- **Contact and follow-up:** open the sponsor, choose **Kontakt erfassen**
  and save as usual. The app confirms **Kontakt gespeichert. Wird gesendet,
  sobald du wieder online bist.** Blocked contact channels cannot be chosen
  offline either.
- **Order:** choose **Bestellung erfassen** at the sponsor. Below the total
  the app says when the price was last updated. If it has changed by the time
  the order is sent, the app asks you before the order is saved. Online it
  asks right on the form, also for a delivery window that filled up
  meanwhile. After saving you see **Bestellung gespeichert**.
- **New sponsor:** under **Neu** you save a draft offline (without the
  street). You can capture a contact for the draft right away; it shows
  **Wartet auf den Entwurf** (waits for the draft). The CRM check runs
  online: the queue shows **Neuer Sponsor … wartet auf deine Prüfung** (new
  sponsor waits for your check). **Jetzt prüfen** opens the usual form with
  your details; add the street if needed and choose **Im CRM prüfen**.
  Afterwards the app sends the contact for this sponsor.

Online, contacts and orders go through the queue too. The app sends them at
once; if an answer is lost, it sends the same entry again, and LeonAid still
stores it only once.

## The queue

The network symbol at the top right shows what is waiting. Tap it to open
the **Warteschlange** (queue).

| Status                           | Meaning                                                                           |
| -------------------------------- | --------------------------------------------------------------------------------- |
| **Wartet auf Verbindung**        | Sent when you are online.                                                         |
| **Wird gesendet …**              | The app is sending.                                                               |
| **Gesendet**                     | LeonAid has the entry (shown until you close the app).                            |
| **Braucht deine Entscheidung**   | LeonAid did not take the entry as it was; you choose what happens.                |
| **Konnte nicht gesendet werden** | Several attempts failed; **Erneut versuchen** (retry) or **Verwerfen** (discard). |
| **Abgelaufen**                   | Older than 14 days; deleted two days later.                                       |
| **Nicht mehr möglich**           | You no longer work in this campaign; kept until you choose **Verwerfen**.         |

The app sends when it opens, when you return to it, when the connection
comes back and with **Jetzt senden** (send now). On an iPhone it sends only
while the app is open.

## Decisions

| What the app reports                                                     | Your choice                                                                                                                                 |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Contact stored, follow-up not taken over                                 | **Meine Wiedervorlage übernehmen** (keep my follow-up) or **Die andere Wiedervorlage behalten** (keep the other one)                        |
| Contact stored, status not taken over                                    | **Meinen Stand übernehmen** (keep my status) or **Den anderen Stand behalten** (keep the other one)                                         |
| The sponsor does not want to be contacted this way                       | **Als Besuch speichern** (save as visit) or **Verwerfen**                                                                                   |
| The sponsor is no longer assigned to you                                 | **Notiz kopieren** (copy note) or **Verwerfen**                                                                                             |
| The delivery window is fully booked meanwhile                            | **Trotzdem eintragen** (book anyway), **Anderes Fenster wählen** (other window), **Als Entwurf speichern** (save as draft) or **Verwerfen** |
| The delivery window no longer exists                                     | **Anderes Fenster wählen**, **Als Entwurf speichern** or **Verwerfen**                                                                      |
| The price has changed                                                    | **Neuen Preis übernehmen** (accept the new price) or **Verwerfen**                                                                          |
| The order now needs a delivery address and window                        | **Ergänzen** (add), **Als Entwurf speichern** or **Verwerfen**                                                                              |
| The offer can no longer be ordered, or the campaign takes no more orders | **Verwerfen**                                                                                                                               |
| Your device's clock is wrong                                             | Check the clock, then **Verwerfen** and capture again                                                                                       |

## Sign out and switch devices

Signing out, in the acquisition app or in the admin area, deletes everything
the app kept on the device. If entries are
still waiting, the app asks first: **Erst senden** (send first; it sends and
opens the queue, in the admin area **Zur Akquise-App**), **Trotzdem
abmelden** (sign out anyway, which deletes them) or **Abbrechen** (cancel). If
another person signs in on the device, the app deletes your data without
asking before it shows their workspace.

## Limits

- Offline you can use sponsors, follow-ups, contacts and orders only. The
  start page with the campaign status, tasks, materials, knowledge, inbox and
  the delivery board need a connection.
- Your sponsors' street addresses are not kept on the device. For an order
  you enter the address.
- Two devices do not know of each other: if you capture the same contact on
  both, it appears twice in the history.
