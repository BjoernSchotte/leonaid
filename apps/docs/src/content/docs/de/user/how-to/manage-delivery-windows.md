---
title: Lieferfenster pflegen
description: Lieferplanung einer Aktion aktivieren, Zeitfenster ergänzen und bestehende Fenster stilllegen.
docId: DOC-P012
audience: [user]
diataxis: how-to
contentRevision: 10
reviewedRevision: 10
verifiedAgainst: d2c26f1238c117dce276f490cb508561ace7ff13
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** Charity-Admin der betroffenen Aktion. Der Reiter **Lieferfenster**
erscheint bei Aktionen mit der Funktion **Auslieferung**. Vorlagen wie
**Krapfentaxi** aktivieren sie; bei anderen Aktionen aktivierst du sie im
Entwurf oder in der Planung über **Bearbeiten** unter **Funktionen**.
Auslieferung setzt **Bestellungen** voraus. Öffne im Backoffice die Aktion und
den Reiter **Lieferfenster**.

1. Wähle **Lieferfenster hinzufügen**.
2. Trage einen **Tag** innerhalb des Aktionszeitraums sowie **Von** und **Bis**
   ein. Beim ersten Fenster wählst du auch die **Zeitzone**; danach bleibt sie
   fest.
3. Wähle **Speichern**. Die Meldung **Lieferfenster … angelegt.** bestätigt
   das Fenster. Wiederhole das für weitere Zeiträume.
4. Ist die Lieferplanung noch nicht aktiv, bietet der Block **Nächster
   Schritt** **Lieferplanung aktivieren** an. Bestätige den Dialog. Ab dann
   müssen neue verbindliche Bestellungen eine Lieferadresse und ein freies
   Fenster enthalten.

Die Tabelle zeigt jedes Fenster mit Status (**Buchbar**, **Ausgebucht** oder
**Stillgelegt**) und, bei Aktionen mit Bestellungen, die gebuchten Boxen ohne
stornierte Bestellungen.

## Fenster als ausgebucht markieren

Ist ein Fenster voll, schalte in seiner Zeile **Ausgebucht** ein. Die Änderung
gilt sofort, die Meldung **… ist als ausgebucht markiert.** bestätigt sie, und
das Protokoll hält fest, wer sie wann gemacht hat. LeonAid zählt dafür keine
Mengen; du entscheidest, wann ein Fenster voll ist.

- Im öffentlichen Bestellformular erscheint das Fenster mit dem Hinweis
  **ausgebucht** und lässt sich nicht wählen. Wird es voll, während jemand das
  Formular ausfüllt, lehnt LeonAid die Bestellung ab und bittet um ein anderes
  Fenster; die übrigen Eingaben bleiben erhalten.
- Backoffice und Akquise zeigen das Fenster mit **(ausgebucht)**. Wählst du es
  trotzdem, fragt der Dialog **Lieferfenster ist ausgebucht** nach; mit
  **Trotzdem eintragen** wird die Bestellung gebucht und der Vorgang im
  Protokoll vermerkt.
- Schalte **Ausgebucht** wieder aus, um das Fenster erneut anzubieten
  (**… ist wieder buchbar.**). Bestehende Bestellungen ändern sich dabei nicht.

Den Schalter gibt es nur für offene Fenster, die noch nicht begonnen haben.
Stilllegen hebt **Ausgebucht** auf.

Gespeicherte Fenster werden nicht editiert. Wähle beim alten Fenster
**Stilllegen**, bestätige **Fenster stilllegen** und lege den neuen Termin an.
Bestehende Bestellungen behalten ihren gebuchten Snapshot. Wenn alle Fenster
stillgelegt sind, können keine neuen verbindlichen Bestellungen abgeschlossen
werden.

Hat inzwischen eine andere Person die Lieferfenster geändert, lädt der Dialog
den aktuellen Stand und behält deine Eingaben. Prüfe sie und wähle erneut
**Speichern**.

## Fehlende Lieferangaben ergänzen

Bestellungen, die vor dem Aktivieren der Lieferplanung erfasst wurden, haben
keine Lieferadresse und kein Fenster. Solange die Lieferplanung aktiv ist, kann
für sie keine Rechnung freigegeben werden: **Rechnung prüfen** zeigt
**Lieferangaben fehlen**, und die Freigabe bleibt gesperrt.

1. Öffne **Bestellungen** und wähle die Bestellung. Die Seitenansicht zeigt den
   Block **Nächster Schritt**; wähle dort **Angaben ergänzen**.
2. Trage die Lieferadresse ein, wähle ein Fenster und korrigiere bei Bedarf die
   Rechnungsadresse.
3. Wähle **Angaben speichern**. Ist das Fenster als ausgebucht markiert, auch
   bei einem Entwurf mit bereits gewähltem Fenster, bestätige **Trotzdem
   eintragen**.

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

## Am Liefertag

Gebuchte Bestellungen erscheinen pro Fenster auf der Seite **Auslieferung**.
Dort weist du Ausfahrer zu, hakst Lieferungen ab und schließt Fenster ab; siehe
[Auslieferung abhaken](/de/user/how-to/work-delivery-board/).

