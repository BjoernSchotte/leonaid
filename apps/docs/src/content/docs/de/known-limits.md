---
title: Bekannte Grenzen
description: Belegte Grenzen des aktuellen LeonAid-Entwicklungs- und Pilotstands.
docId: DOC-P003
audience: [user, ops, dev]
diataxis: reference
contentRevision: 5
reviewedRevision: 5
verifiedAgainst: 68fe0e63b592a739925654788509e63a71b01e8a
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

Diese Dokumentation beschreibt den aktuellen Entwicklungsstand. Sie ist keine
allgemeine Produktionsfreigabe.

- Die Produktoberfläche und die von ihr versendeten Texte sind derzeit
  deutschsprachig. Die englische Dokumentation nennt deutsche UI-Labels
  wörtlich.
- Eine Installation bildet einen Club beziehungsweise einen getrennten
  Mandanten ab. Gemeinsamer Mehrmandantenbetrieb ist nicht vorgesehen.
- Ausfahrer haken ihre zugewiesenen Lieferungen in der App ab (siehe
  [Auslieferung abhaken](/de/user/how-to/work-delivery-board/)). Routen- und
  Tourenplanung gehört nicht zum aktuellen Funktionsumfang.
- `finance_reader` darf Belege nur lesen. Der gepflegte Demo-Benutzer Finn
  Finanzen beweist genau diesen Lesezugriff. Zahlungen und Storno benötigen
  `finance_manager` oder den Charity-Admin der betroffenen Aktion.
- Mitglieder können ihre Login-E-Mail nicht selbst ändern. Ein System-Admin
  stößt den Wechsel an; die neue Adresse muss ihn bestätigen.
- Öffentliche Bestellungen sind nur für eine veröffentlichte Aktion mit
  aktivem Bestellformular und verfügbarem Angebot möglich. Bei aktivierter
  Lieferplanung ist außerdem ein verfügbares Lieferfenster nötig.
- Ein gespeicherter Rechnungsbeleg und sein PDF werden nicht nachträglich
  überschrieben. Korrekturen erfolgen durch Storno und einen neuen Vorgang.
- Teil- und Überzahlungen werden als einzelne Zahlungseinträge erfasst und
  bei Bedarf begründet zurückgebucht. Eine Überzahlung wird nur angezeigt; die
  Erstattung läuft außerhalb von LeonAid. Bankabgleich und Mahnwesen fehlen.
- Listmonk (Compose-Profil `mailing`) gehört nicht zum produktiven
  Pilot-Stack. Dort hat es weder öffentliche Route noch Backup noch
  Monitoring; alle drei müssen vor dem Aktivieren des Profils existieren.
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
