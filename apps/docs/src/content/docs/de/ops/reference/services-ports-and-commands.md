---
title: Dienste, Ports und Operatorbefehle
description: Kompakte Referenz des Compose-Laufzeitbilds, der veröffentlichten Ports und der Betriebsbefehle.
docId: DOC-P027
audience: [ops]
diataxis: reference
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: a559b9ef8ece443011652ff6d5dd490a04dc139f
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
Compose-Netzen.

Wichtige Befehle: `bootstrap`, `doctor`, `dev`, `check`, `backup`, `restore`,
`pilot-doctor`, `pilot-deploy`, `pilot-release`, `pilot-backup`,
`pilot-restore`, `test-handoff`, `test-backup` und `test-upgrade`. Die aktuelle
vollständige Liste liefert `./leonaid help`; sie ist maßgeblich, wenn diese
Referenz abweicht.
