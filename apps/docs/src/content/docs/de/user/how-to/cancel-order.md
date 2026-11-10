---
title: Bestellung stornieren
description: Eine noch nicht gelieferte Bestellung mit Grund stornieren, samt offener Rechnung und Nachliefern-Aufgabe.
docId: DOC-P047
audience: [user]
diataxis: how-to
contentRevision: 4
reviewedRevision: 4
verifiedAgainst: 4a159bd74927862ccac28b97c64607b69e973980
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
  LeonAid stellt dazu eine **Stornorechnung** mit eigener Nummer aus. Du
  findest sie unter **Rechnungen** bei der Rechnung und kannst sie dort
  herunterladen und per E-Mail senden (siehe
  [Rechnung stornieren](/de/user/how-to/cancel-invoice/)). Wurde die Rechnung
  per E-Mail versendet, bietet der Dialog **Stornorechnung gleich senden** an;
  das Häkchen ist gesetzt. Die Stornorechnung geht dann an dieselbe Adresse,
  sobald sie erzeugt ist. Ohne Häkchen sendest du sie später bei der Rechnung.
  Weil dabei ein Beleg entsteht, bestätigst du deine Anmeldung
  gegebenenfalls erneut. Grund und Notiz bleiben dabei erhalten; nach der
  Anmeldung öffnet sich der Dialog wieder, und du bestätigst noch einmal.
- **Besteller:** Kam die Bestellung über das öffentliche Bestellformular,
  erhält der Besteller kurz darauf eine E-Mail **Stornierung Ihrer Bestellung
  bei …** an die Adresse aus dem Formular. Sie nennt Bestellnummer, Positionen,
  Betrag, eine mit stornierte Rechnung und die Kontaktdaten des Clubs aus den
  rechtlichen Angaben. Grund und Notiz stehen nicht darin; sie bleiben intern.
  Wiederholst du den Vorgang, geht keine zweite E-Mail hinaus. Bestellungen, die
  Mitglieder oder Akquisiteure erfasst haben, lösen keine E-Mail aus: Informiere
  diese Besteller selbst.

## Wenn es nicht geht

- **Bereits geliefert:** Eine als geliefert abgehakte Bestellung lässt sich
  nicht stornieren. Der Dialog sagt das. Wurde der Haken versehentlich gesetzt,
  nimm ihn auf der Tafel **Auslieferung** zurück (siehe
  [Auslieferung abhaken](/de/user/how-to/work-delivery-board/)).
- **Zahlung erfasst:** Ist zur Rechnung eine Zahlung gebucht, auch eine
  Teilzahlung, bittet der Dialog, sie erst zurückzubuchen. Öffne die Rechnung
  unter **Rechnungen** und wähle bei der Zahlung **Zurückbuchen**. Sind alle
  Zahlungen zurückgebucht, kannst du die Bestellung stornieren. LeonAid bucht
  keine Erstattungen. Hat der Sponsor wirklich gezahlt und soll die Zahlung
  erfasst bleiben, storniere zuerst die Rechnung: Das geht auch mit Zahlung,
  und LeonAid merkt die offene Erstattung vor (siehe
  [Rechnung stornieren](/de/user/how-to/cancel-invoice/)). Danach lässt sich
  auch die Bestellung stornieren.
- **Inzwischen geändert:** Hat jemand die Bestellung gleichzeitig bearbeitet,
  lehnt der Server ab, und die Liste lädt neu. Prüfe den aktuellen Stand und
  storniere dann erneut; dein Grund bleibt im Dialog stehen.

Ein Storno ist endgültig. Eine stornierte Bestellung lässt sich nicht wieder
öffnen; erfasse bei Bedarf eine neue Bestellung.
