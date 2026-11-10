---
title: Bestellung stornieren
description: Eine noch nicht gelieferte Bestellung mit Grund stornieren, samt offener Rechnung und Nachliefern-Aufgabe.
docId: DOC-P047
audience: [user]
diataxis: how-to
contentRevision: 5
reviewedRevision: 5
verifiedAgainst: 52718b176309716b363998e37aa2c91349cdbe8f
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** Charity-Admin der Aktion oder System-Admin, also dieselben Personen,
die die Bestellungen der Aktion verwalten. Akquisiteure, Ausfahrer und
Finanzrollen sehen die Funktion nicht; der Server lehnt sie für sie ab.

**Voraussetzung:** Die Bestellung ist noch nicht geliefert, und zu ihrer
Rechnung ist keine Zahlung erfasst (oder jede erfasste Zahlung ist
zurückgebucht).

1. Öffne im Backoffice **Bestellungen** und wähle die Bestellung. Der
   Detailbereich öffnet sich.
2. Wähle **Bestellung stornieren**.
3. Trage einen **Grund der Stornierung** ein, mindestens acht Zeichen. Er
   erscheint in der Historie der Bestellung und, falls eine Rechnung mit
   storniert wird, auch beim Storno der Rechnung.
4. Ergänze bei Bedarf eine **Notiz**. Sie ist nur intern sichtbar.
5. Bestätige mit **Stornieren**.

Danach trägt die Bestellung den Stempel **Storniert** und den Status
**Storniert**. Der Abschnitt **Storno** zeigt Grund, Notiz, wer storniert hat
und wann; der **Verlauf** nennt den Vorgang ebenfalls. Die Bestellung bleibt mit
allen Angaben in der Liste, ihr Betrag ist durchgestrichen. Mit dem Filter
**Status** › **Storniert** findest du alle stornierten Bestellungen. Summen von
Menge und Betrag zählen sie nicht mehr mit.

## Was sonst passiert

- **Lieferung:** Die Bestellung verschwindet sofort von der Tafel
  **Auslieferung** und zählt dort nicht mehr mit. War sie als **Nachliefern**
  markiert, wird ihre Aufgabe in der Liste **Nachliefern** erledigt. Die Aufgabe
  erhält einen Vermerk über das Storno, aber nicht den Grund: Sie enthält nie
  Namen oder Freitext aus der Bestellung.
- **Rechnung:** Gibt es noch keine Rechnung, passiert nichts weiter. Ist die
  Rechnung ausgestellt oder versendet und unbezahlt, nennt der Dialog sie mit
  ihrer Nummer. Sie wird zusammen mit der Bestellung storniert: Nummer, Daten
  und PDF bleiben unverändert erhalten, der Status wechselt auf **Storniert**.
  Weil dabei ein Beleg geändert wird, bestätigst du deine Anmeldung
  gegebenenfalls erneut. Grund und Notiz bleiben dabei erhalten; nach der
  Anmeldung öffnet sich der Dialog wieder, und du bestätigst noch einmal.
- **Besteller:** Der Dialog sagt vor dem Stornieren, ob der Besteller eine
  E-Mail bekommt. Kam die Bestellung über das öffentliche Bestellformular,
  erhält er kurz darauf die E-Mail **Stornierung Ihrer Bestellung bei …** an
  die Adresse aus dem Formular. Sie nennt Bestellnummer, Positionen, Betrag,
  eine mit stornierte Rechnung und die Kontaktdaten des Clubs aus den
  rechtlichen Angaben. Grund und Notiz stehen nicht darin; sie bleiben intern.
  Wiederholst du den Vorgang, geht keine zweite E-Mail hinaus.

  Für Bestellungen, die Mitglieder oder Akquisiteure erfasst haben, gilt
  dasselbe nur, wenn in der Aktion der Schalter **E-Mails für Bestellungen,
  die Mitglieder erfassen** an ist (siehe unten) und in der Bestellung eine
  E-Mail-Adresse des Käufers steht. Ein stornierter Entwurf sendet nichts.
  Sagt der Dialog, dass LeonAid nicht benachrichtigt, informiere den
  Besteller selbst.

## Wenn es nicht geht

