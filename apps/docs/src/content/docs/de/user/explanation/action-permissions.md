---
title: Rechte innerhalb einer Aktion
description: Warum LeonAid Navigation, Datensätze und Aktionen an globale und aktionsbezogene Rollen bindet.
docId: DOC-P019
audience: [user]
diataxis: explanation
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

LeonAid trennt globale Verantwortung von der Arbeit in einer einzelnen
Charity-Aktion. `system_admin`, `finance_reader` und `finance_manager` können
global wirken. `charity_admin`, `acquirer`, aktionsbezogenes
`finance_reader` und `driver` gehören immer zu einer konkreten Aktion.

Deshalb kann dieselbe Person in Aktion A Charity-Admin, in Aktion B
Akquisiteur und in Aktion C ohne Zugriff sein. Die Navigation wird aus der
aktuellen Identität abgeleitet. Eine ausgeblendete Schaltfläche ist nur die
sichtbare Folge; Core erzwingt die Grenze auch bei einem direkten API-Aufruf.

Datensichtbarkeit kann enger als die Aktionsrolle sein. Ein Akquisiteur sieht
innerhalb seiner Aktion nur zugeordnete CRM-Parteien. Eine Zuordnung gibt weder
Finanz- noch Administrationszugriff. Historische Aktivitäten, Bestellungen und
Belege bleiben nach Rollenentzug bestehen, während neue Requests die entzogene
Berechtigung sofort berücksichtigen.

Sensible Aktionen wie Rollenänderung oder Rechnungsfreigabe verlangen eine
frische Bestätigung der laufenden Sitzung. Das begrenzt den Schaden eines
unbeaufsichtigten angemeldeten Geräts, ohne für normale Arbeit bei jedem Schritt
einen neuen Login zu verlangen.
