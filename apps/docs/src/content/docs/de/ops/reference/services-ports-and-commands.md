---
title: Dienste, Ports und Operatorbefehle
description: Kompakte Referenz des Compose-Laufzeitbilds, der veröffentlichten Ports und der Betriebsbefehle.
docId: DOC-P027
audience: [ops]
diataxis: reference
contentRevision: 5
reviewedRevision: 5
verifiedAgainst: afa78a892a766115c5b0c3d33f0af8ac4c751c13
reviewer: Björn Schotte
---

| Dienst                        | Aufgabe                                      | Führende Persistenz                     |
| ----------------------------- | -------------------------------------------- | --------------------------------------- |
| Caddy                         | einziger Web-Einstieg und TLS                | Caddy-Daten für öffentliche Zertifikate |
| FastAPI Core + Worker         | Auth, Policies, Fachoperationen, Outbox      | Core PostgreSQL                         |
| Web / PWA / Public / Campaign | Admin-, Akquise- und öffentliche Oberflächen | keine führenden Fachdaten               |
| Twenty Server/Worker          | Firmen und Personen                          | Twenty PostgreSQL und Dateien           |
| RustFS                        | private unveränderliche Dokumentbytes        | RustFS-Volume                           |
| Mail-Relay                    | E-Mail von LeonAid und Twenty CRM            | externer Provider; lokal Mailpit        |

Lokal veröffentlicht nur Caddy `127.0.0.1:8443` für HTTPS und
`127.0.0.1:8080` für Diagnose-HTTP. Ist einer der Ports belegt, wählt
`bootstrap` einmalig das erste freie Paar ab 28080 und speichert es als
`LEONAID_HTTP_PORT` und `LEONAID_HTTPS_PORT` in `.env.local`. Für Zugriff aus
dem LAN setzt man `LEONAID_BIND_ADDRESS=0.0.0.0` und `LEONAID_LAN_HOST` auf den
LAN-Namen des Hosts, etwa `myhost.local` (keine IP: Browser senden dafür kein
TLS-SNI); dann ist der Dev-Stack im LAN erreichbar. `LEONAID_REMOTE_HOST`
ergänzt einen zweiten Namen für denselben Stack, etwa den Tailscale- oder
VPN-Namen `myhost.tailnet.ts.net`; ungenutzt bleibt er `127.0.0.1`. Änderungen
übernimmt `./leonaid dev`. Im Pilot-Overlay sind ausschließlich
80/443 öffentlich. Datenbanken, Redis, S3 und interne APIs bleiben in
Compose-Netzen. Im Pilot sind nur Worker und Twenty-Worker im Netz
`mail-egress`, dem einzigen Weg zum externen SMTP-Relay.

Wichtige Befehle: `bootstrap`, `doctor`, `dev`, `check`, `backup`, `restore`,
`pilot-doctor`, `pilot-deploy`, `pilot-release`, `pilot-backup`,
`pilot-restore`, `pilot-repair-crm-match-keys`, `test-handoff`, `test-backup` und `test-upgrade`. Die aktuelle
vollständige Liste liefert `./leonaid help`; sie ist maßgeblich, wenn diese
Referenz abweicht.

## Worker-Aufbewahrung

Der Worker betreibt neben `outbox`, `survey_sweep` und der PostgreSQL-Probe
eine Schleife `retention`. Einmal pro `OUTBOX_RETENTION_INTERVAL_SECONDS`
(Standard `3600`) löscht sie Outbox-Jobs, die vor mehr als
`OUTBOX_RETENTION_DAYS` (Standard `30`) Tagen erfolgreich abgeschlossen
wurden, sowie Rate-Limit-Versuche, die älter als zwei Tage sind. Sie löscht
nie wartende, laufende oder Dead-Letter-Jobs und keine abgeschlossenen Jobs,
auf die noch ein Rechnungsversand, ein Umfrage-Export oder eine
Umfrage-Löschung verweist. Bei einer versendeten E-Mail löscht sie den Job,
behält aber den Nachweis in `mail_delivery`, ohne Verweis auf den Job. Sie löscht in Stapeln von
`OUTBOX_RETENTION_BATCH_SIZE` (Standard `500`) Zeilen, höchstens
`OUTBOX_RETENTION_MAX_BATCHES` (Standard `20`) Stapel pro Durchlauf, und
überspringt Zeilen, die eine andere Sitzung gesperrt hält. Ungültige Werte
beenden den Worker beim Start mit `worker.configuration.invalid`. Die Metrik
`leonaid_worker_retention_deleted_total{table=...}` zählt gelöschte Zeilen;
die Outbox-Zähler unter `/admin/system` zeigen abgeschlossene Jobs daher nur
für das Aufbewahrungsfenster. `docker compose run --rm worker python -m
leonaid.entrypoints.worker.outbox retention-sweep` startet einen Durchlauf von
Hand.

