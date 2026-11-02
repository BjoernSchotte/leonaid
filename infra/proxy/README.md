# Reverse Proxy

Caddy is the only service boundary that is normally bound on the host.
Locally it listens only on `127.0.0.1:8080`.

| Path | Target |
|---|---|
| `/` | Public web |
| `/app` and `/app/*` | Acquirer PWA; `/app` redirects to `/app/` |
| `/admin` and `/admin/*` | Internal web interface; `/admin` redirects to `/admin/` |
| `/api/*` | FastAPI |
| `http://crm.localhost:8080/` | Twenty, through the same proxy port |
| `/crm` and `/crm/*` | Alternative Twenty path; `/crm` redirects to `/crm/` |
| `/mail` and `/mail/*` | Mailpit in the `dev-mail` profile; `/mail` redirects to `/mail/` |
| `/mailing` and `/mailing/*` | Listmonk in the `mailing` profile; `/mailing` redirects to `/mailing/` |
