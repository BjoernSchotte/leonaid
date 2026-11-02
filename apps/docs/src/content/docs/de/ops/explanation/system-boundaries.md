---
title: System- und Persistenzgrenzen
description: Warum LeonAid Core, Twenty, RustFS und die Oberflächen getrennte Verantwortungen besitzen.
docId: DOC-P028
audience: [ops]
diataxis: explanation
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 6d3891e2a7f6497307f1cd2927bb6efe1b4b97aa
reviewer: Björn Schotte
---

LeonAid Core besitzt Identitäten, Aktionsmitgliedschaften, Charity-Aktionen,
Zuordnungen, Aktivitäten, Bestellungen, Rechnungen, Zahlungen, Audit und
Outbox. Twenty besitzt Firmen und Personen. Core referenziert stabile
Twenty-IDs und speichert Snapshots, wenn spätere CRM-Änderungen die Historie
nicht verändern dürfen.

RustFS speichert nur Dokumentbytes; Core hält Object-Key, Version, SHA-256,
Größe und Fachreferenz. Rechnungsnummer, Rechnungssnapshot und Outbox-Ereignis
entstehen in einer Core-Transaktion. Rendering und Versand folgen idempotent.
Browser und Astro Actions besitzen keine führende Fachlogik.

Diese Grenzen erklären den Backupumfang: Beide PostgreSQL-Datenbanken,
Twenty-Dateien und RustFS müssen denselben Recovery Point bilden. Der
Valkey-Queue-Speicher (`twenty-redis`) ist wiederaufbaubar. Eine Installation bildet genau einen Club oder Träger ab;
weitere Organisationen werden durch getrennte Installationen isoliert.
