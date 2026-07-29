# Operativer Betrieb im PoC

LeonAid trennt Prozessverfügbarkeit, Abhängigkeitsbereitschaft und
fachliche Jobfehler. Die System-Administration sieht diese Signale unter
`/admin/system`; der zugrunde liegende Vertrag ist
`GET /api/v1/admin/operations`.

## Signale

| Signal | Quelle | Bedeutung |
| --- | --- | --- |
| `/health/live` | FastAPI | der API-Prozess antwortet |
| `/health/ready` | FastAPI | PostgreSQL, Twenty und RustFS sind bereit |
| Operations-Abhängigkeiten | aktive HTTP-Probes | Twenty, RustFS und Mail sind einzeln erreichbar |
| API-Metriken | FastAPI-Prozess | Requests, Serverfehler und mittlere Latenz seit Prozessstart |
| Outbox-/Mail-Metriken | Core-PostgreSQL | pending, processing, completed und dead letter |
| Login-Metriken | AuditEvent | Anforderungen, Abschlüsse und Fehler der letzten 24 Stunden |

Mail ist für das Lesen und die meisten Fachoperationen nicht
readiness-kritisch. Ein Mailausfall erscheint deshalb als eigenes
Operations-Signal und als wiederholbarer Outbox-Job, setzt
`/health/ready` aber nicht auf 503.

## Korrelation und Logvertrag

Ein gültiger Browser-Header `X-Request-ID` wird übernommen, andernfalls
erzeugt FastAPI eine UUID. Dieselbe ID steht in der HTTP-Antwort, im
abgeschlossenen Request-Log und in den direkten Probes zu Twenty, RustFS und
Mailpit beziehungsweise dem späteren Maildienst.

Logs sind einzeilige JSON-Objekte. Zulässig sind ausschließlich technische
Felder wie:

- Eventname, Zeitpunkt, Request-, Job-, Action- und relevante Objekt-ID;
- HTTP-Methode, normalisierter Pfad, Status und Latenz;
- Event-/Aggregattyp, Versuchszähler und stabiler Fehlercode;
- Abhängigkeitsname und Status.

Nicht geloggt werden Request- oder Event-Payloads, Queryparameter, E-Mail,
Name, Sitzungs-/Magic-Link-Token, Fehlerdetails, Mailtext oder Dokumentbytes.
Ausführliche technische Fehler bleiben geschützt im jeweiligen
Outbox-Datensatz und werden in der Admin-Oberfläche nur als stabiler Code
angezeigt.

## Dead Letter sicher wiederholen

1. Als System-Admin frisch anmelden.
2. `/admin/system` öffnen und die Abhängigkeit beheben.
3. Beim betroffenen Job `Sicher wiederholen` wählen.
4. Prüfen, dass der Job aus dem Fehlerbestand verschwindet und die
   `completed`-Kennzahl steigt.

Der API-Endpunkt akzeptiert nur aktuell als `dead_letter` markierte Jobs,
benötigt System-Admin plus frische Anmeldung und schreibt Operator, Zeitpunkt,
Zähler und ein AuditEvent atomar. Die Fachhandler bleiben idempotent; ein
zweiter Klick auf denselben Zustand wird als Konflikt abgewiesen.

## Reproduzierbarer Nachweis

```sh
./leonaid test-operations
```

Der Test verwendet frische reale Volumes. Er stoppt Twenty, RustFS und
Mailpit einzeln, prüft Liveness/Readiness, erzeugt bei ausgeschaltetem SMTP
einen echten Login-Mail-Dead-Letter und verarbeitet ihn nach dem
System-Admin-Klick in Chromium genau einmal. Bekannte PII-, Token- und
Dokumentsignaturen werden anschließend gegen die gesammelten Logs geprüft.

## Pilot-Monitoring

Für den Pilot ergänzt das Compose-Profil `monitoring` den bestehenden
Operations-Vertrag um:

- Prometheus 3.13.0 für Scraping und zehn versionierte P0/P1/P2-Regeln;
- Alertmanager 0.32.1 für Gruppierung, Deduplizierung und gelöste Meldungen;
- einen kleinen LeonAid-Exporter für Backupalter, Kapazität und öffentliches
  TLS ohne Docker-Socket oder privilegierten Container;
- einen extern konfigurierten Webhook aus einer privaten 0600-Datei. Dieser
  Kanal darf nicht vom LeonAid-Mailpfad abhängen.

Beide Upstream-Images sind in `infra/locks/external-systems.lock` nach Tag und
Multi-Arch-Digest fixiert. Prometheus und Alertmanager besitzen keine
öffentlichen Hostports. Die Metrik-Endpunkte von API und Worker sind nur im
internen `telemetry`-Netz erreichbar.

Der System-Admin-Bereich `/admin/system` liest über dieselben internen Quellen
einen semantischen Status für Backup, freien Speicher, TLS und aktive Alarme.
Er zeigt verständliche Zustände, Priorität und Runbook statt PromQL oder
Rohmetriken. Ohne gestartetes `monitoring`-Profil bleibt dieser Bereich
explizit neutral auf „Nicht aktiv“.

Alarmtexte bestehen ausschließlich aus festen Zusammenfassungen, technischen
Labels und Links auf [`RUNBOOKS.md`](RUNBOOKS.md). Wartungsmodus unterdrückt
erwartete Verfügbarkeits-, Job- und API-Alarme, nicht aber Backup-, Kapazitäts-
oder TLS-/Security-Alarme.

Der reale End-to-End-Nachweis läuft isoliert:

```sh
./leonaid test-pilot-alerting
```

Der Test validiert die produktiven Konfigurationen mit `promtool` und
`amtool`, stoppt alle vier kritischen Dienste, erzwingt Backup- und
Speicheralarme, prüft den semantischen Admin-Status gegen dieselben Quellen und
verifiziert jeweils Alarmzustellung sowie Recovery.
