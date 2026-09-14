---
title: Die erste geprüfte Änderung
description: Einen frischen Checkout einrichten, eine kleine Änderung umsetzen und mit dem passenden Vertrag prüfen.
docId: DOC-P031
audience: [dev]
diataxis: tutorial
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

Du benötigst Git, Docker mit Compose v2 und mindestens 5 GiB freien Speicher.

1. Klone LeonAid in einen frischen Checkout und erstelle einen Arbeitsbranch.
2. Führe `./leonaid bootstrap` und anschließend `./leonaid doctor` aus.
3. Lies `PERSONAS.md`, die betroffene Domain-/UI-Implementierung und den
   nächstgelegenen ausführbaren Test. Verwende Specs und ADRs als Kontext.
4. Nimm eine kleine, zusammenhängende Änderung vor. Bei API-, Konfigurations-,
   Bedien- oder Betriebswirkung aktualisierst du die betroffenen Docs im selben
   Commitstand.
5. Führe zuerst den engsten relevanten `./leonaid test-…`-Befehl aus. Bei einer
   reinen Docs-Änderung sind das `./leonaid docs-check` und `docs-build`.
6. Führe vor der Übergabe `./leonaid check` in einem sauberen Arbeitsbaum aus.
7. Prüfe Diff, generierte Dateien, Secrets und unerwartete Änderungen.

`./leonaid test-handoff` wiederholt diesen Einstieg in einem frischen Checkout
und beweist, dass die dokumentierten Voraussetzungen vollständig sind. Ein
gezielter grüner Test ersetzt trotzdem nicht das für die konkrete Änderung
geforderte Gesamtgate.
