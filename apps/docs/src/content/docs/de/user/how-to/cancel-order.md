---
title: Bestellung stornieren
description: Eine noch nicht gelieferte Bestellung mit Grund stornieren, samt offener Rechnung und Nachliefern-Aufgabe.
docId: DOC-P047
audience: [user]
diataxis: how-to
contentRevision: 5
reviewedRevision: 5
verifiedAgainst: 1f49427206df2ee9224ad2fb21c80e3f2241649b
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
nichts hinaus.

Die E-Mail geht an die Adresse, die beim Sponsor im CRM steht. Das
Erfassungsformular der Akquise-App und das Formular **Angaben ergänzen**
zeigen diese Adresse vor dem Speichern an und nennen die E-Mails, die
dorthin gehen. Kläre mit dem Käufer, ob sie stimmt.

Eine Bestätigung, die zu spät käme, sendet LeonAid nicht: nicht nach der
abgehakten Lieferung, nicht nach dem Ende des Lieferfensters und nicht mehr,
wenn die Aktion abgeschlossen ist. Wer also eine Bestellung erst nachträglich
erfasst oder abschließt, löst keine Bestätigung aus.

Bestellungen, die vor dem Einschalten erfasst wurden, bestätigt LeonAid nicht
von selbst. Du kannst die Bestätigung in der Bestellung einzeln senden (siehe
unten).

Die Datenschutzerklärung des Clubs muss diese E-Mails nennen. Ein
System-Admin pflegt sie unter **Rechtliches**; die Vorlage enthält dafür den
Abschnitt **Bestellungen, die ein Mitglied für Sie erfasst**. LeonAid prüft
nicht, ob der Abschnitt in der aktiven Fassung steht.

## E-Mails einer Bestellung ansehen und erneut senden

Der Detailbereich jeder Bestellung zeigt oben ihre **Bestellnummer**; jede
Bestellung hat eine, egal wie sie erfasst wurde. Sie besteht aus `LA-` und
acht Zeichen, zum Beispiel `LA-7F3K2QWX`, ohne die leicht verwechselbaren
Zeichen 0, O, 1, I und L, damit ein Käufer sie am Telefon nennen kann.
Öffentliche Bestellungen von vor dieser Umstellung behalten ihre lange Nummer
(`LA-` und 32 Zeichen). Die Suche der Liste findet die Bestellung über beide.

Der Abschnitt **E-Mails an den Käufer** zeigt je E-Mail eine Zeile:
**Bestellbestätigung** und, nach einem Storno, **Stornierung**. Der Stand ist
**Gesendet** mit Datum und Uhrzeit, **Wartet**, **Fehlgeschlagen**, **Nicht
gesendet** oder **Nicht fällig**; darunter steht der Grund, zum Beispiel dass
die Bestellung keine E-Mail-Adresse hat, die E-Mails der Aktion
ausgeschaltet sind, die Lieferung schon erfasst ist, das Lieferfenster vorbei
ist oder die Aktion abgeschlossen ist.

Hat der Käufer eine E-Mail nicht bekommen, wähle **Erneut senden**. Ist eine
fällige E-Mail noch nie hinausgegangen, heißt die Schaltfläche **Senden**:
zum Beispiel bei einer Bestellung von vor dem Einschalten. Die Schaltfläche
gibt es immer dann, wenn die E-Mail jetzt fällig ist und keine wartet. Sie
fehlt, solange die E-Mail wartet, und immer, wenn LeonAid die E-Mail auch von
selbst nicht senden würde: ohne Adresse, bei ausgeschalteten E-Mails, für
einen Entwurf und für die Bestätigung einer stornierten, gelieferten oder
abgelaufenen Bestellung. Die Bestätigung nennt beim erneuten Senden den
heutigen Stand der Bestellung, nicht den von damals. An dasselbe Postfach
gehen höchstens zehn Bestell-E-Mails pro Stunde; darüber schlägt der Versand
fehl, und du sendest später erneut. Meldet LeonAid nach einem Klick, der
Auftrag von vorhin sei angekommen, ging keine weitere E-Mail hinaus.
