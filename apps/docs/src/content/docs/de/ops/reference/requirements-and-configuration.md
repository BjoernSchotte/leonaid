---
title: Voraussetzungen und Konfiguration
description: Referenz für lokale und Pilot-Voraussetzungen, Environment-Dateien und Secret-Grenzen.
docId: DOC-P026
audience: [ops]
diataxis: reference
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 6d17bcfaca798bedf39427163d35a7ccd859a66e
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

| Bereich     | Lokal                                                 | Pilot/Produktion                                                                   |
| ----------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Host        | Git, Docker, Compose v2, mindestens 5 GiB frei        | Linux-Host, Docker/Compose, öffentliche Domains und Ports 80/443                   |
| Environment | `.env.local`, ignoriert und durch `bootstrap` erzeugt | ausgefüllte Vorlage außerhalb Git, Owner-only, Modus `0600`                        |
| Images      | gelockte Entwicklungsimages                           | ausschließlich Release-Images mit Tag und Digest                                   |
| Identität   | `LEONAID_ENV=local` und getrennte lokale Zufallswerte | Stage, Compose-Projekt, Bucket und vollständiger Release-SHA müssen zusammenpassen |
| Backup      | für Entwicklung optional                              | externes Restic-Ziel, eigenes Passwort und Backend-Zugangsdaten                    |
| Mail/TLS    | optional Mailpit, lokale Caddy-CA                     | eigener SMTP-Zugang, öffentlicher DNS-/TLS-Nachweis                                |

Die versionierte `.env.example` enthält ausschließlich Generator-Platzhalter.
`./leonaid bootstrap` ersetzt sie lokal und überschreibt keine bestehende
`.env.local`. Produktionswerte werden nicht aus dieser lokalen Datei übernommen.

Ein Secret gehört weder in Git noch in Prozessargumente, Browserkonfiguration,
Logs oder öffentliche Artefakte. Der Twenty-Integrations-Key wird separat
rotiert und nur in Core-Prozesse injiziert. Prüfe die effektive Konfiguration
vor jeder Pilotmutation mit `pilot-doctor`.

## Web Push: Benachrichtigungen der Akquise-App

Die Akquise-App sendet Benachrichtigungen über die Push-Dienste der
Browserhersteller (Web Push mit VAPID, ADR-0017). Dafür braucht die
Installation zwei Werte; API und Worker bekommen dieselben.

| Variable                    | Bedeutung                                                                                                                                                                                                 |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `LEONAID_VAPID_PRIVATE_KEY` | Privater P-256-Schlüssel der Installation, base64url des 32-Byte-Skalars. `./leonaid bootstrap` (lokal) und `./leonaid pilot-secrets` (Pilot) erzeugen ihn. Die API gibt nur den öffentlichen Teil heraus. |
| `LEONAID_VAPID_SUBJECT`     | Kontakt des Betreibers, den die Push-Dienste bei jedem Push lesen: `mailto:adresse` oder eine `https:`-Adresse.                                                                                           |

- **Ohne Schlüssel** (beide Werte leer) sind Benachrichtigungen „nicht
  eingerichtet“: Die Seite **Benachrichtigungen** sagt das, der Worker sendet
  nichts. Eine Installation, die auf diese Version aktualisiert, startet
  deshalb unverändert.
- **Mit Schlüssel** muss `LEONAID_VAPID_SUBJECT` gesetzt sein. In Produktion
  lehnen API und Worker einen Kontakt mit reserviertem Namen ab
  (`example.org`, `.invalid`, `localhost`). Die Vorlage
  `infra/pilot/production.env.example` trägt `mailto:operations@example.org`:
  Ersetze die Adresse. `pilot-doctor` meldet sonst
  `web_push_settings_invalid`, und der Worker endet beim Start mit
  `worker.configuration.invalid`.
- **Der Schlüssel bleibt für die Lebensdauer der Installation.** Jede
  Anmeldung eines Geräts ist an ihn gebunden. Ein neuer Schlüssel beendet
  alle Anmeldungen: Der Worker sendet an die alten nichts mehr und löscht
  sie. Jedes Gerät meldet sich mit dem neuen Schlüssel von selbst neu an,
  sobald das Mitglied die App dort wieder öffnet; bis dahin bekommt es
  nichts. Der Schlüssel gehört ins Backup der Environment-Datei.
- **Ausgang:** Der Worker sendet an `fcm.googleapis.com` und
  `jmt17.google.com` (Chrome, Edge auf Android),
  `updates.push.services.mozilla.com` (Firefox), `web.push.apple.com` (Safari,
  iPhone, iPad) und Hosts unter `notify.windows.com` (Edge auf Windows), Port
  443. Im Pilot erreicht er sie über das Netz `mail-egress`, im Dev-Stack
  über `geocoder-egress`. Test-Stacks haben keinen Ausgang. An andere Hosts
  sendet er nie; ein weiterer Push-Dienst braucht eine neue Version.
- **Einschalten:** Schlüssel und Kontakt setzen, Dienste neu starten, den
  Datenschutzhinweis für Mitglieder mit dem Abschnitt „Benachrichtigungen auf
  deinem Gerät“ aktivieren, dann unter **System › Feature-Flags**
  **Benachrichtigungen in der Akquise-App** einschalten. Prüfe danach auf
  einem echten Android-Telefon und einem echten iPhone mit **Test senden**
  (siehe [Benachrichtigungen einschalten](../../../user/how-to/switch-on-notifications/)).

Was der Worker dafür tut, steht unter
[Dienste, Ports und Operatorbefehle](../services-ports-and-commands/).
