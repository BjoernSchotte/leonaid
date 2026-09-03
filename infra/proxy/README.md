# Reverse Proxy

Caddy ist die einzige regulär am Host gebundene Servicegrenze. Lokal lauscht
sie ausschließlich auf `127.0.0.1:8080`.

| Pfad | Ziel |
|---|---|
| `/` | Public Web |
| `/app` und `/app/*` | Akquisiteur-PWA; `/app` wird auf `/app/` umgeleitet |
| `/admin` und `/admin/*` | interne Weboberfläche; `/admin` wird auf `/admin/` umgeleitet |
| `/api/*` | FastAPI |
| `http://crm.localhost:8080/` | Twenty, über denselben Proxy-Port |
| `/crm` und `/crm/*` | alternativer Twenty-Pfad; `/crm` wird auf `/crm/` umgeleitet |
| `/mail` und `/mail/*` | Mailpit im Profil `dev-mail`; `/mail` wird auf `/mail/` umgeleitet |
| `/mailing` und `/mailing/*` | Listmonk im Profil `mailing`; `/mailing` wird auf `/mailing/` umgeleitet |
