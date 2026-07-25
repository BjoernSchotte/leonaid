# API

FastAPI ist der HTTP-Adapter vor den frameworkfreien LeonAid Application
Services. Der Composition Root validiert die typisierte Konfiguration beim
Start und verdrahtet reale PostgreSQL- und HTTP-Adapter.

Aktuelle Plattform-Endpunkte:

- `GET /health/live`
- `GET /health/ready`
- `GET /api/v1/platform`

Jede Antwort trägt `X-Request-ID`. Fehler verwenden ausschließlich das
einheitliche, geheimnisfreie Format `error.code`, `error.message` und
`error.requestId`.
