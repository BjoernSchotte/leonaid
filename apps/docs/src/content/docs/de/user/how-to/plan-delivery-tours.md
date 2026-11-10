---
title: Lieferrouten planen
description: Die Stopps eines Liefertags Fahrern zuweisen, die Grundreihenfolge je Fenster festlegen, Pins korrigieren und den Startpunkt setzen.
docId: DOC-P051
audience: [user]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: c546921444a3c60a7681373698b85b3c3e37bc59
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** Charity-Admin der Aktion (und System-Admin). Die Ansicht
**Touren** gibt es nur, wenn das Feature-Flag `delivery.tours` an ist. Es ist
standardmäßig aus, ebenso `pwa.offline_queue`, das Fahrer für die Arbeit
offline brauchen (siehe [Meine Tour fahren](/de/user/how-to/drive-my-tour/)).
Ein System-Admin schaltet die Flags ein. Ohne Flag arbeitet die Auslieferungstafel wie bisher (siehe
[Auslieferung abhaken](/de/user/how-to/work-delivery-board/)).

Eine Tour ist ein Fahrer an einem Liefertag. Jeder Fahrer hat pro Tag eine
Tour.

## Planung öffnen

1. Öffne in der Verwaltung **Auslieferung** und wähle die Aktion.
2. Wechsle zur Ansicht **Touren**. Wähle den Liefertag.
3. Stopps ohne Fahrer stehen getrennt. Jeder Fahrer hat eine Spalte; die
   Stopps sind nach Lieferfenster gruppiert.

## Zuweisen und sortieren

1. Weise Stopps einem Fahrer zu. Es gibt drei Wege:
   - Ziehe den Stopp an seinem Griff (sechs Punkte links) in die Spalte des
     Fahrers. Die Spalte unter dem Zeiger wird markiert und nennt das Fenster,
     an dessen Ende der Stopp kommt.
   - Zeige auf den Stopp und wähle **Fahrer ändern**.
   - Kreuze mehrere Stopps an und nutze **Fahrer zuordnen**. **Alle ohne
     Fahrer auswählen** kreuzt alle Stopps ohne Fahrer an.

   So gibst du auch einen einzelnen Stopp an einen anderen Fahrer weiter. Die
   Meldung bietet **Rückgängig**.
2. Ziehe Stopps innerhalb einer Fenstergruppe, um die Grundreihenfolge
   festzulegen. LeonAid speichert beim Ablegen. Die Meldung bietet
   **Rückgängig**. Ein Stopp bleibt in seinem Lieferfenster: Das Zeitfenster
   ist dem Kunden zugesagt.
3. **Vorschlag sortieren** an einer Fahrerspalte schlägt eine Reihenfolge nach
   Luftlinie vor. Fehlen Pins, steht dort **Für den Vorschlag fehlen
   Koordinaten.** **Strecke …** zeigt die Luftlinien-Länge der Tour.
4. **Karte** im Seitenkopf blendet die Karte ein und aus; LeonAid merkt sich
   die Wahl im Browser. Die Karte zeigt die Stopps als nummerierte Pins, nach
   Fahrer eingefärbt. Die Nummern folgen der Reihenfolge, die die Spalte
   zeigt; Spalte und Nummern tragen die Farbe der Pins.

Ein Fahrer kann seine eigene Tour umsortieren. Seine Reihenfolge gilt dann vor
deiner Grundreihenfolge, bis du sie zurücksetzt.

## Startpunkt

Setze den Startpunkt in den Lieferungs-Einstellungen der Aktion, im Abschnitt
**Startpunkt der Touren**: der Ort, an dem der Fahrer morgens alle Krapfen
abholt (zum Beispiel die Bäckerei). Gib die Adresse ein und wähle
**Startpunkt speichern**; **Startpunkt entfernen** löscht ihn. Wird die Adresse
nicht gefunden, bittet die Meldung **Startpunkt nicht gefunden – Pin auf der
Karte setzen** darum, den Pin auf der Karte zu setzen. Strecke und
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
