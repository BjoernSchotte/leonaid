---
title: Eine Version releasen
description: Ein CalVer-Release erzeugen, das digest-gebundene Images und ein Release-Manifest veröffentlicht.
docId: DOC-P038
audience: [ops, dev]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 86b4e396de4569cbc7dbd03cdb2153a8698bb0d1
reviewer: Björn Schotte
---

LeonAid-Versionen folgen CalVer. Ein Release heißt `vYYYY.M.N`: Jahr und Monat
in UTC, der Monat ohne führende Null, und `N` zählt die Releases des Monats,
beginnend bei 1. Ein Fix-Release heißt `vYYYY.M.N.P` und baut auf genau einem
Release auf. Tags sind annotiert und werden nie verschoben, gelöscht oder
wiederverwendet.

## Release von main

1. Alles für das Release nach `main` mergen, lokal aktualisieren und warten,
   bis die CI auf dem letzten Commit grün ist.
2. `./leonaid release --dry-run` ausführen. Es zeigt die nächste Version und
   die Notizen, gruppiert nach den Conventional Commits seit dem letzten
   Release.
3. `./leonaid release` ausführen. Es prüft einen sauberen Arbeitsbaum,
   `HEAD` gleich `origin/main`, grüne CI und eine `gh`-Anmeldung und pusht
   dann den Tag.
4. Der Tag startet den Workflow `Release`. Er baut die sechs LeonAid-Images,
   pusht sie nach `ghcr.io/<owner>/leonaid/<name>:<version>` und
   veröffentlicht das GitHub-Release mit drei Dateien:
   - `release-images.env`: Version, Commit und die sechs Image-Referenzen mit
     Tag und Digest;
   - `release-manifest.json`: das Release-Manifest für Produktion;
   - `SHA256SUMS` für beide Dateien.

Der Workflow überschreibt niemals Images, die es für eine Version schon gibt.

## Fix-Release

1. Den Fix zuerst per Pull Request auf `main` bringen.
2. Den Release-Branch einmalig vom Tag anlegen:
   `git switch -c release/2026.11.1 v2026.11.1`.
3. Den Fix mit `git cherry-pick -x <commit>` übernehmen und den Branch pushen.
4. `./leonaid release` auf dem Branch ausführen. Das Ergebnis ist
   `v2026.11.1.1`. Fix-Releases werden nicht als neuestes GitHub-Release
   markiert.

## Abgebrochenes Release fortsetzen

Gibt es den Tag, aber kein GitHub-Release, `./leonaid release` erneut auf dem
getaggten Commit ausführen. Es pusht den Tag erneut und startet den Workflow
dafür. Einen zweiten Tag legt es nie an.

## Release deployen

Die Zeilen aus `release-images.env` unverändert in die private
Environment-Datei übernehmen und mit `release-manifest.json` bei
[Pilotinstallation deployen](/de/ops/how-to/deploy-pilot/) weitermachen.
