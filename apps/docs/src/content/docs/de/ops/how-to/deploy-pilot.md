---
title: Eine Pilotinstallation bereitstellen
description: Eine manifestgebundene Staging- oder Produktionsinstallation ohne Build auf dem Zielsystem ausrollen.
docId: DOC-P022
audience: [ops]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 86b4e396de4569cbc7dbd03cdb2153a8698bb0d1
reviewer: Björn Schotte
---

Lege für Staging und Produktion getrennte Domains, Compose-Projekte, Volumes,
Buckets, SMTP-Zugänge, Restic-Repositories und Secrets fest. Eine weitere
Organisation erhält eine weitere Installation.

1. Kopiere `infra/pilot/production.env.example` außerhalb des Repositorys.
   Die ausgefüllte Datei gehört dem Betriebsaccount und hat Modus `0600`.
2. Übernimm die Zeilen aus `release-images.env` des freigegebenen
   GitHub-Releases (siehe [Eine Version releasen](/de/ops/how-to/release-a-version/)):
   Version, vollständiger `LEONAID_RELEASE_COMMIT` und Images mit Tag und
   Digest. Ergänze ein externes Backupziel.
3. Erzeuge und prüfe die effektive Konfiguration mit `docker compose ... config
--format json`; verwende dabei `infra/compose/compose.yml` und
   `infra/pilot/compose.yml`.
4. Führe `./leonaid pilot-doctor --env-file ENV --backup-manifest MANIFEST
--gate pilot-deploy` aus. Exitcode 0 bedeutet technisch bereit, 1 einen
   Blocker, 2 offene Entscheidungen und 3 eine STOP-Entscheidung.
5. Rolle nur ein freigegebenes Release-Manifest aus:
   `./leonaid pilot-deploy --env-file ENV --backup-manifest BACKUP
--release-manifest RELEASE`.

Der Zielhost baut nicht und veröffentlicht nur Caddy auf 80/443. Staging ist
freiwillig und darf auf einem anderen Host laufen, etwa als VM im eigenen Netz
des Vereins. Eine Staging-Installation wartet auf keine Entscheidung im
Register. Der reale Produktionsstart bleibt blockiert, solange DNS,
vertrauenswürdiges TLS, Mail, Betreiberangaben, Recovery-Ziel oder fachliche
Entscheidungen offen sind.

## Staging hinter einem Proxy und ohne SMTP-Zugang

Zwei Optionen erleichtern eine Staging-VM im eigenen Netz des Vereins. Der
Doctor lehnt beide ab, wenn `LEONAID_DEPLOYMENT_STAGE=production` gilt.

- **`LEONAID_EDGE_TLS=true`:** Ein Reverse Proxy oder Tunnel vor dem Server
  (zum Beispiel Pangolin oder Cloudflare Tunnel) hält das öffentliche
  Zertifikat und Port 80. Caddy nutzt dann seine interne CA. Der Proxy
  leitet HTTPS auf Port 443 des Servers weiter, mit dem öffentlichen
  Hostnamen als TLS-Servername (SNI). Der Doctor prüft das öffentliche
  Zertifikat über den Proxy und lässt die Prüfung von Port 80 aus. Zum
  Abschalten den Schlüssel weglassen; `false` wird abgelehnt.
- **`LEONAID_STAGING_MAILPIT=true`:** Mailpit spielt im Stack das SMTP-Relay.
  Keine Mail verlässt den Server. Setze diese Schlüssel:

  ```sh
  LEONAID_STAGING_MAILPIT=true
  LEONAID_STAGING_MAILPIT_UI_AUTH=operator:<Passwort, mindestens 16 Zeichen>
  MAIL_SMTP_HOST=mailpit
  MAIL_SMTP_PORT=465
  MAIL_SMTP_MODE=tls
  MAIL_SMTP_CA_FILE=/run/leonaid-staging-mail/ca.pem
  ```

  Der Stack erzeugt eine eigene CA für Mailpit; nur der Core-Worker und
  Twenty vertrauen ihr. Die Mails, etwa Anmeldecodes, liest du unter
  `http://SERVER:8025` mit Benutzer und Passwort aus
  `LEONAID_STAGING_MAILPIT_UI_AUTH`. Öffne Port 8025 nur für dein eigenes
  Netz. Der Doctor lässt die Prüfung des Mailanbieters aus. Für einen echten
  SMTP-Zugang später die sechs Zeilen oben entfernen und die Werte des
  Anbieters eintragen.
