---
title: Bekannte Grenzen
description: Belegte Grenzen des aktuellen LeonAid-Entwicklungs- und Pilotstands.
docId: DOC-P003
audience: [user, ops, dev]
diataxis: reference
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

Diese Dokumentation beschreibt den aktuellen Entwicklungsstand. Sie ist keine
allgemeine Produktionsfreigabe.

- Die Produktoberfläche und die von ihr versendeten Texte sind derzeit
  deutschsprachig. Die englische Dokumentation nennt deutsche UI-Labels
  wörtlich.
- Eine Installation bildet einen Club beziehungsweise einen getrennten
  Mandanten ab. Gemeinsamer Mehrmandantenbetrieb ist nicht vorgesehen.
- Der Ausfahrer-Workflow ist zurückgestellt. Lieferadressen und Lieferfenster
  werden gespeichert; eine Fahrer-App mit Touren und Zustellstatus gehört nicht
  zum aktuellen Funktionsumfang.
- `finance_reader` darf Belege nur lesen. Der gepflegte Demo-Benutzer Finn
  Finanzen beweist genau diesen Lesezugriff. Vollzahlung und Storno benötigen
  `finance_manager` oder den Charity-Admin der betroffenen Aktion.
- Mitglieder können ihre Login-E-Mail nicht selbst ändern. Ein System-Admin
  stößt den Wechsel an; die neue Adresse muss ihn bestätigen.
- Öffentliche Bestellungen sind nur für eine veröffentlichte Aktion mit
  aktivem Bestellformular und verfügbarem Angebot möglich. Bei aktivierter
  Lieferplanung ist außerdem ein verfügbares Lieferfenster nötig.
- Ein gespeicherter Rechnungsbeleg und sein PDF werden nicht nachträglich
  überschrieben. Korrekturen erfolgen durch Storno und einen neuen Vorgang.
- Teil- und Überzahlungen sind nicht implementiert; die Buchung akzeptiert nur
  den exakten vollständigen Rechnungsbetrag.
- Die getrennte Dokumentationswebsite wird als statische GitHub-Pages-Site aus
  dem geprüften Artefakt veröffentlicht. Bis zur öffentlichen Abnahme sind die
  versionierten Quellen und CI-Artefakte der belastbare Zugang.

## Hinweise zur Dokumentationswebsite

Björn Schotte pflegt die Website über das öffentliche
[LeonAid-Repository](https://github.com/BjoernSchotte/leonaid). Fehler können
dort als Issue gemeldet werden. Die statische Site setzt keine eigene Analyse
ein und benötigt keine Anmeldung. GitHub verarbeitet beim Hosting technische
Zugriffsdaten nach seiner
[Datenschutzerklärung](https://docs.github.com/de/site-policy/privacy-policies/github-general-privacy-statement).

Für LeonAid ist noch keine Open-Source-Lizenz gewählt. Die Dokumentation ändert
diesen Status nicht; Lizenzen eingebundener Komponenten gelten unabhängig.

Melde eine Abweichung mit dem betroffenen Produktpfad, der sichtbaren Meldung
und dem verwendeten Commit. Die Implementierung bleibt die Wahrheitsquelle.
