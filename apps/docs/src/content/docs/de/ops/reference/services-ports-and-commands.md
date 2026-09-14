---
title: Dienste, Ports und Operatorbefehle
description: Kompakte Referenz des Compose-Laufzeitbilds, der veröffentlichten Ports und der Betriebsbefehle.
docId: DOC-P027
audience: [ops]
diataxis: reference
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

| Dienst                        | Aufgabe                                      | Führende Persistenz                     |
| ----------------------------- | -------------------------------------------- | --------------------------------------- |
| Caddy                         | einziger Web-Einstieg und TLS                | Caddy-Daten für öffentliche Zertifikate |
| FastAPI Core + Worker         | Auth, Policies, Fachoperationen, Outbox      | Core PostgreSQL                         |
| Web / PWA / Public / Campaign | Admin-, Akquise- und öffentliche Oberflächen | keine führenden Fachdaten               |
| Twenty Server/Worker          | Firmen und Personen                          | Twenty PostgreSQL und Dateien           |
| RustFS                        | private unveränderliche Dokumentbytes        | RustFS-Volume                           |
| Mail-Relay                    | Login-, Einladungs- und Rechnungs-E-Mail     | externer Provider; lokal Mailpit        |

Lokal veröffentlicht nur Caddy `127.0.0.1:8443` für HTTPS und
`127.0.0.1:8080` für Diagnose-HTTP. Im Pilot-Overlay sind ausschließlich
80/443 öffentlich. Datenbanken, Redis, S3 und interne APIs bleiben in
Compose-Netzen.

Wichtige Befehle: `bootstrap`, `doctor`, `dev`, `check`, `backup`, `restore`,
`pilot-doctor`, `pilot-deploy`, `pilot-release`, `pilot-backup`,
`pilot-restore`, `test-handoff`, `test-backup` und `test-upgrade`. Die aktuelle
vollständige Liste liefert `./leonaid help`; sie ist maßgeblich, wenn diese
Referenz abweicht.
