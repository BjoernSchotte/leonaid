---
title: Lokale Demo installieren
description: Einen frischen LeonAid-Checkout mit der gelockten Docker-Toolchain starten und prüfen.
docId: DOC-P021
audience: [ops]
diataxis: tutorial
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

Du benötigst Git, Docker mit Compose v2 und mindestens 5 GiB freien Speicher.
Node, Bun, Python und Datenbanken müssen auf dem Host nicht installiert sein.

1. Klone das Repository und wechsle in den Checkout.
2. Führe `./leonaid bootstrap` aus. Der Befehl erzeugt die ignorierte
   `.env.local` mit lokalen Zufallswerten und installiert gelockte Pakete in
   Docker. Eine vorhandene Datei wird nicht überschrieben.
3. Prüfe mit `./leonaid doctor` Docker, Locks, Secrets und lokale Abhängigkeiten.
4. Starte mit `./leonaid dev` den Standardstack und warte auf die Healthchecks.
5. Öffne `https://localhost:8443`. Das Zertifikat stammt von Caddys lokaler CA.
   `http://localhost:8080` ist nur der zusätzliche Diagnosezugang.
6. Führe `./leonaid test-handoff` aus. Der Test beweist den dokumentierten
   Übergabeweg noch einmal aus einem frischen Checkout.

Erfolgreich ist der Lernweg, wenn `doctor` und `test-handoff` mit Exitcode 0
enden und die Mitgliederoberfläche über HTTPS antwortet. Testdaten sind
synthetisch. Entferne die wiederverwendbare Testumgebung später mit
`./leonaid test-env-stop`; normale lokale Daten werden dadurch nicht gelöscht.
