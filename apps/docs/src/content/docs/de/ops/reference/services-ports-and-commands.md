---
title: Dienste, Ports und Operatorbefehle
description: Kompakte Referenz des Compose-Laufzeitbilds, der veröffentlichten Ports und der Betriebsbefehle.
docId: DOC-P027
audience: [ops]
diataxis: reference
contentRevision: 14
reviewedRevision: 14
verifiedAgainst: 583524f992adb500d686dfe91f72e7fa5b7327cc
reviewer: Björn Schotte
---

| Dienst                        | Aufgabe                                      | Führende Persistenz                     |
| ----------------------------- | -------------------------------------------- | --------------------------------------- |
| Caddy                         | einziger Web-Einstieg und TLS                | Caddy-Daten für öffentliche Zertifikate |
| FastAPI Core + Worker         | Auth, Policies, Fachoperationen, Outbox      | Core PostgreSQL                         |
| Web / PWA / Public / Campaign | Admin-, Akquise- und öffentliche Oberflächen | keine führenden Fachdaten               |
| Twenty Server/Worker          | Firmen und Personen; UI nur für Admins       | Twenty PostgreSQL und Dateien           |
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
80/443 öffentlich. Das Twenty CRM hat keine öffentliche Domain: `twenty-server`
veröffentlicht seinen Port nur auf der Loopback-Adresse des Hosts,
`127.0.0.1:TWENTY_ADMIN_PORT` (Standard 3020), und ist in `crm-data` und im
eigenen Netz `crm-admin`, nie im Proxy-Netz `edge`. `SERVER_URL` und
`AUTH_COOKIE_ALLOWED_ORIGINS` sind `http://localhost:TWENTY_ADMIN_PORT`. `./leonaid crm-admin --env-file DATEI`
prüft die Loopback-Bindung und gibt den Befehl
`ssh -N -L PORT:127.0.0.1:PORT` aus, den die Systemadministration auf ihrem
Arbeitsplatz startet, bevor sie `http://localhost:PORT` öffnet.
Datenbanken, der Valkey-Queue-Speicher, S3 und interne APIs
bleiben in Compose-Netzen. Im Pilot sind nur Worker und Twenty-Worker im Netz
`mail-egress`, dem einzigen Weg zum externen SMTP-Relay. Twenty versendet nur
mit `MAIL_SMTP_MODE=tls` (implizites TLS auf Port 465), weil sein SMTP-Client
STARTTLS nicht erzwingen kann. Bei `starttls` starten die Twenty-Container mit
dem Logger-Mailtreiber und versenden nichts; `pilot-doctor` warnt, blockiert
aber nicht.

Wichtige Befehle: `bootstrap`, `doctor`, `dev`, `check`, `backup`, `restore`,
`pilot-doctor`, `pilot-deploy`, `pilot-release`, `pilot-backup`,
`pilot-restore`, `pilot-repair-crm-match-keys`, `crm-admin`, `test-handoff`, `test-backup` und `test-upgrade`. Die aktuelle
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

## Modulschalter

Fachmodule sind standardmäßig eingeschaltet. `LEONAID_DISABLED_MODULES` in der
Env-Datei der Installation schaltet Module kommagetrennt ab, zum Beispiel
`LEONAID_DISABLED_MODULES=surveys`. Schaltbare Module sind `surveys`, `tasks`, `materials` und `knowledge`
(knowledge benötigt tasks und materials); Kernbereiche wie Mail und Rechnungen lassen sich nicht
abschalten. API und Worker lesen denselben Wert; nach einer Änderung beide neu
starten.

Ein abgeschaltetes Modul behält alle Daten. Es zeigt keine Navigation, seine
API-Routen sind nicht registriert und antworten mit 404, und die Webseiten
fallen auf die Übersicht zurück. Der Worker betreibt keine seiner Schleifen
und lässt seine Jobs wartend liegen: Sie werden weder versucht noch als
Dead Letter abgelegt und laufen, sobald das Modul wieder eingeschaltet ist.
Eine unbekannte oder nicht schaltbare ID oder das Abschalten eines Moduls, das
ein eingeschaltetes Modul benötigt, stoppt die API beim Start und den Worker
mit `worker.configuration.invalid`.

