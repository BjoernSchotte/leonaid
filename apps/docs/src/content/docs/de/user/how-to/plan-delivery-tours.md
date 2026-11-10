---
title: Lieferrouten planen
description: Die Stopps eines Liefertags Fahrern zuweisen, die Grundreihenfolge je Fenster festlegen, Pins korrigieren und den Startpunkt setzen.
docId: DOC-P051
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 278f0c5658d87a7aaa1829609e883c816d35340b
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** Charity-Admin der Aktion (und System-Admin). Die Ansicht
**Touren** gibt es nur, wenn das Feature-Flag `delivery.tours` an ist. Es ist
standardmäßig aus. Ohne Flag arbeitet die Auslieferungstafel wie bisher (siehe
[Auslieferung abhaken](/de/user/how-to/work-delivery-board/)).

Eine Tour ist ein Fahrer an einem Liefertag. Jeder Fahrer hat pro Tag eine
Tour.

## Planung öffnen

1. Öffne in der Verwaltung **Auslieferung** und wähle die Aktion.
2. Wechsle zur Ansicht **Touren**. Wähle den Liefertag.
3. Stopps ohne Fahrer stehen getrennt. Jeder Fahrer hat eine Spalte; die
   Stopps sind nach Lieferfenster gruppiert.

## Zuweisen und sortieren

1. Weise Stopps einem Fahrer zu (Stopp auf die Fahrerspalte ziehen oder die
   Fahrerauswahl am Stopp nutzen).
2. Ziehe Stopps innerhalb einer Fenstergruppe, um die Grundreihenfolge
   festzulegen. LeonAid speichert beim Ablegen. Die Meldung bietet
   **Rückgängig**.
3. Die Karte zeigt die Stopps als nummerierte Pins, nach Fahrer eingefärbt.
   Die Nummern folgen der wirksamen Reihenfolge.

Ein Fahrer kann seine eigene Tour umsortieren. Seine Reihenfolge gilt dann vor
deiner Grundreihenfolge, bis du sie zurücksetzt.

## Startpunkt

Setze je Aktion einen Startpunkt: den Ort, an dem der Fahrer morgens alle
Krapfen abholt (zum Beispiel die Bäckerei). Entfernung und
Sortiervorschlag beginnen dort. Der Startpunkt ist optional.

## Pins und Adressen

LeonAid sucht jede Lieferadresse serverseitig über den öffentlichen
Nominatim-Dienst. Gesendet werden nur Straße, Postleitzahl, Ort und Land,
nie Namen, Kontakte oder Bestelldaten. Nur Treffer auf Hausnummern-Ebene
werden verwendet.

Gibt es keinen genauen Treffer, zeigt der Stopp keinen Pin auf der Karte. Er
kann trotzdem zugewiesen und sortiert werden. Setze den Pin von Hand:

1. Wähle am Stopp **Pin setzen** und klicke auf den Ort in der Karte.
2. Um einen vorhandenen Pin zu verschieben, wähle **Pin versetzen**.

## Hinweis für den Fahrer

Das Bestellformular hat ein optionales Feld **Hinweis für den Fahrer**, eine
Zeile mit bis zu 200 Zeichen, zum Beispiel „Hinterhof“ oder „zweimal
klingeln“. Der zugewiesene Fahrer und du sehen ihn. In E-Mails erscheint er
nie.

## Grenzen

Siehe [Bekannte Grenzen](/de/known-limits/): keine Straßenrouten, keine
Live-Ortung, eine Tour je Fahrer und Tag.
