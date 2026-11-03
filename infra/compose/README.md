# Compose

Current bilingual installation tutorial:
[Deutsch](../../apps/docs/src/content/docs/de/ops/tutorials/local-demo.md) ·
[English](../../apps/docs/src/content/docs/en/ops/tutorials/local-demo.md).
This file remains the low-level Compose reference.

`compose.yml` is the only committed definition for local development and
integration tests. `compose.dev-local.yml` only mounts uncommitted local
extensions into the dev proxy (see below).

The default start contains Caddy, FastAPI, core worker/PostgreSQL, web, PWA,
public web, Twenty server/worker/PostgreSQL/Valkey (service `twenty-redis`)
and RustFS:

```sh
./leonaid dev
```

The member interfaces are then reachable at `https://localhost:8443`. Caddy
creates an internal certificate for local development; diagnostic access also
stays possible at `http://localhost:8080`. Only the proxy publishes these two
ports, and only on the loopback interface.

Optional services are enabled explicitly:

```sh
docker compose --env-file .env.local -f infra/compose/compose.yml \
  --profile dev-mail up -d --wait
docker compose --env-file .env.local -f infra/compose/compose.yml \
  --profile mailing up -d --wait
docker compose --env-file .env.local -f infra/compose/compose.yml \
  --profile observability up -d --wait
```

## Local dev extensions

A developer can extend the local dev stack without committing anything. All
files live in the git-ignored `.local/dev/` directory. Create it to opt in:

```sh
mkdir -p .local/dev/caddy.d .local/dev/static
```

When `.local/dev/` exists, every `./leonaid` command that runs Compose for the
default dev project (`leonaid`) adds these files:

1. `infra/compose/compose.dev-local.yml`. It mounts two directories into the
   `proxy` service, read-only:
   - `.local/dev/caddy.d` → `/etc/caddy/local.d`
   - `.local/dev/static` → `/srv/local-static`
2. `.local/dev/compose.override.yml`, if it exists. It is an ordinary Compose
   file and can add or change services of the dev stack.

The CLI creates both mount directories as the current user, so Docker never
creates root-owned directories. Test stacks use their own project names and
the pilot uses its own Compose commands; neither loads these files.

The dev Caddyfile imports `/etc/caddy/local.d/*.caddy` inside the shared
`leonaid_routes` block, after the built-in routes and before the catch-all
route to the public site. A snippet can therefore add a route under a new path
prefix. Use a prefix that no built-in route uses: Caddy sorts `handle` blocks
by path length, so a longer path inside an existing prefix (for example
`/admin/x/*`) would take those requests away from the built-in route. Import `leonaid_headers` in every snippet to get the
strict Content-Security-Policy. Without it, the response has no CSP.

Example: serve a static single-page app from `.local/dev/static/example` at
`/example/`, with a fallback to `index.html` for client-side routes.
`.local/dev/caddy.d/example.caddy`:

```caddyfile
handle_path /example/* {
	import leonaid_headers
	root * /srv/local-static/example
	try_files {path} /index.html
	file_server
}
```

Caddy reads snippets at start. Apply new or changed snippets with a reload:

```sh
docker compose --project-name leonaid exec proxy \
  caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Run `./leonaid dev` once after you create `.local/dev/` or change
`compose.override.yml`, so that Compose recreates the affected containers.
Plain `docker compose` commands without the CLI do not load the local files;
if they recreate the proxy, run `./leonaid dev` again.

`./leonaid test-integration` uses an isolated Compose project and cleans up
only its own containers, networks and volumes. The test starts from empty
volumes, checks all health checks and host port bindings, writes golden data
through PostgreSQL and the real S3 API and verifies it after a restart of all
default containers. It then proves reset safety, idempotent seeding through
the official Twenty API, real Typst PDFs in RustFS, an empty Mailpit state and
exact recovery after real mutations of all four systems.

The targeted identity evidence runs with:

```sh
./leonaid test-identity
```

It also starts from empty volumes, seeds golden users and actions, checks
server-side sessions, role changes and AuditEvents against PostgreSQL/FastAPI
and then drives the admin and PWA shells with a real Chromium. Runtime
session tokens live only in a temporary file with mode `0600`; the secret-free
screenshots stay ignored under `.artifacts/poc040/`.

The targeted invitation evidence runs with:

```sh
./leonaid test-invitations
```

It starts PostgreSQL, FastAPI, worker, Mailpit, Caddy and the web interfaces
from empty isolated volumes. The contract loads real invitation emails from
Mailpit, accepts separate invitations by link and by code and checks expiry,
revocation, reuse, the lockout after failed attempts, atomic
account/membership activation and AuditEvents. Chromium then proves, at
desktop and mobile width, the server-side limited action selection and the
public code entry. Secret-free screenshots stay under `.artifacts/poc041/`.

The targeted session evidence runs with:

```sh
./leonaid test-sessions
```

It starts PostgreSQL, FastAPI, worker, Mailpit and the interfaces with real
HTTPS from empty, isolated volumes. The contract and Chromium prove the
generic passwordless login, the protected `__Host-` cookie, the absolute
90-day end, normal access after the fresh period has expired, the new code
sign-in for a sensitive admin action, token rotation, logout and immediate
administrative revocation. Secret-free screenshots stay under
`.artifacts/poc042/`.

The targeted row-level policy evidence runs with:

```sh
./leonaid test-policy
```

It provisions a new pinned Twenty instance with a restricted integration key,
seeds the complete golden dataset with real Typst documents and checks the
shared server-side scope for lists, search, counts, export, activity and
documents. Acquirers authenticate only against LeonAid Core; the Twenty key
is injected only into the core container. Removed memberships and
assignments take effect on the next request without a new sign-in.

The targeted evidence for the neutral charity action core runs with:

```sh
./leonaid test-actions
```

It starts the pinned default services from empty isolated volumes, persists
lifecycle, capabilities, target values, multiple beneficiaries and
AuditEvents through FastAPI/PostgreSQL and then creates a complete action at
`/admin/actions/new` with a real Chromium. The browser verifies the result
only through the core API. The secret-free screenshot stays under
`.artifacts/poc050/`.

The targeted evidence for versioned action templates runs with:

```sh
./leonaid test-templates
```

It starts Twenty, core PostgreSQL, FastAPI and RustFS from empty isolated
volumes. A real API/PostgreSQL contract proves the neutral and the
Krapfentaxi template, immutable published versions, historically stable
configuration snapshots and a previous-year copy without orders, invoices,
documents, sequence numbers or unrelated action assignments.

The real upgrade and recovery evidence runs with:

```sh
./leonaid test-upgrade
```

It upgrades pinned Twenty and RustFS source versions behind a server-side
maintenance boundary, runs the Twenty instance and workspace migrations
fail-closed and verifies the golden contract and Chromium before and after the
upgrade. A separate upgrade clone is deliberately changed and reset from the
encrypted recovery point onto empty volumes. The operating procedure is in
[`infra/upgrade/README.md`](../upgrade/README.md).

`./leonaid provision-twenty` rotates the local integration key in an isolated
staging directory and replaces `.local/twenty/integration.env` only after
allowed CRM access and denied unrelated or administrative access have been
proven against the real Twenty. The file has restrictive permissions. All
following `./leonaid` Compose commands read it automatically, without copying
the key into `.env.local`, process arguments or browser configuration. After
a rotation, `./leonaid dev` loads the key into the API and worker. An explicit
process variable `TWENTY_INTEGRATION_API_KEY` still takes precedence for CI.
