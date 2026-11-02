---
title: Login-, Mail- und TLS-Störungen eingrenzen
description: Häufige Betriebsfehler mit Doctor, Healthchecks und sicheren Korrelationen diagnostizieren.
docId: DOC-P025
audience: [ops]
diataxis: how-to
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: a559b9ef8ece443011652ff6d5dd490a04dc139f
reviewer: Björn Schotte
---

Beginne lokal mit `./leonaid doctor`, im Pilotbetrieb mit `./leonaid
pilot-doctor ... --json`. Teile den sanitizten Status, nie `.env`-Inhalte,
Tokens, E-Mail-Adressen oder Dokumentbytes.

- **Docker nicht erreichbar:** Starte Docker/OrbStack und wiederhole `doctor`.
- **Login-Code fehlt:** Prüfe Worker, Outbox und Mail-Relay. Lokal wird Mailpit
  nur über das Profil `dev-mail` gestartet. Verwende immer die zuletzt
  versendete E-Mail; Codes sind einmalig und Fehlversuche werden begrenzt.
- **Zu viele Loginversuche:** Warte die sichtbare Sperrfrist ab. Umgehe weder
  Rate Limit noch generische Auth-Antworten.
- **HTTPS lokal:** Verwende `https://localhost:8443`; der HTTP-Port 8080 dient
  der Diagnose. Importiere die lokale CA nur in einer kontrollierten
  Entwicklungsumgebung.
- **Öffentliches TLS:** Prüfe DNS, Hostname, vollständige Vertrauenskette,
  Sicherheitsheader und mindestens 14 Tage Zertifikatsrestlaufzeit mit dem
  Pilot Doctor. Port 80 bleibt für ACME und HTTPS-Weiterleitung erreichbar.
- **Twenty-CRM-Prüfung schlägt fehl:** `doctor` (bei laufendem Dev-Stack) und
  die Gates `pilot-deploy`/`pilot-release` des Pilot Doctor fragen die laufende
  API, ob Twenty das Feld `leonaidMatchKey` hat und ihren Integrations-Key
  annimmt. Lokal hilft `./leonaid provision-twenty`, im Pilotbetrieb
  `./leonaid pilot-release --twenty-bootstrap-file FILE`. Die Prüfung zählt
  außerdem Datensätze ohne Schlüssel; `repair-crm-match-keys` schließt diese
  Lücke.
- **Schreibzugriff liefert 503:** Prüfe
  `infra/upgrade/maintenance.sh status`. Deaktiviere Wartung erst nach gesunden
  Abhängigkeiten und bestandenen Verträgen.

Bei wiederholbaren Fehlern notiere Zeitpunkt, Release-SHA, Service und
Korrelations-ID. Wiederhole schreibende Jobs nur über den dafür vorgesehenen
sicheren Retry-Weg.

## Dokumentationswebsite zurücksetzen

Schlägt der HTTPS-Smoke nach einem Pages-Deployment fehl, öffne den letzten
grünen `Documentation`-Lauf von `main`, prüfe dessen Manifest-SHA und führe
genau diesen Lauf erneut aus. GitHub Pages aktiviert das daraus neu erzeugte
Artefakt atomar. Prüfe danach den deutschen und englischen Einstieg, Suche,
Sprachwechsel und `build-manifest.json`. Verwende keinen PR-Lauf als
Rollback-Quelle.

Der getrennte Workflow `Documentation watchdog` öffnet bei einem
fehlgeschlagenen `main`-Lauf sofort ein Repository-Issue. Zusätzlich prüft er
alle sechs Stunden, ob seit mehr als 30 Stunden keine erfolgreiche
Veröffentlichung vorliegt. Damit liegt der vorgesehene Alarm vor der
36-Stunden-Grenze. Ein erfolgreicher Wiederanlauf schließt das Issue. Der
Maintainer muss Benachrichtigungen für Repository-Issues aktiviert haben.
