---
title: Lieferfenster pflegen
description: Lieferplanung einer Aktion aktivieren, Zeitfenster ergänzen und bestehende Fenster stilllegen.
docId: DOC-P012
audience: [user]
diataxis: how-to
contentRevision: 4
reviewedRevision: 4
verifiedAgainst: 0902dfb1bf60793cde4dd67936e7f8424c58a8db
reviewer: Björn Schotte
---

**Rolle:** Charity-Admin der betroffenen Aktion. Der Editor wird für Aktionen
mit der Funktion **Auslieferung** angeboten. Vorlagen wie **Krapfentaxi**
aktivieren sie; bei anderen Aktionen aktivierst du sie im Entwurf oder in der
Planung unter **Funktionen & Team**. Auslieferung setzt **Bestellungen** voraus.
Öffne im Backoffice die Aktion und den Abschnitt **Lieferung planen**.

1. Aktiviere bei einer neuen Planung **Lieferplanung für diese Aktion
   aktivieren**.
2. Wähle die **Zeitzone**, bevor du das erste Fenster speicherst. Sobald Termine
   vorhanden sind, bleibt sie fest.
3. Wähle **Weiteren Tag hinzufügen**, trage ein Datum innerhalb des
   Aktionszeitraums ein und ergänze **Beginn** und **Ende**.
4. Füge mit **Zeitfenster hinzufügen** bei Bedarf weitere Zeiträume am selben
   Tag hinzu.
5. Wähle **Lieferplanung speichern**.

Die Bestätigung lautet **Lieferplanung gespeichert. Die Fenster gelten für
Akquise und öffentliche Bestellungen.** Neue verbindliche Bestellungen müssen
nun eine Lieferadresse und ein verfügbares Fenster enthalten.

Gespeicherte Termine werden nicht editiert. Markiere stattdessen das alte
Fenster mit **… Uhr stilllegen**, ergänze den neuen Termin und speichere.
Bestehende Bestellungen behalten ihren gebuchten Snapshot. Wenn alle Fenster
stillgelegt sind, können keine neuen verbindlichen Bestellungen abgeschlossen
werden.

Bei einem Änderungskonflikt wähle **Aktuellen Stand laden und Eingaben
behalten**, vergleiche die zusammengeführte Planung und speichere erneut. Öffne
bei Unsicherheit den aktuellen Stand im angebotenen neuen Tab.

## Fehlende Lieferangaben ergänzen

Bestellungen, die vor dem Aktivieren der Lieferplanung erfasst wurden, haben
keine Lieferadresse und kein Fenster. Solange die Lieferplanung aktiv ist, kann
für sie keine Rechnung freigegeben werden: **Rechnung prüfen** zeigt
**Lieferangaben fehlen**, und die Freigabe bleibt gesperrt.

1. Öffne **Bestellungen prüfen** und bei der Bestellung den Abschnitt **Liefer-
   und Rechnungsangaben ergänzen**.
2. Trage die Lieferadresse ein, wähle ein Fenster und korrigiere bei Bedarf die
   Rechnungsadresse.
3. Wähle **Angaben speichern**.

Die Bestätigung lautet **Angaben gespeichert. Die Bestellung ist prüfbereit.**
Besteller, Positionen und Preise bleiben unverändert. Ein gebuchtes Fenster
bleibt fest, auch wenn es später stillgelegt wurde. Fakturierte Bestellungen
lassen sich nicht mehr ändern.

### Lieferung nachträglich erfassen

Sind alle Lieferfenster schon vorbei, kannst du als Charity-Admin trotzdem
festhalten, wann die Bestellung tatsächlich geliefert wurde. Das Formular zeigt
dafür die Gruppe **Vergangene Lieferzeiten (nachträglich erfassen)**. Sie
enthält auch stillgelegte Fenster, die schon begonnen haben.

1. Wähle in dieser Gruppe das Fenster, in dem geliefert wurde. Der Hinweis
   **Die Lieferung wird nachträglich für ein vergangenes Zeitfenster erfasst.**
   erscheint.
2. Ergänze Lieferadresse und Rechnungsadresse und wähle **Angaben speichern**.

Das Protokoll markiert diese Ergänzung als nachträglich, ohne Adressen oder
Kontaktdaten zu speichern. Danach kannst du die Rechnung prüfen und freigeben.
Das geht auch, wenn der Bestellzeitraum der Aktion schon abgeschlossen ist;
dann wird ein Entwurf dabei prüfbereit. Archivierte Aktionen bleiben
unverändert. Akquise und öffentliche Bestellungen bieten vergangene Fenster nie
an.

Hat inzwischen eine andere Person die Bestellung gespeichert, bleiben deine
Eingaben im Formular erhalten. Wähle **Aktuellen Stand laden und vergleichen**,
prüfe die gespeicherten Angaben, wähle **Meine Eingaben auf diesen Stand
anwenden** und speichere erneut.
