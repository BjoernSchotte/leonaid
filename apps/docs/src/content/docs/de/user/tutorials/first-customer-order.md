---
title: Erste Kundenbestellung erfassen
description: Lernweg für Akquisiteure von einem zugeordneten Sponsor bis zur prüfbereiten Bestellung.
docId: DOC-P011
audience: [user]
diataxis: tutorial
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

In diesem Lernweg erfasst du als Akquisiteur eine synthetische Bestellung für
einen bereits zugeordneten Sponsor. Verwende eine Demo-Installation mit einer
aktiven Aktion, einem bestellbaren Angebot und – falls Lieferung aktiviert ist
– einem zukünftigen Lieferfenster.

## 1. Anmelden und Sponsor öffnen

1. Öffne `/login` deiner LeonAid-Installation.
2. Trage deine **Login-E-Mail** ein und wähle **Login-Code anfordern**.
3. Gib den **Sechsstelligen Code** aus der zuletzt versendeten E-Mail ein und
   wähle **Anmelden**.
4. Öffne **Meine Sponsoren** und beim synthetischen Sponsor die Aktion
   **Bestellung**.

LeonAid zeigt nur Sponsoren, die dir in dieser Charity-Aktion zugeordnet sind.
Der Sponsor ist im Bestellformular als **Zugeordneter Sponsor** ausgewählt.

## 2. Angebot und Rechnungsempfänger erfassen

1. Wähle unter **Angebot** einen aktuell bestellbaren Eintrag.
2. Trage eine **Menge** größer als null ein. Der angezeigte Gesamtbetrag dient
   zur Kontrolle; LeonAid berechnet den verbindlichen Preis beim Speichern neu.
3. Prüfe unter **Rechnungsempfänger** Name, **Straße und Hausnummer**, **PLZ**
   und **Ort**. Ergänze optional die **Rechnungs-E-Mail**.

Verwende ausschließlich synthetische Namen und Adressen. Der
Rechnungsempfänger wird als Snapshot in der Bestellung gespeichert.

## 3. Lieferangaben und Ergebnis

Ist die Lieferplanung aktiv, ergänze die Lieferadresse und wähle ein verfügbares
Fenster. Ein stillgelegtes oder inzwischen geändertes Fenster kann nicht für
eine neue verbindliche Bestellung verwendet werden.

Wähle **Prüfbereit erfassen**. Die Erfolgsseite zeigt **Bestellung
gespeichert**, **Bereit für die Prüfung**, den Besteller und den serverseitig
berechneten Gesamtbetrag. Der Charity-Admin findet den Vorgang danach unter
**Bestellungen** mit Status **Prüfbereit**.

Wenn Lieferangaben noch fehlen, speichere mit **Als Entwurf speichern**. Ergänze
sie später unter **Entwurf abschließen** und wähle **Entwurf prüfbereit
abschließen**.

Bei einer Fehlermeldung bleiben die Eingaben erhalten. Lade Angebote und
Sponsoren mit **Erneut versuchen** neu. Erscheint ein Berechtigungsfehler, öffne
einen dir zugeordneten Sponsor statt den Request zu wiederholen.
