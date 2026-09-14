---
title: Einen lokalen Fehler debuggen
description: Einen reproduzierbaren LeonAid-Fehler vom Wrapper bis zum zuständigen Dienst eingrenzen.
docId: DOC-P033
audience: [dev]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

1. Führe `./leonaid doctor` aus und behebe zuerst fehlende Locks, Secrets,
   Pakete oder einen nicht erreichbaren Docker-Daemon.
2. Reproduziere den Fehler mit dem kleinsten passenden `./leonaid test-…`-Befehl.
   Testartefakte bleiben ignoriert unter `.artifacts/`.
3. Prüfe `docker compose --env-file .env.local -f infra/compose/compose.yml ps`
   und danach nur die Logs des betroffenen Diensts.
4. Folge der Eigentumsgrenze: HTTP/Policy/Fachdaten zum FastAPI Core,
   Firmen/Personen zu Twenty, Dokumentbytes zu RustFS, asynchrone Zustellung zu
   Outbox/Worker und Darstellung zur jeweiligen Web-App.
5. Nutze eine technische Korrelations-ID. Kopiere keine Payloads, Tokens,
   E-Mail-Adressen oder Dokumentbytes in Tickets oder Logs.
6. Ergänze einen reproduzierenden Test, behebe die Ursache und führe erst den
   gezielten Test, danach die erforderlichen Gesamtgates aus.

Die VS-Code-Debugprofile hängen sich an die Compose-Dienste; sie starten keine
abweichende zweite Anwendung. So bleiben Konfiguration und Datenpfade mit den
Integrationstests identisch.
