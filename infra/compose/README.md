# Compose

`compose.yml` ist die einzige Definition für lokale Entwicklung und
Integrationstests.

Der Standardstart enthält Caddy, FastAPI, Core-Worker/-PostgreSQL, Web, PWA,
Public Web, Twenty Server/Worker/PostgreSQL/Redis und RustFS:

```sh
./leonaid dev
```

Optionale Dienste werden explizit zugeschaltet:

```sh
docker compose --env-file .env.local -f infra/compose/compose.yml \
  --profile dev-mail up -d --wait
docker compose --env-file .env.local -f infra/compose/compose.yml \
  --profile mailing up -d --wait
docker compose --env-file .env.local -f infra/compose/compose.yml \
  --profile observability up -d --wait
```

`./leonaid test-integration` verwendet ein isoliertes Compose-Projekt und
räumt nur dessen Container, Netze und Volumes auf. Der Test startet aus
leeren Volumes, prüft sämtliche Healthchecks und Host-Portbindungen, schreibt
Golden Data über PostgreSQL und die echte S3-API und verifiziert sie nach
einem Neustart aller Standardcontainer.