- **Bereits geliefert:** Eine als geliefert abgehakte Bestellung lässt sich
  nicht stornieren. Der Dialog sagt das. Wurde der Haken versehentlich gesetzt,
  nimm ihn auf der Tafel **Auslieferung** zurück (siehe
  [Auslieferung abhaken](/de/user/how-to/work-delivery-board/)).
- **Zahlung erfasst:** Ist zur Rechnung eine Zahlung gebucht, auch eine
  Teilzahlung, bittet der Dialog, sie erst zurückzubuchen. Öffne die Rechnung
  unter **Rechnungen** und wähle bei der Zahlung **Zurückbuchen**. Sind alle
  Zahlungen zurückgebucht, kannst du die Bestellung stornieren. LeonAid bucht
  keine Erstattungen.
- **Inzwischen geändert:** Hat jemand die Bestellung gleichzeitig bearbeitet,
  lehnt der Server ab, und die Liste lädt neu. Prüfe den aktuellen Stand und
  storniere dann erneut; dein Grund bleibt im Dialog stehen.

Ein Storno ist endgültig. Eine stornierte Bestellung lässt sich nicht wieder
öffnen; erfasse bei Bedarf eine neue Bestellung.

## E-Mails für Bestellungen, die Mitglieder erfassen

Bestellungen aus dem öffentlichen Formular erhalten Bestellbestätigung und
Stornohinweis immer. Für Bestellungen aus der Akquise und aus der Verwaltung
schaltest du die E-Mails je Aktion ein:

1. Öffne im Backoffice **Aktionen**, wähle die Aktion und dann
   **Bearbeiten**.
2. Schalte im Abschnitt **E-Mails an Käufer** den Schalter **E-Mails für
   Bestellungen, die Mitglieder erfassen** ein. Der Schalter gilt sofort, auch
   während die Aktion läuft, und du kannst ihn jederzeit wieder ausschalten.

Ab dann erhält der Käufer die Bestellbestätigung, sobald seine Bestellung
prüfbereit ist: beim Erfassen, beim Abschließen eines Entwurfs oder wenn die
Verwaltung fehlende Angaben ergänzt. Das gilt auch für Bestellungen, die die
App offline gespeichert und später gesendet hat. Die E-Mail sagt, dass ein
Mitglied des Clubs die Bestellung erfasst hat. Jede Bestellung wird einmal
bestätigt; eine spätere Änderung von Adresse oder Lieferfenster sendet keine
zweite Bestätigung. Ohne E-Mail-Adresse des Käufers in der Bestellung geht
nichts hinaus, und Bestellungen, die vor dem Einschalten erfasst wurden,
werden nicht nachträglich bestätigt.

## E-Mails einer Bestellung ansehen und erneut senden

Der Detailbereich jeder Bestellung zeigt oben ihre **Bestellnummer**
(`LA-…`); jede Bestellung hat eine, egal wie sie erfasst wurde. Die Suche der
Liste findet die Bestellung auch über diese Nummer.

Der Abschnitt **E-Mails an den Käufer** zeigt je E-Mail eine Zeile:
**Bestellbestätigung**, bei Bestellungen mit Lieferfenster die
**Liefertags-E-Mail** (wenn die Aktion sie sendet, siehe
[Lieferfenster pflegen](/de/user/how-to/manage-delivery-windows/#e-mail-am-liefertag))
und, nach einem Storno, **Stornierung**. Der Stand ist
**Gesendet** mit Datum und Uhrzeit, **Wartet**, **Fehlgeschlagen**, **Nicht
gesendet** oder **Nicht fällig**; darunter steht der Grund, zum Beispiel dass
die Bestellung keine E-Mail-Adresse hat oder die E-Mails der Aktion
ausgeschaltet sind.

Hat der Käufer eine E-Mail nicht bekommen, wähle **Erneut senden**. Die
Schaltfläche gibt es für gesendete und fehlgeschlagene E-Mails. Sie fehlt,
solange die E-Mail wartet, wenn die Adresse fehlt, wenn die E-Mails der Aktion
ausgeschaltet sind und für die Bestätigung einer stornierten Bestellung. Die
Liefertags-E-Mail lässt sich nur am Liefertag erneut senden, bis das Fenster
endet oder die Lieferung abgehakt ist; vorher steht dort **Wird am Liefertag
gesendet**. An dasselbe Postfach gehen höchstens zehn Bestell-E-Mails pro Stunde; darüber
schlägt der Versand fehl, und du sendest später erneut.
