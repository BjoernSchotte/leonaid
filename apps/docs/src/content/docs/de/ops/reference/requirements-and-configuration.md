---
title: Voraussetzungen und Konfiguration
description: Referenz für lokale und Pilot-Voraussetzungen, Environment-Dateien und Secret-Grenzen.
docId: DOC-P026
audience: [ops]
diataxis: reference
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
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
