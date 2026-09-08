# Visible local acceptance

Use `visible-local.yml` for an interactive, persistent **full** LeonAid stack,
not as an overlay for the disposable headless proof runner. It retains the base
Core, worker, administration, public frontend and Twenty dependencies. EmDash
uses the same localhost HTTPS origin and the existing protected order ingress.
Only Caddy publishes ports, bound to loopback. PostgreSQL and RustFS stay private.

Before starting, select a unique Compose project, two unused host ports and an
unused Docker `/24`. Inspect all existing networks; the existing
`tools/emdash_spike/order-subnet.mjs` helper can select a candidate. Docker must
reject a concurrent subnet or port collision; do not remove the conflicting
project. Set `LEONAID_HTTP_PORT`, `LEONAID_HTTPS_PORT` and
`EMDASH_LOCAL_NET_PREFIX` in the command environment, not in another worktree.

Use these Compose files in this order, with this worktree's private `.env.local`
and an explicit `--project-name`, for **every** operation:

1. `infra/compose/compose.yml`
2. `infra/emdash-spike/service.test.yml`
3. `infra/emdash-spike/visible-local.yml`

Enable the `emdash` profile. Start PostgreSQL, RustFS and Twenty first, then run
the `cms-db-operator` and `cms-storage-operator` one-off services before starting
the CMS. These operators provision the dedicated CMS database role, migrations,
identity mapping and private media bucket. Their profile keeps them out of
ordinary `up` operations. This local operator currently assumes the default
`leonaid` Core database and role; do not use it for a differently named database.

Open `https://localhost:<HTTPS port>/` visibly in the In-App Browser. Verify the
administration at `/admin/`, Core health at `/api/health/live`, CMS at `/_emdash/`
and the imported campaign at `/campaigns/krapfentaxi-2026/`. A reachable login page
is not proof of editorial access, and an empty database is not a campaign import.
Complete the existing designated-operator setup, synthetic Core seed, Twenty
provisioning and campaign import before claiming integrated acceptance. Do not
copy session cookies or database state from a parallel project.

After the visible designated-operator setup, stop only this project's
`campaign-site`. Run `cms-db-operator` with the command
`node tools/emdash_spike/initialize-local-campaign.mjs`, environment
`LEONAID_ENV=local`, and this project's `cms-bootstrap-state` volume mounted
read-only at `/app/bootstrap-state`. This installs the existing campaign schema,
binding and media guards without test pages or publication. It uses the dedicated
CMS role and one database connection. Restart the CMS only after success; on
failure leave it stopped and investigate. This is initial local preparation,
not the production migration/release procedure and not a campaign import.

For the Golden Krapfentaxi import, run the `local-campaign-import` one-off
service. Mount only this project's public Caddy root certificate read-only at
`/proof/root.crt` and set `NODE_EXTRA_CA_CERTS=/proof/root.crt`; never disable TLS
verification. Its default command is a dry run. After reviewing that result,
explicitly run `bun tools/emdash_spike/local-krapfentaxi-import.mjs apply`.
The operator logs in as the synthetic Golden System Admin through real Core and
Mailpit, uses that user's existing CMS identity mapping, and logs its own session
out afterwards. No session is inserted into SQL or copied from the browser.
The existing importer creates a draft only and refuses an automatic overwrite.
Inspect and publish the imported campaign through the visible CMS editor.

Caddy's local CA persists in the project-specific `visible-local-caddy-data`
volume. Trust must be established explicitly for the local browser; do not
disable origin checks, replace HTTPS with HTTP, or silently install a system CA.
Keep this browser stack available for interactive checks instead of deleting it
when the separate headless runner exits. It is not a production deployment.

Acceptance remains pending until the actual visible browser flows work. Record
the exact project, ports, source revision and observed results in the spike plan.
