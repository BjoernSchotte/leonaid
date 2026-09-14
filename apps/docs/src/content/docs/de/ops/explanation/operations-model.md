---
title: Betriebs- und Recovery-Modell
description: Wie Healthchecks, Wartung, Backup, Release und externe Abnahme zusammen die Betriebsgrenze bilden.
docId: DOC-P029
audience: [ops]
diataxis: explanation
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

Ein grüner Container-Healthcheck beweist Erreichbarkeit, aber keine erfolgreiche
Migration oder fachliche Integrität. LeonAid kombiniert deshalb technische
Readiness mit expliziten Migrationsbefehlen, Golden-Contracts und Browserwegen.
Der Pilot Doctor prüft zusätzlich die externe Umgebung und offene Entscheidungen.

Vor einer schemaändernden Veröffentlichung entsteht ein verschlüsselter,
integritätsgeprüfter Recovery Point. Der Wartungsmodus hält neue Schreibzugriffe
ab, während abhängige Systeme in definierter Reihenfolge migrieren. Nach einer
Schemaänderung führt der sichere Rückweg über einen Fresh-Volume-Restore statt
über ein älteres Image auf neuen Daten.

Produktion erhält nur einen SHA, der mit demselben Manifest in Staging geprüft
wurde. Konfiguration, Secrets, Domains, Buckets, SMTP und Backupziel bleiben
zwischen Staging und Produktion getrennt. Synthetische Tests belegen den
Mechanismus; Betreiber müssen DNS, TLS, Mailzustellung, Restore-Zeit und
fachliche Freigabe in der echten Umgebung zusätzlich nachweisen.