## Laufzeitgrenzen und Identität

Jeder dauerhaft laufende Dienst hat eine Speicher-, CPU- und Prozessgrenze
(`mem_limit`, `cpus`, `pids_limit`) und rotierte Logs (Treiber `local`,
5 × 10 MB). Die Grenzen sind Obergrenzen, keine Reservierungen. Der Pilotumfang
einschließlich Monitoring-Profil passt auf einen VPS mit 8 GB und lässt etwa
1,4 GiB für Betriebssystem und Docker frei.

| Dienst                      | Beobachtet (Leerlauf) | Speichergrenze | CPUs | PIDs |
| --------------------------- | --------------------- | -------------- | ---- | ---- |
| twenty-server               | 610–780 MiB           | 1600 MiB       | 2    | 512  |
| twenty-worker               | 630–670 MiB           | 1400 MiB       | 1,5  | 512  |
| worker (inkl. Typst)        | 70 MiB                | 768 MiB        | 1,5  | 256  |
| api                         | 115 MiB               | 384 MiB        | 1,5  | 256  |
| core-postgres               | 27 MiB                | 384 MiB        | 1,5  | 256  |
| twenty-postgres             | 35 MiB                | 384 MiB        | 1,5  | 256  |
| twenty-redis                | 15–31 MiB             | 256 MiB        | 0,5  | 64   |
| rustfs                      | 40 MiB                | 256 MiB        | 1    | 256  |
| survey-validator            | 21 MiB                | 256 MiB        | 1    | 64   |
| proxy (Caddy)               | 16 MiB                | 128 MiB        | 1    | 128  |
| public                      | 29 MiB                | 128 MiB        | 1    | 64   |
| web, pwa                    | je 16–17 MiB          | je 64 MiB      | 0,5  | 64   |
| **Summe Core**              | ca. 2,5 GiB           | **5,9 GiB**    |      |      |
| prometheus                  | —                     | 256 MiB        | 0,5  | 128  |
| pilot-exporter              | —                     | 128 MiB        | 0,5  | 64   |
| alertmanager                | —                     | 64 MiB         | 0,25 | 64   |
| **Summe Pilot mit Monitoring** |                    | **6,4 GiB**    |      |      |

Die optionale Kampagnenseite (Profil `emdash`) kommt mit 384 MiB hinzu. Redis
erhält `--maxmemory 192mb`: Mit `noeviction` lehnt es Schreibzugriffe ab, bevor
die Containergrenze es beendet. Wird ein Dienst wegen Speichermangels beendet
(`docker inspect` zeigt `OOMKilled: true`), hebt man seine Grenze an und senkt
eine andere, sodass die Summe weiter auf den Host passt.

Das Core-Image läuft als fester Benutzer `10001:10001`. `api`, `worker`, `web`,
`pwa`, `public` und `survey-validator` laufen mit schreibgeschütztem
Root-Dateisystem, einem kleinen `tmpfs` unter `/tmp`, ohne Linux-Capabilities
und mit `no-new-privileges`. `pilot-doctor` weist eine Pilotkonfiguration ohne
diese Einstellungen ab. Releases vor dieser Änderung liefen als root und
schrieben das Survey-Löscharchiv als root. Der einmalige Dienst
`core-volume-init` übergibt dieses Volume deshalb vor jedem Start von
`api`/`worker` an `10001:10001`; bestehende Installationen brauchen keinen
manuellen Schritt. `pilot-exporter` läuft als das Konto, das `./leonaid`
aufruft, weil er dessen Backup-Manifest mit Modus `0600` liest.
