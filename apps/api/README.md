# API

FastAPI is the HTTP adapter in front of the framework-free LeonAid application
services. The composition root validates the typed configuration at startup and
wires real PostgreSQL and HTTP adapters.

Current platform endpoints:

- `GET /health/live`
- `GET /health/ready`
- `GET /api/v1/platform`

Action templates are served only through the Core:

- `GET /api/v1/action-templates` returns the newest available, published
  version per type.
- `POST /api/v1/actions/from-template` creates the action, effective offers,
  form configuration, template snapshot and admin assignment atomically.
- `GET /api/v1/actions/{action_id}/configuration` returns the configuration
  frozen for this action.
- `POST /api/v1/actions/{action_id}/copies` creates a new draft action with its
  own configuration and new IDs, but without operational records.

The published template versions and the action snapshots are immutable in
PostgreSQL. New business rules are therefore created as a new version and do
not change existing actions retroactively.

Every response carries `X-Request-ID`. Errors use only the uniform,
secret-free format `error.code`, `error.message` and `error.requestId`.
