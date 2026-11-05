---
title: Erste Kundenbestellung erfassen
description: Lernweg für Akquisiteure von einem zugeordneten Sponsor bis zur prüfbereiten Bestellung.
docId: DOC-P011
audience: [user]
diataxis: tutorial
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: 625bbfb87f7406f8811245356849f830b4321ab7
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

In diesem Lernweg erfasst du als Akquisiteur eine synthetische Bestellung für
einen bereits zugeordneten Sponsor. Verwende eine Demo-Installation mit einer
aktiven Aktion, einem bestellbaren Angebot und – falls Lieferung aktiviert ist
– einem zukünftigen Lieferfenster.

## 1. Anmelden und Sponsor öffnen

1. Öffne `/login` deiner LeonAid-Installation.
2. Trage deine **Login-E-Mail** ein und wähle **Login-Code anfordern**.
3. Gib unter **Sechsstelliger Code** den Code aus der zuletzt versendeten
   E-Mail ein und wähle **Anmelden**.
4. Wähle unten den Reiter **Sponsoren** und tippe auf den synthetischen
   Sponsor.
5. Wähle in der Sponsoransicht **Bestellung erfassen**.

LeonAid zeigt nur Sponsoren, die dir in dieser Charity-Aktion zugeordnet sind.
Die Bestellung heißt danach **Bestellung für …** mit dem Namen des Sponsors.

## 2. Angebot wählen

Die Bestellung hat drei Schritte: **Angebot**, **Lieferung** und **Prüfen**.

1. Wähle unter **Angebot** einen aktuell bestellbaren Eintrag.
2. Stelle die Anzahl mit **−** und **+** ein oder tippe sie ein. Die **Summe**
   dient zur Kontrolle; LeonAid berechnet den verbindlichen Preis beim Speichern
   erneut.
3. Wähle **Weiter**.

## 3. Lieferung und Rechnung erfassen

1. Ist die Lieferplanung aktiv, ergänze die Lieferadresse und wähle ein
   verfügbares Fenster. Ein stillgelegtes oder inzwischen geändertes Fenster
   kann nicht für eine neue verbindliche Bestellung verwendet werden.
2. Prüfe unter **Rechnung** Name, **Straße und Hausnummer**, **PLZ** und
   **Ort**. Ergänze optional die **Rechnungs-E-Mail**.
3. Wähle **Weiter**.

Verwende ausschließlich synthetische Namen und Adressen. Die Rechnungsanschrift
wird als Snapshot in der Bestellung gespeichert.

## 4. Prüfen und erfassen

Prüfe die Zusammenfassung und wähle **Verbindlich erfassen**. Die
Bestätigung zeigt **Bestellung erfasst**, Menge, Sponsor und den serverseitig
berechneten Betrag. Der Charity-Admin findet den Vorgang danach unter
**Bestellungen** mit Status **Prüfbereit**. Mit **Zurück zu …** kehrst du zum
Sponsor zurück.

Wenn Lieferangaben noch fehlen, wähle **Als Entwurf speichern**. Ergänze sie
später unter **Entwurf abschließen** und wähle **Entwurf prüfbereit
abschließen**.

Bei einer Fehlermeldung bleiben die Eingaben erhalten; mit **Zurück** kommst du
zu jedem Schritt. Erscheint ein Berechtigungsfehler, öffne einen dir
zugeordneten Sponsor statt den Vorgang zu wiederholen.
