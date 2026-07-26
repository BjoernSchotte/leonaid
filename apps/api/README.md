# API

FastAPI ist der HTTP-Adapter vor den frameworkfreien LeonAid Application
Services. Der Composition Root validiert die typisierte Konfiguration beim
Start und verdrahtet reale PostgreSQL- und HTTP-Adapter.

Aktuelle Plattform-Endpunkte:

- `GET /health/live`
- `GET /health/ready`
- `GET /api/v1/platform`

Aktionstemplates werden ausschließlich über den Core bedient:

- `GET /api/v1/action-templates` liefert je Typ die neueste verfügbare,
  veröffentlichte Version.
- `POST /api/v1/actions/from-template` legt Aktion, effektive Angebote,
  Formularkonfiguration, Template-Snapshot und Admin-Zuordnung atomar an.
- `GET /api/v1/actions/{action_id}/configuration` liefert die für diese
  Aktion unveränderlich festgehaltene Konfiguration.
- `POST /api/v1/actions/{action_id}/copies` erzeugt eine neue Draft-Aktion
  mit eigener Konfiguration und neuen IDs, jedoch ohne operative Vorgänge.

Die veröffentlichten Template-Versionen und die Aktions-Snapshots sind in
PostgreSQL unveränderlich. Neue fachliche Vorgaben werden deshalb als neue
Version angelegt und ändern bestehende Aktionen nicht rückwirkend.

Jede Antwort trägt `X-Request-ID`. Fehler verwenden ausschließlich das
einheitliche, geheimnisfreie Format `error.code`, `error.message` und
`error.requestId`.
