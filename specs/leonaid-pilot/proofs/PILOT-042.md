# PILOT-042 – Monitoring und reale Alarmkette

Task-ID: `PILOT-042`

Nachweisdatum: 29. Juli 2026

Status: technische Alarmkette und Admin-Status bewiesen, Betreiberdrill offen

## Ergebnis

Das Pilotprofil ergänzt den bestehenden Operations-Vertrag um ein
payloadfreies, vollständig intern angebundenes Monitoring:

- Prometheus 3.13.0 und Alertmanager 0.32.1 sind nach Tag und
  Multi-Arch-Digest fixiert;
- API, Worker und Pilot-Exporter liefern Metriken ausschließlich im internen
  `telemetry`-Netz;
- zehn versionierte P0/P1/P2-Regeln decken Abhängigkeiten, Jobs, API,
  Loginfehler, Backup, Kapazität und TLS ab;
- jede Regel besitzt Owner, Kategorie, festen Alarmtext und Runbook-Link;
- der produktive Webhook wird ausschließlich aus einer privaten 0600-Datei
  gelesen und darf nicht vom LeonAid-Mailpfad abhängen;
- die System-Admin-UI übersetzt dieselben Quellen in verständliche Zustände
  für Backup, Speicher und Zertifikat und zeigt aktive Alarme mit Priorität
  und Runbook.

Prometheus, Alertmanager und Exporter besitzen keine öffentlichen Hostports.
Der Exporter benötigt weder Docker-Socket noch privilegierten Container.

## Reale Alarm- und Recovery-Kette

`./leonaid test-pilot-alerting` verwendet frische Compose-Volumes und keine
Test-Doubles:

```text
SUCCESS: Prometheus-Konfiguration und 10 Regeln gültig
SUCCESS: Wartungsmodus-Regeltests gültig
SUCCESS: Alertmanager-Konfiguration gültig
pilot-alerting-test: stoppt twenty-server und erwartet Alarm/Recovery
pilot-alerting-test: stoppt rustfs und erwartet Alarm/Recovery
pilot-alerting-test: stoppt mailpit und erwartet Alarm/Recovery
pilot-alerting-test: stoppt worker und erwartet Alarm/Recovery
pilot-alerting-test: erzeugt und heilt ein real veraltetes Backup
pilot-alerting-test: füllt ein echtes 16-MiB-tmpfs bis unter 10 Prozent
pilot-alerting-test: prüft synthetische PII gegen den Alarmkanal
pilot-alerting-test: OK: vier reale Ausfälle, Backup, Disk, Recovery,
pilot-alerting-test:     Wartungsgrenze und PII-freier Webhook bewiesen
```

Für jeden Dienst wurde eine reale `firing`-Meldung am separaten Webhook
empfangen, der Dienst neu gestartet und anschließend die zugehörige
`resolved`-Meldung empfangen. Beim Backup- und Kapazitätsfall wurden zusätzlich
der semantische Exporterstatus und der aktive Alertmanager-Zustand geprüft.

Der Datenträgertest belegt rund 90 Prozent eines echten 16-MiB-tmpfs und gibt
die Datei danach wieder frei. Das vermeidet eine künstliche Stub-Metrik und
lässt zugleich genug Dateisystemreserve für einen stabilen Containerbetrieb.

Das isolierte TLS-Ziel verwendet eine eigene Caddy-CA, die der Exporter
read-only aus Caddys Datenvolume liest. Sein ausschließlich für den Test
geltendes 30-Tage-Zertifikat liegt oberhalb der produktiven
14-Tage-Alarmschwelle. Produktions-TLS und Schwellwert bleiben unverändert.

## Admin-UX und Loghygiene

`./leonaid test-operations` lief anschließend mit frischen realen Diensten,
Golden Data und Chromium vollständig grün:

```text
1 passed in Chromium
operations-test: OK: korrelierte Logs, Metriken, trennscharfe Ausfälle,
operations-test:     sicherer UI-Retry und loghygienische Browser-UX bewiesen
```

Der sichtbare In-App-Browser-Smoke auf `/admin/system` bestätigte:

- vier von vier Abhängigkeiten verständlich als bereit;
- den neutralen Zustand „Nicht aktiv“, wenn das optionale Monitoring-Profil
  lokal nicht gestartet ist;
- keine horizontale Überbreite bei 551 Pixel Viewport;
- keine Browser-Konsolenfehler.

Der synthetische Dead-Letter-Canary enthielt eine einmalige E-Mail-Adresse und
ein Token. Weder Wert erschien im Webhook. Logs und Alarmtexte bestehen aus
stabilen technischen Codes, Request-IDs und festem Metadatenvokabular, niemals
aus Bestell-, Kontakt-, Dokument- oder Mailpayloads.

## Qualitätsgates und Cleanup

Zusätzlich grün:

- 187 Unit-Tests;
- Ruff, Ruff Format und MyPy für 219 Python-Quellen;
- kanonischer OpenAPI-Vertrag und generierter TypeScript-Client;
- TypeScript für API-Client, UI, Features, Web und PWA;
- Astro-Check ohne Fehler, Warnungen oder Hinweise;
- Prettier für alle geprüften Frontenddateien.

Beide isolierten Testprojekte entfernten ihre Container, Netzwerke und Volumes
über ihre exakten Compose-Projektnamen.

## Offene formale Gates

PILOT-042 bleibt formal offen:

- PILOT-020, PILOT-040 und PILOT-041 enthalten noch externe
  Betreiber-/Produktionsnachweise;
- ein benannter Operator muss einen real zugestellten Alarm quittieren, das
  verlinkte Runbook ohne Implementiererhilfe ausführen und den privaten
  Nachweis freigeben.

Erst dieser Operator-Drill schließt `PILOT-GATE-010`.