## E-Mail am Liefertag

LeonAid kann Käufern am Tag der Lieferung eine E-Mail mit ihrem Lieferfenster
senden: **Ihre Lieferung kommt heute zwischen 10:00 und 12:00 Uhr**. Sie nennt
Bestellnummer, Lieferfenster, Lieferadresse, die bestellten Mengen und die
Kontaktdaten des Clubs. Namen oder Telefonnummern von Ausfahrern, der Hinweis
für den Fahrer, Preise und eine Ankunftszeit je Adresse stehen nicht darin.

1. Öffne die Aktion und wähle **Bearbeiten**.
2. Schalte im Abschnitt **E-Mails an Käufer** den Schalter **E-Mail am
   Liefertag** ein. Er gilt sofort, auch während die Aktion läuft. Bei
   Aktionen ohne die Funktion **Auslieferung** bleibt er aus.
3. Wähle bei **E-Mail am Liefertag senden ab** eine volle oder halbe Stunde
   zwischen 05:00 und 12:00 Uhr (voreingestellt 07:00 Uhr). Sie gilt in der
   Zeitzone der Lieferfenster.

Ab dieser Uhrzeit geht die E-Mail am Liefertag an jede Bestellung, deren
Fenster an diesem Tag beginnt, wenn die Bestellung prüfbereit, bestätigt oder
fakturiert ist, eine E-Mail-Adresse des Käufers enthält und auf der Tafel
**Auslieferung** noch nicht abgehakt ist. Das gilt für jede Herkunft, auch für
Bestellungen aus dem öffentlichen Formular. LeonAid prüft alle fünf Minuten;
die E-Mail kommt also bis zu fünf Minuten nach der gewählten Uhrzeit. Eine
Bestellung, die erst am Liefertag selbst dazukommt, bekommt die E-Mail beim
nächsten Durchlauf, solange ihr Fenster nicht vorbei ist.

Schaltest du den Schalter erst am Liefertag nach der gewählten Uhrzeit ein,
geht die E-Mail beim nächsten Durchlauf sofort an alle Bestellungen, deren
Fenster heute noch nicht zu Ende ist. Das trifft auch Bestellungen, die schon
ausgeliefert, aber auf der Tafel noch nicht abgehakt sind: Sie lesen „wird
heute geliefert“, obwohl die Lieferung schon da war. Dasselbe passiert, wenn
LeonAid am Morgen nicht lief und später wieder startet: Es holt alle noch
offenen Fenster des Tages nach, auch kurz vor deren Ende. Hake Lieferungen
deshalb ab, bevor du den Schalter am Liefertag einschaltest.

Keine E-Mail bekommen stornierte Bestellungen, Entwürfe, bereits abgehakte
Lieferungen, Bestellungen ohne E-Mail-Adresse und Fenster, die vor der
gewählten Uhrzeit enden. Bei einem solchen Fenster steht in der Bestellung
**Keine E-Mail: Das Lieferfenster endet vor der Versandzeit**. Ist die Aktion
abgeschlossen oder archiviert, geht keine Liefertags-E-Mail mehr hinaus. Jede
Bestellung bekommt die E-Mail für ihr Fenster einmal.

An dasselbe Postfach gehen höchstens zehn Bestell-E-Mails pro Stunde. Hat ein
Käufer am Liefertag mehr Bestellungen unter derselben Adresse (zum Beispiel
ein Mitglied, das für Kollegen bestellt hat), gehen die ersten zehn E-Mails
hinaus. Die übrigen Bestellungen zeigen die Zeile als **Fehlgeschlagen** mit
dem Hinweis auf das Postfach; sende sie später in der Bestellung mit
**Senden**. Ein Alarm entsteht dadurch nicht.

Konnte LeonAid eine E-Mail nicht senden, bevor ihr Fenster endete (Versand
gestört, LeonAid lief nicht), geht sie nicht mehr hinaus. Die Bestellung
zeigt die Zeile dann als **Fehlgeschlagen** mit dem Grund, auch wenn die
E-Mail nie angelegt wurde. In der Betriebsübersicht steht sie nicht bei den
fehlgeschlagenen Aufträgen, weil ein erneuter Versuch nichts mehr senden
würde. Für Fenster, die schon zu Ende waren, als du den Schalter
eingeschaltet hast, zeigt die Bestellung keinen Fehler.

Die E-Mail nennt für Rückfragen nur, was in der Rechtskonfiguration steht:
die E-Mail-Adresse des Clubs und, wenn eingetragen, die Telefonnummer des
Impressums.

Ob die E-Mail hinausging, zeigt der Abschnitt **E-Mails an den Käufer** in
der Bestellung (Zeile **Liefertags-E-Mail**). Dort kannst du sie am Liefertag
ab der gewählten Uhrzeit auch selbst senden oder erneut senden, bis das
Fenster endet oder die Lieferung abgehakt ist;
siehe [Bestellung stornieren](/de/user/how-to/cancel-order/#e-mails-einer-bestellung-ansehen-und-erneut-senden).
