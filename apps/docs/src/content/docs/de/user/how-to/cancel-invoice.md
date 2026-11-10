---
title: Rechnung stornieren
description: Eine Rechnung stornieren, die Stornorechnung finden und senden und eine Erstattung als erledigt vermerken.
docId: DOC-P053
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: dd69fcf4fed541649862cc2ed3c869415a3813d6
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** Charity-Admin der betroffenen Aktion oder globaler
`finance_manager`. Senden kann nur der Charity-Admin der Aktion.
`finance_reader` sieht Storno und Stornorechnung, kann aber nichts ändern.

Ein Storno hebt die Rechnung vollständig auf. LeonAid stellt dabei im selben
Schritt eine **Stornorechnung** aus. Ein Teilstorno gibt es nicht. Zu einer
Bestellung gibt es nur eine Rechnung: Für eine Korrektur erfasst du nach dem
Storno eine neue Bestellung und stellst deren Rechnung aus.

## Rechnung stornieren

1. Öffne im Backoffice **Rechnungen** und wähle die Rechnung. Der
   Detailbereich öffnet sich.
2. Wähle **Stornieren**.
3. Trage den **Grund der Stornierung** ein, mindestens acht Zeichen. Er bleibt
   intern: Er steht im Abschnitt **Storno** der Rechnung, aber nicht auf der
   Stornorechnung.
4. Wurde die Rechnung per E-Mail versendet, bietet der Dialog
   **Stornorechnung gleich senden** an. Das Häkchen ist gesetzt. Die
   Stornorechnung geht dann als PDF an die Adresse, an die auch die Rechnung
   ging, sobald sie erzeugt ist. Nimm das Häkchen heraus, wenn du sie später
   oder gar nicht senden willst.
5. Bestätige mit **Stornieren**. Weil dabei ein Beleg entsteht, bestätigst du
   deine Anmeldung gegebenenfalls erneut.

Die Meldung nennt die Nummer der Stornorechnung, zum Beispiel
**KT26-0017 storniert. Stornorechnung KT26-0042 ausgestellt.**

## Was dabei entsteht

- **Die Rechnung** bleibt mit Nummer, Daten und PDF unverändert erhalten. Ihr
  Status wechselt auf **Storniert**. Die Liste zeigt bei ihr
  **storniert · Stornorechnung** und die Nummer.
- **Die Stornorechnung** ist ein eigener Beleg. Sie erhält die nächste Nummer
  aus dem Nummernkreis der Rechnungen und das Datum des Stornos. Sie nennt
  Nummer und Datum der aufgehobenen Rechnung und weist deren Positionen und
  Beträge mit umgekehrtem Vorzeichen aus.
- **Der Nummernkreis** gilt für die ganze Installation, nicht je Aktion.
  Rechnungen und Stornorechnungen aller Aktionen mit demselben Präfix stehen in
  einer gemeinsamen, lückenlosen Reihe.

Der Abschnitt **Stornorechnung** im Detailbereich der Rechnung zeigt Nummer und
Datum. Darunter steht das PDF: Es wird kurz nach dem Storno erzeugt und lässt
sich dann ansehen und herunterladen.

## Stornorechnung senden

Hast du die Stornorechnung nicht gleich mitgesendet, wähle im Bereich
**Versand der Stornorechnung** die Schaltfläche **Stornorechnung senden**. Das
geht, sobald das PDF bereitsteht. Der Bereich zeigt danach, ob die E-Mail
zugestellt wurde. Ein fehlgeschlagener Versand lässt sich dort erneut starten.
Mit **Erneut senden** schickst du dieselbe Stornorechnung bewusst noch einmal.

Die E-Mail geht an die E-Mail-Adresse des Rechnungsempfängers. Ist dort keine
Adresse gespeichert, kann LeonAid die Stornorechnung nicht senden: Lade das PDF
herunter und gib es auf anderem Weg weiter.

## Wenn Geld eingegangen war

Du kannst auch eine bezahlte oder teilweise bezahlte Rechnung stornieren. Der
Dialog nennt dann den eingegangenen Betrag.

- Die Zahlung bleibt erfasst. Bei einer stornierten Rechnung lässt sie sich
  nicht mehr zurückbuchen.
- Die Stornorechnung nennt den erhaltenen Betrag und den Satz
  „Die Erstattung erfolgt gesondert.“.
- LeonAid bucht keine Erstattung. Du überweist den Betrag außerhalb von LeonAid
  zurück.
- Bis dahin zeigt die Rechnung in der Liste und im Detailbereich
  **Erstattung offen**. Der Filter **Erstattung** findet alle Rechnungen mit
  offener Erstattung.

Ist das Geld zurücküberwiesen:

1. Öffne die Rechnung und wähle **Erstattung erledigt**.
2. Trage unter **Erstattet am** den Tag der Überweisung ein. Er liegt zwischen
   dem Tag des Stornos und heute.
3. Ergänze bei Bedarf eine **Notiz**.
4. Bestätige mit **Erstattung erledigt**.

Der Vermerk schließt nur die Erinnerung. Er lässt sich nicht ändern oder
zurücknehmen. Der Abschnitt **Stornorechnung** zeigt danach
**Erstattung erledigt am** mit Datum und Person.

Die Bestellung bleibt beim Storno der Rechnung bestehen. Soll auch sie
entfallen, storniere sie danach (siehe
[Bestellung stornieren](/de/user/how-to/cancel-order/)). Umgekehrt geht es
nicht: Eine Bestellung, zu deren offener Rechnung eine Zahlung erfasst ist,
lässt sich nicht stornieren. Storniere dann zuerst die Rechnung.

## Ältere Stornos

Rechnungen, die storniert wurden, bevor LeonAid Stornorechnungen ausgestellt
hat, haben keine Stornorechnung. LeonAid erfindet sie nicht nachträglich. Der
Abschnitt **Stornorechnung** sagt das und bietet **Stornorechnung ausstellen**
an. Die Stornorechnung erhält dann die nächste Nummer und das heutige Datum,
nicht das Datum des damaligen Stornos. Auch hier bestätigst du deine Anmeldung
gegebenenfalls erneut.

## Wenn es nicht geht

- **Keine Schaltfläche:** Dein Konto hat nur Lesezugriff, oder die Rechnung ist
  bereits storniert.
- **Rechnungsprofil fehlt:** Die Stornorechnung braucht den Nummernkreis der
  Aktion. Fehlt das Rechnungsprofil, muss ein System-Admin zuerst die
  rechtlichen Angaben aktivieren.
- **Stornorechnung gleich senden schlägt fehl:** Fehlt die E-Mail-Adresse des
  Empfängers, lehnt der Server den ganzen Schritt ab. Storniere ohne das
  Häkchen.
- **Versand noch nicht möglich:** Das PDF wird gerade erzeugt. Versuche es
  kurz darauf erneut.

Ein Storno ist endgültig. Eine stornierte Rechnung lässt sich nicht wieder
öffnen, und eine Stornorechnung lässt sich nicht ändern oder löschen.