## Material-Uploads bereinigen

Ein abgebrochener Material-Upload kann eine private Speicherversion
hinterlassen, auf die kein Material verweist. Ein wiederholter Upload
übernimmt sie. Um genau eine solche Version endgültig zu entfernen, führe
`docker compose exec api python -m leonaid.entrypoints.material_cleanup` mit
exaktem Material, Upload und Speicherversion aus; es prüft zuerst und löscht
nur mit `--apply`. Das Vorgehen steht in `tools/materials/README.md`.

## Joblaufzeit und Fehlerangaben

Ein Modul kann die Laufzeit seiner Outbox-Handler begrenzen. Der Worker
kappt jede Grenze bei 80 % von `OUTBOX_CLAIM_LEASE_SECONDS` (Standard `300`).
Das Rendern von Umfrage-Exporten ist auf 240 s begrenzt. Ein Job, der seine
Grenze überschreitet, wird abgebrochen und mit dem Fehlercode `job_timeout`
erneut versucht. Jobs speichern als Fehlerangabe nur den sicheren Fehlercode,
nie Ausnahmetext. Jede Joblogzeile (`outbox.job.*`) enthält `durationMs`,
wenn der Job abgeschlossen wurde, fehlschlug oder seinen Claim verlor.

Die Outbox-Karte unter `/admin/system` zeigt außerdem den nächsten
wartenden Versuch und wie lange der älteste fällige Job schon wartet
(API-Felder `nextPendingAttemptAt` und `oldestDuePendingAgeSeconds`). Jobs
abgeschalteter Module zählen bei beiden Werten nicht, weil sie absichtlich
warten. Eine wachsende Wartezeit bei laufendem Worker deutet auf eine
hängende oder überlastete Queue.

## Laufzeitgrenzen und Identität

Jeder dauerhaft laufende Dienst hat eine Speicher-, CPU- und Prozessgrenze
(`mem_limit`, `cpus`, `pids_limit`) und rotierte Logs (Treiber `local`,
5 × 10 MB). Die Grenzen sind Obergrenzen, keine Reservierungen. Der Pilotumfang
einschließlich Monitoring-Profil passt auf einen VPS mit 8 GB und lässt etwa
1,6 GiB für Betriebssystem und Docker frei. Der Deployment-Vertrag
(`pilot-doctor`, `pilot-deploy`) lehnt Grenzen ab, deren Summe weniger als
1,5 GiB frei lässt. „Spitze“ ist der höchste unter Last gemessene Working Set
(Upgrade, Installation, CRM-Import mit 3000 Zeilen, Golden Journey, Backup und
Restore; gemessen am 2. November 2026 mit Twenty 2.54). „Leerlauf“ reicht vom 5. Perzentil bis zum Median aller Messpunkte.

| Dienst                         | Beobachtet (Leerlauf) | Spitze (Last) | Speichergrenze | CPUs | PIDs |
| ------------------------------ | --------------------- | ------------- | -------------- | ---- | ---- |
| twenty-server                  | 330–680 MiB           | 1223 MiB      | 1728 MiB       | 2    | 512  |
| twenty-worker                  | 590–640 MiB           | 960 MiB       | 1400 MiB       | 1,5  | 512  |
| worker (inkl. Typst)           | 70 MiB                | 94 MiB        | 512 MiB        | 1,5  | 256  |
| api                            | 105–110 MiB           | 151 MiB       | 384 MiB        | 1,5  | 256  |
| core-postgres                  | 20–22 MiB             | 70 MiB        | 384 MiB        | 1,5  | 256  |
| twenty-postgres                | 29–65 MiB             | 139 MiB       | 384 MiB        | 1,5  | 256  |
| twenty-redis (Valkey)          | 4–15 MiB              | 30 MiB        | 512 MiB        | 0,5  | 64   |
| rustfs                         | 22–23 MiB             | 49 MiB        | 256 MiB        | 1    | 256  |
| survey-validator               | 14–17 MiB             | 27 MiB        | 128 MiB        | 1    | 64   |
| proxy (Caddy)                  | 13–18 MiB             | 31 MiB        | 128 MiB        | 1    | 128  |
| public                         | 23–25 MiB             | 75 MiB        | 128 MiB        | 1    | 64   |
| web, pwa                       | je 13–14 MiB          | 20 MiB        | je 64 MiB      | 0,5  | 64   |
| **Summe Core**                 | ca. 1,7 GiB           | 2,4 GiB¹      | **5,9 GiB**    |      |      |
| prometheus                     | 59–63 MiB             | 69 MiB        | 256 MiB        | 0,5  | 128  |
| pilot-exporter                 | 18–19 MiB             | 30 MiB        | 128 MiB        | 0,5  | 64   |
| alertmanager                   | 22–25 MiB             | 27 MiB        | 64 MiB         | 0,25 | 64   |
| **Summe Pilot mit Monitoring** |                       |               | **6,4 GiB**    |      |      |

