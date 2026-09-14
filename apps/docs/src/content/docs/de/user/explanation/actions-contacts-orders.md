---
title: Aktion, Kontakt und Bestellung
description: Wie LeonAid Kampagnen, CRM-Parteien, Zuständigkeiten und verbindliche Bestellungen verbindet.
docId: DOC-P018
audience: [user]
diataxis: explanation
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

Eine **Charity-Aktion** gibt Zeitraum, Zweck, Angebote, Ziel, Veröffentlichung
und Rollenrahmen vor. Sie ist die Grenze, innerhalb der LeonAid
Zuständigkeiten und Finanzvorgänge autorisiert.

Eine Firma oder Person ist eine **CRM-Partei** in Twenty. LeonAid Core speichert
dazu die aktionsbezogene Akquisezuordnung: wer zuständig ist, welcher Status,
welche Wiedervorlage und welche Aktivitäten zur Aktion gehören. Mehrere
Akquisiteure können dieselbe Partei gemeinsam betreuen, ohne den CRM-Datensatz
zu duplizieren.

Eine **Bestellung** ist in Core ein `Commitment`. Sie speichert die Quelle,
serverseitig bewertete Positionen, einen Rechnungsempfänger und gegebenenfalls
Lieferadresse, Kontakt und gebuchtes Lieferfenster. Öffentliche Formulare können
eine CRM-Partei anlegen oder wiederverwenden; die verbindliche Bestellung bleibt
trotzdem ein Core-Datensatz.

Wird daraus eine Rechnung freigegeben, entsteht ein unveränderlicher Snapshot
von Empfänger, Aussteller, Positionen, Preisen, Zahlungsdaten und Rechtstext.
Spätere Änderungen am CRM-Kontakt oder an einem Lieferfenster schreiben diesen
historischen Beleg nicht um. Diese Trennung erhält Nachvollziehbarkeit und
erklärt, warum eine Korrektur als eigener Vorgang erfolgt.
