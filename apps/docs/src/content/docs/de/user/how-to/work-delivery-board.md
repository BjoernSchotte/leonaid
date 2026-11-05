---
title: Auslieferung abhaken
description: Am Liefertag Ausfahrer zuweisen, Lieferungen abhaken, Fenster abschließen und Nicht-Geliefertes nachliefern.
docId: DOC-P046
audience: [user]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: a255af208a20325a525d9fa2f88f6e5642ad5c73
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** Charity-Admin der Aktion für die Tafel, Ausfahrer für die eigenen
Lieferungen in der App. Die Seite **Auslieferung** gibt es nur, wenn eine Aktion,
die du verwaltest, die Funktion **Auslieferung** hat und ihre Lieferplanung
aktiv ist (siehe [Lieferfenster pflegen](/de/user/how-to/manage-delivery-windows/)).

## Tafel vorbereiten

1. Öffne im Backoffice **Auslieferung** und wähle oben die Aktion. Die Tafel
   zeigt den Liefertag mit allen Fenstern; mit **Liefertag** wechselst du den
   Tag.
2. Haben Lieferungen noch keinen Fahrer, bietet der Block **Nächster Schritt**
   **Fahrer zuweisen** an. Wähle einen Ausfahrer für alle Lieferungen ohne
   Fahrer. Einzelne Lieferungen änderst du über das Fahrer-Symbol am
   Zeilenende, ein ganzes Fenster über **Fahrer für alle**.
3. Hat die Aktion noch keine Ausfahrer, zeigt **Nächster Schritt** **Ausfahrer
   einladen**. Lade dort jemanden mit der Rolle **Ausfahrer** ein.

Ein offenes Fenster, das im Reiter **Lieferfenster** als ausgebucht markiert
ist, trägt im Kopf den Hinweis **Ausgebucht**; Ausfahrer sehen ihn nicht.

Ausfahrer sehen nur die Lieferungen, die ihnen zugewiesen sind. Mit
**Fahrdienst** filterst du die Tafel nach Fahrer oder **Ohne Fahrer**.

## Lieferungen abhaken

1. Wähle den runden Haken vor einer Lieferung. Die Meldung **…: geliefert.**
   bietet **Rückgängig** an.
2. Mit der Tastatur bewegst du dich mit **J** und **K** und hakst mit **D** ab.

Solange das Fenster offen ist, kannst du jeden Haken zurücknehmen. Stornierte
Bestellungen bleiben durchgestrichen sichtbar, lassen sich aber nicht abhaken
und zählen nicht mit.

## Fenster abschließen

1. Wähle beim Fenster **Fenster abschließen**. Ist ein vergangenes Fenster
   vollständig geliefert, bietet **Nächster Schritt** das ebenfalls an.
2. Der Dialog nennt die Lieferungen, die noch nicht abgehakt sind. Bestätige mit
   **Mit … offenen abschließen** oder **Abschließen**.

Offene Lieferungen werden dabei als **Nachliefern** markiert. Ist das Modul
**Aufgaben** aktiv, legt LeonAid für jede eine Aufgabe in deiner Liste
**Nachliefern** an. Die Aufgabe nennt nur die Bestellnummer, das Fenster und
einen Link zur Bestellung, keine Namen oder Adressen. Ohne Aufgaben bleiben die
Lieferungen mit dem Hinweis **Nachliefern** auf der Tafel.

## Nach dem Abschluss

- **Nachliefern:** Hake eine als **Nachliefern** markierte Lieferung ab, sobald
  sie doch angekommen ist. Die Aufgabe wird damit erledigt. Diesen Haken kannst
  du zurücknehmen; die Aufgabe ist dann wieder offen.
- **Später gebucht:** Wurde eine Bestellung nach dem Abschluss in das Fenster
  gebucht, trägt sie den Hinweis **nach Abschluss gebucht**, und **Nächster
  Schritt** erinnert mit **Zur Lieferung** daran. Eine Aufgabe entsteht dafür
  nicht. Hake sie nach der Lieferung ab; das wird protokolliert und lässt sich
  ohne erneutes Öffnen nicht zurücknehmen. Wird sie nicht geliefert, öffne das
  Fenster wieder und schließe es erneut ab: Dann zählt sie als
  **Nachliefern**.
- **Korrigieren:** Andere Haken in einem abgeschlossenen Fenster änderst du nur
  nach **Wieder öffnen**. Dabei werden Nachliefern-Markierungen aufgehoben und
  ihre Aufgaben erledigt. Schließt du erneut ab, öffnet LeonAid dieselben
  Aufgaben wieder und weist sie dir zu, ohne Duplikate.

## In der App (Ausfahrer)

1. Öffne in der App **Auslieferung**. Du siehst nur deine Lieferungen mit
   Adresse und Kontakt, ohne Beträge. Fährst du für mehrere Aktionen, wählst du
   oben die **Aktion**.
2. Hake ab, was angekommen ist. Solange das Fenster offen ist, kannst du den
   Haken zurücknehmen.

Ist das Fenster abgeschlossen, kannst du nichts mehr ändern; wende dich dann an
die Aktionsleitung. Ohne Verbindung zeigt die App keine Lieferungen und behält
keine Adressen auf dem Gerät. Sobald du wieder online bist, lädt die Tafel neu.
