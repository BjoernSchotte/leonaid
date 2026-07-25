# Reverse Proxy

Caddy ist die einzige regulär am Host gebundene Servicegrenze. Lokal lauscht
sie ausschließlich auf `127.0.0.1:8080`.

| Pfad | Ziel |
|---|---|
| `/` | Public Web |
| `/app/*` | Akquisiteur-PWA |
| `/admin/*` | interne Weboberfläche |
| `/api/*` | FastAPI |
| `/crm/*` | Twenty |
| `/mail/*` | Mailpit im Profil `dev-mail` |
| `/mailing/*` | Listmonk im Profil `mailing` |
