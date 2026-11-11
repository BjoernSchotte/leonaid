---
title: Betriebs- und Recovery-Modell
description: Wie Healthchecks, Wartung, Backup, Release und externe Abnahme zusammen die Betriebsgrenze bilden.
docId: DOC-P029
audience: [ops]
diataxis: explanation
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

Ein grüner Container-Healthcheck beweist Erreichbarkeit, aber keine erfolgreiche
Migration oder fachliche Integrität. LeonAid kombiniert deshalb technische
Readiness mit expliziten Migrationsbefehlen, Golden-Contracts und Browserwegen.
Der Pilot Doctor prüft zusätzlich die externe Umgebung und offene Entscheidungen.

Die API ist bereit, wenn PostgreSQL und der Objektspeicher antworten. Twenty
(CRM) gehört nur dann dazu, wenn `TWENTY_INTEGRATION_API_KEY` gesetzt ist; ohne
Schlüssel sind die CRM-Funktionen aus. Produktion braucht den Schlüssel: Fehlt
er, scheitert der Pilot Doctor, statt eine Installation ohne CRM als bereit zu
melden.

Vor einer schemaändernden Veröffentlichung entsteht ein verschlüsselter,
integritätsgeprüfter Recovery Point. Der Wartungsmodus hält neue Schreibzugriffe
ab, während abhängige Systeme in definierter Reihenfolge migrieren. Nach einer
Schemaänderung führt der sichere Rückweg über einen Fresh-Volume-Restore statt
über ein älteres Image auf neuen Daten.

Ein Upgrade ist ein Befehl, wie bei anderen selbst betriebenen Projekten: Er
prüft, ob die Version die installierte Datenbank lesen kann, sichert, migriert
und prüft den Zustand. Staging ist freiwillig: Spiele eine Produktionssicherung
auf einem Staging-Host ein und führe dort zuerst dasselbe Upgrade aus.
Konfiguration, Secrets, Domains, Buckets, SMTP und Backupziel bleiben zwischen
Staging und Produktion getrennt. Synthetische Tests belegen den
Mechanismus; Betreiber müssen DNS, TLS, Mailzustellung, Restore-Zeit und
fachliche Freigabe in der echten Umgebung zusätzlich nachweisen.