¹ Höchste Summe aller Working Sets zum selben Zeitpunkt, nicht die Summe der
Spitzen.

Die optionale Kampagnenseite (Profil `emdash`) kommt mit 384 MiB hinzu. Wird
ein Dienst wegen Speichermangels beendet (`docker inspect` zeigt
`OOMKilled: true`), hebt man seine Grenze an und senkt eine andere, sodass die
Summe weiter auf den Host passt.

Node bemisst den V8-Heap ohne Vorgabe nach der Containergrenze.
`twenty-server` setzt deshalb `NODE_OPTIONS=--max-old-space-size=1024` und
`twenty-worker` `--max-old-space-size=768`. Gemessene Heap-Spitzen: 742 von
1072 MiB Heap-Grenze (69 %) für `twenty-server` und 560 von 816 MiB (69 %) für
`twenty-worker`. Die Spitze von `twenty-server` entsteht bei jedem Start:
Vor `node dist/main` läuft `yarn command:prod upgrade` mit bis zu 1085 MiB
RSS plus yarn-Hülle; deshalb liegt die Grenze bei 1728 MiB. Senke eine
Twenty-Speichergrenze nie, ohne diesen Wert zu prüfen; sonst bricht Twenty mit
„JavaScript heap out of memory“ ab. Der Deployment-Vertrag verlangt
mindestens 256 MiB zwischen `--max-old-space-size` und `mem_limit`. `twenty-worker`
startet `node dist/queue-worker/queue-worker` direkt, ohne die
yarn-Hüllprozesse (etwa 200 MiB). Beide Twenty-Dienste laufen mit
`init: true`; `docker stop` lässt Twenty deshalb aktive Jobs beenden und
sauber herunterfahren.

`twenty-redis` betreibt Valkey 9.1, einen BSD-lizenzierten Server für das
Redis-Protokoll. Der Dienst behält seinen Namen, weil Twenty `REDIS_URL` liest.
Er erhält `--maxmemory 384mb` mit `noeviction`, das BullMQ verlangt: Ist der
Speicher voll, lehnt er Schreibzugriffe mit einem Fehler ab, bevor die
Containergrenze ihn beendet. Twenty behält je Queue bis zu 1000 erledigte und
1000 fehlgeschlagene Jobs (4 Stunden bzw. 7 Tage); ein großer CRM-Import füllt
den Speicher um etwa 20 MiB pro Minute. Valkey kann die Datendateien von
Redis 7.4 nicht laden. `pilot-release` (und lokal das erste `up` eines
`./leonaid`-Befehls) führt deshalb einmal
`infra/upgrade/twenty-queue-store.sh migrate` aus: Es stoppt `twenty-server`,
lässt den alten `twenty-worker` alle wartenden, aktiven und verzögerten Jobs
abarbeiten (höchstens `LEONAID_QUEUE_DRAIN_TIMEOUT` Sekunden, Standard 300) und
leert danach das Volume. Job-Historie und Cache gehen verloren; Cron-Jobs
registriert `twenty-server` beim Start neu. Sind nach der Frist noch Jobs
offen, bricht der Befehl ab und lässt das Volume unverändert; setze
`LEONAID_QUEUE_DISCARD_PENDING=true` nur, wenn diese Jobs entfallen dürfen.
`pilot-deploy` weist einen nicht migrierten Speicher ab.

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
