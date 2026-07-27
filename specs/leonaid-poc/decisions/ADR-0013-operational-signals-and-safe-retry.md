# ADR-0013: Korrelierte Betriebssignale und sicherer Job-Retry

- Status: für den PoC angenommen
- Datum: 2026-07-27
- Entscheider: Produktverantwortlicher und Implementierung
- Referenz: Produkt- und Architekturvorschlag, Kapitel 9.2

## Kontext

Ein grüner Containerstatus erklärt weder, welcher externe Dienst gestört ist,
noch ob ein fachlicher Hintergrundjob dauerhaft gescheitert ist. Gleichzeitig
dürfen Logs keine Sponsor-, Kontakt-, Login-, Mail- oder Dokumentinhalte
offenlegen. Für den PoC soll die bestehende System-Administration die
wichtigsten Betriebsfragen ohne zusätzliche Observability-Plattform
beantworten.

## Entscheidung

FastAPI übernimmt oder erzeugt pro Anfrage eine Request-ID. Der
Operations-Endpunkt verwendet dieselbe ID für aktive, nicht mutierende Probes
zu Twenty, RustFS und Mail. HTTP-Abschluss, Probes und Outbox-Verarbeitung
schreiben einzeilige strukturierte JSON-Ereignisse mit ausschließlich
explizit zugelassenen technischen Feldern.

Prozessverfügbarkeit und Bereitschaft bleiben getrennt:

- Liveness bedeutet ausschließlich, dass der Prozess antwortet.
- Readiness umfasst die für synchrone Kernoperationen erforderlichen Dienste
  PostgreSQL, Twenty und RustFS.
- Mail bleibt ein separat sichtbares Signal, weil der transaktionale
  Outbox-Pfad einen Ausfall puffert.

Kurzlebige API-Zähler bleiben im API-Prozess. Dauerhafte Outbox-, Mail- und
Loginmetriken werden aus Core-PostgreSQL und AuditEvents abgeleitet. Der PoC
behauptet damit keine langfristige Zeitreihenüberwachung.

Nur System-Admins sehen Operations-Daten. Ein manueller Retry benötigt eine
frische Anmeldung und ist ausschließlich für den aktuellen Zustand
`dead_letter` erlaubt. Statuswechsel, Operator, Zeitpunkt, Zähler und
AuditEvent werden in einer Transaktion geschrieben. Payload und detaillierter
Fehler werden weder an den Browser noch in Logs ausgegeben.

## Konsequenzen

- Ein Browserrequest lässt sich über eine ID bis zu allen drei
  Abhängigkeitsprobes korrelieren.
- Ein Ausfall ist nach Twenty, RustFS oder Mail unterscheidbar, ohne die
  gesamte Anwendung pauschal als tot zu markieren.
- Der System-Admin kann einen behobenen, idempotenten Job ohne direkten
  Datenbankzugriff erneut starten.
- Eine produktive Installation sollte strukturierte Logs und Metriken später
  an eine dedizierte, zugriffsgeschützte Plattform exportieren. Retention,
  Alerting, SLOs und Langzeit-Zeitreihen sind nicht Teil des PoC.
- Neue Logfelder benötigen eine bewusste PII-/Secret-Prüfung; freie Payloads
  oder Exception-Texte sind nicht zulässig.
