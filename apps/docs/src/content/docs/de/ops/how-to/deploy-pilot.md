---
title: Eine Pilotinstallation bereitstellen
description: Eine manifestgebundene Staging- oder Produktionsinstallation ohne Build auf dem Zielsystem ausrollen.
docId: DOC-P022
audience: [ops]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

Lege für Staging und Produktion getrennte Domains, Compose-Projekte, Volumes,
Buckets, SMTP-Zugänge, Restic-Repositories und Secrets fest. Eine weitere
Organisation erhält eine weitere Installation.

1. Kopiere `infra/pilot/production.env.example` außerhalb des Repositorys.
   Die ausgefüllte Datei gehört dem Betriebsaccount und hat Modus `0600`.
2. Trage ausschließlich digest-gepinnte Images, den freigegebenen vollständigen
   `LEONAID_RELEASE_COMMIT` und ein externes Backupziel ein.
3. Erzeuge und prüfe die effektive Konfiguration mit `docker compose ... config
--format json`; verwende dabei `infra/compose/compose.yml` und
   `infra/pilot/compose.yml`.
4. Führe `./leonaid pilot-doctor --env-file ENV --backup-manifest MANIFEST
--gate pilot-deploy` aus. Exitcode 0 bedeutet technisch bereit, 1 einen
   Blocker, 2 offene Entscheidungen und 3 eine STOP-Entscheidung.
5. Rolle nur ein freigegebenes Release-Manifest aus:
   `./leonaid pilot-deploy --env-file ENV --backup-manifest BACKUP
--release-manifest RELEASE`.

Der Zielhost baut nicht und veröffentlicht nur Caddy auf 80/443. Für Produktion
muss derselbe Manifest-SHA zuvor in Staging verifiziert sein. Der reale Start
bleibt blockiert, solange DNS, vertrauenswürdiges TLS, Mail, Betreiberangaben,
Recovery-Ziel oder fachliche Entscheidungen offen sind.
