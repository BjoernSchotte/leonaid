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
einem Neustart aller Standardcontainer. Anschließend beweist er
Reset-Sicherheit, idempotentes Seeding über die offizielle Twenty API, echte
Typst-PDFs in RustFS, einen leeren Mailpit-Stand sowie die exakte
Wiederherstellung nach realen Mutationen aller vier Systeme.

Der gezielte Identitätsnachweis läuft mit:

```sh
./leonaid test-identity
```

Er startet ebenfalls aus leeren Volumes, sät Golden-Benutzer und -Aktionen,
prüft serverseitige Sitzungen, Rollenänderungen und AuditEvents gegen
PostgreSQL/FastAPI und bedient anschließend Admin- und PWA-Shell mit einem
echten Chromium. Laufzeit-Sitzungstoken liegen nur in einer temporären Datei
mit Modus `0600`; die geheimnisfreien Screenshots bleiben ignoriert unter
`.artifacts/poc040/`.
