---
title: Bestellung stornieren
description: Eine noch nicht gelieferte Bestellung mit Grund stornieren, samt offener Rechnung und Nachliefern-Aufgabe.
docId: DOC-P047
audience: [user]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 05e19df19f872cc5137477166450e97438ff8348
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
- **Besteller:** LeonAid benachrichtigt den Besteller nicht automatisch.
  Informiere ihn selbst über die Stornierung.

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
